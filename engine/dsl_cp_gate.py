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
        import general_dsl as gd  # type: ignore
    except ImportError:
        import os
        import sys
        _eng = os.path.dirname(os.path.abspath(__file__))
        if _eng not in sys.path:
            sys.path.insert(0, _eng)
        import general_dsl as gd  # type: ignore
    return gd


def _build_world(sol, profs, *, day=None):
    """Build the general_dsl ``world`` dict from an in-memory solution.

    Delegates to ``metaheuristics._build_world_from_sol`` so the world
    shape is identical to the one the metaheuristic universal solver
    feeds the evaluator.

    When ``day`` is not ``None`` the world's ``days`` table is projected
    to that single day. This is REQUIRED on the per-day CP path: a
    per-day solve only carries one day's lessons, but the DSL evaluator's
    per-day pragmas (e.g. ``class_day_load_in``) iterate over EVERY day
    in ``world["days"]`` -- with the full 6-day table, the five absent
    days each read an empty class load and a "load must be in {4,5,6}"
    rule would spuriously report VIOLATED. Projecting to the solved day
    makes verification correct for the slice the per-day model owns.
    """
    try:
        from . import metaheuristics as mh  # type: ignore
    except ImportError:
        import metaheuristics as mh  # type: ignore
    world = mh._build_world_from_sol(sol, profs)
    if day is not None:
        world = dict(world)
        world["days"] = [{"index": int(day), "name": ""}]
    return world


def screen_dsl_hard(sol, profs, hard_exprs, *, day=None):
    """Split ``hard_exprs`` into ``(violated, unverifiable)`` against ``sol``.

    - ``violated``: parseable AND evaluable AND the rule evaluated
      ``False``. A no-good over this exact assignment can rule the point
      out, so the refinement loop CAN act on these.
    - ``unverifiable``: the expression could NOT be parsed, OR its
      evaluation raised (``evaluate_safe`` reports a non-``None`` error,
      i.e. the ``True``-on-error default fired). A HARD rule reaches this
      gate precisely because the CP compiler declined it; if it *also*
      cannot be certified here it can be neither compiled nor verified, so
      it MUST fail closed -- accepting the solution would be the
      silent-pass bug (audit H6 residual). A no-good cannot fix it, so the
      caller must stop refining and surface it rather than spinning.

    ``day`` (per-day CP path only): project the evaluation world to that
    single day so per-day pragmas are checked against the slice the
    per-day model actually owns (see ``_build_world``). ``None`` (the
    week / whole-solution path) keeps the full-week world unchanged.
    """
    if not hard_exprs:
        return [], []
    gd = _gd()
    world = _build_world(sol, profs, day=day)
    violated, unverifiable = [], []
    for e in hard_exprs:
        try:
            tree = gd.parse(e)
        except Exception:  # noqa: BLE001 - unparseable HARD rule: fail closed
            unverifiable.append(e)
            continue
        ok, err = gd.evaluate_safe(tree, world)
        if err is not None:      # eval raised -> True-on-error masked it
            unverifiable.append(e)
        elif not ok:
            violated.append(e)
    return violated, unverifiable


def verify_dsl_hard(sol, profs, hard_exprs, *, day=None):
    """Return the hard-DSL expression strings NOT SATISFIED by ``sol``.

    This is ``violated + unverifiable`` from :func:`screen_dsl_hard`: a
    HARD rule that cannot be verified (unparseable, or its evaluation
    raised) is treated as NOT satisfied and therefore fails closed -- it
    is never silently accepted. Callers that must distinguish "fixable by
    a no-good" from "un-fixable, must fail closed" should call
    :func:`screen_dsl_hard` directly.

    ``day`` (per-day CP path only): project the evaluation world to that
    single day so per-day pragmas are checked against the slice the
    per-day model actually owns (see ``_build_world``). ``None`` (the
    week / whole-solution path) keeps the full-week world unchanged.
    """
    violated, unverifiable = screen_dsl_hard(sol, profs, hard_exprs, day=day)
    return violated + unverifiable


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
        violated, unverifiable = screen_dsl_hard(sol, profs, hard_exprs)
        if unverifiable:
            # A HARD rule we can neither compile nor certify: a no-good
            # cannot fix it, so stop refining and surface it. The caller
            # fails closed on a non-empty unsatisfied list (STRICT),
            # exactly as for a genuine infeasibility.
            return sol, status, unverifiable + violated
        if not violated:
            return sol, status, []           # fully compliant
        forbidden.append(dict(sol))
    violated, unverifiable = screen_dsl_hard(last_sol, profs, hard_exprs)
    return last_sol, last_status, unverifiable + violated
