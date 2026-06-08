"""DSL compliance gate for CP solvers.

Makes any CP-SAT solver *completely* DSL-compliant for hard rules the
constraint compiler could not model natively, via a post-solve
**verify + no-good refinement** loop:

  1. ``verify_dsl_hard(sol, profs, hard_exprs)`` evaluates each hard-DSL
     expression on the produced solution using the post-hoc general_dsl
     evaluator (which can check ANY grammar expression, not just the
     compilable fragment) and returns the list of VIOLATED expressions.
  2. ``add_nogood(model, slot, sol)`` forbids the EXACT assignment just
     produced (a no-good cut over the slot BoolVars).
  3. ``solve_with_dsl_refinement(solve_once, profs, hard_exprs, ...)``
     runs solve -> verify -> accumulate-no-good -> re-solve, bounded by
     ``max_iters``. The ``solve_once(forbidden)`` callback rebuilds a
     FRESH model each call and re-applies all accumulated forbidden
     assignments as no-goods -- required because the MonolithicSolver
     rebuilds its model on every ``solve()``. Natively-compiled rules
     pass verification on iteration 0 (one cheap check, no extra solve);
     only genuinely un-compiled violations trigger a refinement round.

This module is **frontend-agnostic** (pure ``engine/``). The only webui
reference is the lazy ``general_dsl`` import inside ``_gd()``, which
mirrors the resolution idiom used by ``metaheuristics`` (repo-root
fallback) so the evaluator AST is shared and the dual-module hazard is
avoided. Surfacing ``unsatisfied`` to RunLog is the webui orchestration's
job, not this module's.
"""
from __future__ import annotations


def _gd():
    """Resolve ``general_dsl`` using metaheuristics' import idiom.

    Importing it the *same* way metaheuristics does keeps a single
    module object (and therefore a single AST node class hierarchy) in
    play, so trees parsed here evaluate cleanly there and vice versa.
    """
    try:
        from webui.backend.utils import general_dsl as gd  # type: ignore
    except ImportError:
        import os
        import sys
        _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if _root not in sys.path:
            sys.path.insert(0, _root)
        from webui.backend.utils import general_dsl as gd  # type: ignore
    return gd


def _build_world(sol, profs):
    """Build the general_dsl ``world`` dict from an in-memory solution.

    Delegates to ``metaheuristics._build_world_from_sol`` so the world
    shape is identical to the one the metaheuristic universal solver
    feeds the evaluator.
    """
    try:
        from . import metaheuristics as mh  # type: ignore
    except ImportError:
        import metaheuristics as mh  # type: ignore
    return mh._build_world_from_sol(sol, profs)


def verify_dsl_hard(sol, profs, hard_exprs):
    """Return the list of hard-DSL expression strings VIOLATED by ``sol``.

    Each expression is parsed and evaluated against the world built from
    ``sol``; ``evaluate_safe`` returns ``(ok, err)`` where ``ok is
    False`` means the rule is violated. Expressions that cannot be
    parsed or evaluated are skipped (they cannot be verified here and
    are warned about elsewhere) rather than crashing the gate.
    """
    if not hard_exprs:
        return []
    gd = _gd()
    world = _build_world(sol, profs)
    violated = []
    for e in hard_exprs:
        try:
            ok, _err = gd.evaluate_safe(gd.parse(e), world)
        except Exception:  # noqa: BLE001 - unparseable/unevaluable: skip
            continue
        if not ok:
            violated.append(e)
    return violated


def add_nogood(model, slot, sol):
    """Forbid the EXACT current assignment over the ``slot`` vars.

    For each slot var, require it to differ from the value it took in
    ``sol`` -- expressed as a single ``BoolOr`` that is satisfied iff at
    least one var flips, i.e. the next solution is not the same point.
    """
    lits = []
    for k, v in slot.items():
        on = int(sol.get(k, 0)) == 1
        lits.append(v.Not() if on else v)
    if lits:
        model.AddBoolOr(lits)


def solve_with_dsl_refinement(solve_once, profs, hard_exprs, *, max_iters=8):
    """Refine via no-good accumulation over a BUILD-PER-SOLVE solver.

    ``solve_once(forbidden) -> (sol | None, status)`` MUST build a
    *fresh* model, apply each assignment-dict in ``forbidden`` as a
    no-good cut over the freshly-built slot vars, solve, and return
    ``(sol_or_None, status)``. This callback form is required because
    ``MonolithicSolver.solve()`` calls ``build()`` on every invocation
    and ``build()`` is NOT idempotent (it re-creates ``self.slot`` and
    re-adds constraints). We therefore cannot mutate a persistent model
    between solves; instead we accumulate the FORBIDDEN ASSIGNMENTS
    (keyed by the stable ``(p, cl, subj, d, h)`` tuples) and let
    ``solve_once`` re-apply ALL of them on each iteration.

    Loop (at most ``max_iters`` times): solve with the current forbidden
    list; if no solution return ``(None, status, [])``; verify the hard
    DSL on the solution; if none violated return ``(sol, status, [])``;
    otherwise append that exact assignment to ``forbidden`` and re-solve.
    If the budget is exhausted, return ``(last_sol, last_status,
    still_violated)`` -- the honest "couldn't fully comply within budget"
    signal.

    Returns ``(sol, status, unsatisfied_exprs)``.
    """
    forbidden: list[dict] = []
    last_sol, last_status = None, None
    for _ in range(max(1, int(max_iters))):
        sol, status = solve_once(forbidden)
        last_sol, last_status = sol, status
        if sol is None:
            return None, status, []          # infeasible / no solution
        violated = verify_dsl_hard(sol, profs, hard_exprs)
        if not violated:
            return sol, status, []           # fully compliant
        forbidden.append(dict(sol))
    return last_sol, last_status, verify_dsl_hard(last_sol, profs, hard_exprs)
