"""Unit tests for engine/dsl_cp_gate.py.

The gate makes any CP solver completely DSL-compliant via a
post-solve verify + no-good refinement loop:

  - ``verify_dsl_hard(sol, profs, hard_exprs)`` -> list of VIOLATED
    expression strings (uses the post-hoc general_dsl evaluator, so it
    can check ANY grammar expression, not just the compilable fragment).
  - ``add_nogood(model, slot, sol)`` -> forbid the EXACT assignment.
  - ``solve_with_dsl_refinement(solver, hard_exprs, profs, ...)`` ->
    solve / verify / no-good / re-solve, bounded by ``max_iters``.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "engine"))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)


def test_verify_dsl_hard_flags_violation():
    import dsl_cp_gate as g
    profs = {"T1": {"classi": {"1A": {"Mat": {"ore": 2}}}, "max_hours": 18}}
    sol = {("T1", "1A", "Mat", 1, 8): 1, ("T1", "1A", "Mat", 1, 9): 1}
    expr = ('forall l in lessons where l.teacher == "T1" '
            'and l.day == 1 and l.hour == 8: false')
    assert g.verify_dsl_hard(sol, profs, [expr]) == [expr]  # violated (T1 at 1,8)
    sol2 = {("T1", "1A", "Mat", 1, 9): 1, ("T1", "1A", "Mat", 1, 10): 1}
    assert g.verify_dsl_hard(sol2, profs, [expr]) == []      # satisfied


def test_add_nogood_forbids_exact_assignment():
    import dsl_cp_gate as g
    from ortools.sat.python import cp_model
    m = cp_model.CpModel()
    slot = {("T1", "1A", "Mat", 1, 8): m.NewBoolVar("a"),
            ("T1", "1A", "Mat", 1, 9): m.NewBoolVar("b")}
    # force the "bad" point a=1,b=0, then no-good it -> must change
    sol = {("T1", "1A", "Mat", 1, 8): 1, ("T1", "1A", "Mat", 1, 9): 0}
    g.add_nogood(m, slot, sol)
    # adding a constraint that pins exactly the bad point must now be infeasible
    m.Add(slot[("T1", "1A", "Mat", 1, 8)] == 1)
    m.Add(slot[("T1", "1A", "Mat", 1, 9)] == 0)
    s = cp_model.CpSolver()
    assert s.Solve(m) == cp_model.INFEASIBLE


def _ms(profs, dc, **cfg):
    """Build a MonolithicSolver on a tiny in-memory instance."""
    from cp_sat_constraint_model import MonolithicSolver, ConstraintConfig
    return MonolithicSolver(profs, dc, ConstraintConfig(**cfg))


def test_solve_dsl_compliant_enforces_hard_dsl():
    """``solve_dsl_compliant`` returns a HARD-feasible solution honoring a
    hard DSL expr the compiler does not natively guarantee.

    The instance places T1's six Mat hours on day 1 (one full school
    day). The forbid expr bans T1 from the sixth hour (1, 13). The
    plain solve would happily fill h8..h13 (the only contiguous-free,
    no-holes layout); the refinement must drop the (1,13) placement and
    re-solve until the rule holds -- which, with six hours and six
    slots, FORCES an empty sixth slot to be unreachable, so it instead
    spreads the cattedra across more days. We assert HARD feasibility,
    empty ``unsatisfied``, and that the rule verifies clean on the
    returned solution.
    """
    # T1 teaches 1A Mat for 6 hours across the week. No day-count fixed
    # (dc=None => weekly mode) so CP-SAT decides the day distribution.
    profs = {"T1": {"classi": {"1A": {"Mat": {"ore": 6}}},
                    "max_hours": 18, "min_free_days": 0}}
    expr = ('forall l in lessons where l.teacher == "T1" '
            'and l.day == 1 and l.hour == 13: false')

    ms = _ms(profs, None, enforce_no_holes=False)
    sol, status, unsatisfied = ms.solve_dsl_compliant(
        [expr], profs, max_iters=8, time_limit_s=10.0, workers=1)

    import dsl_cp_gate as g
    assert sol is not None, status
    assert unsatisfied == [], unsatisfied
    # No placed lesson has T1 at the forbidden (day1, hour13) cell.
    assert ("T1", "1A", "Mat", 1, 13) not in sol, sol
    # And the post-hoc evaluator confirms full compliance.
    assert g.verify_dsl_hard(sol, profs, [expr]) == []


def test_refinement_loop_accumulates_nogoods_until_compliant():
    """Exercise the refinement branch deterministically.

    ``solve_with_dsl_refinement`` must re-solicit ``solve_once`` once per
    violating solution, accumulating forbidden assignment-dicts, until a
    compliant solution is produced. We feed a synthetic ``solve_once``
    that returns a VIOLATING point on the first two calls and a compliant
    one on the third, asserting the forbidden list grew on each retry
    (proving the no-good accumulation drives the loop, independent of any
    CP objective steering the monolithic solver toward compliance on
    iteration 0).
    """
    import dsl_cp_gate as g

    profs = {"T1": {"classi": {"1A": {"Mat": {"ore": 2}}}, "max_hours": 18}}
    expr = ('forall l in lessons where l.teacher == "T1" '
            'and l.day == 1 and l.hour == 13: false')
    bad = {("T1", "1A", "Mat", 1, 13): 1}     # violates expr
    good = {("T1", "1A", "Mat", 1, 9): 1}      # satisfies expr
    seq = [bad, bad, good]
    seen_sizes = []

    def solve_once(forbidden):
        seen_sizes.append(len(forbidden))
        return seq[len(seen_sizes) - 1], "FEASIBLE"

    sol, status, unsatisfied = g.solve_with_dsl_refinement(
        solve_once, profs, [expr], max_iters=8)

    assert sol == good
    assert unsatisfied == []
    # forbidden list size on each call: 0 (first), 1, 2 -> accumulation.
    assert seen_sizes == [0, 1, 2], seen_sizes


def test_refinement_reports_unsatisfied_at_budget_exhaustion():
    """When the violation never clears within ``max_iters``, the helper
    returns the still-violated expr list (the honest 'couldn't comply'
    signal) rather than crashing or looping forever."""
    import dsl_cp_gate as g

    profs = {"T1": {"classi": {"1A": {"Mat": {"ore": 1}}}, "max_hours": 18}}
    expr = ('forall l in lessons where l.teacher == "T1" '
            'and l.day == 1 and l.hour == 13: false')
    bad = {("T1", "1A", "Mat", 1, 13): 1}

    def solve_once(forbidden):
        return dict(bad), "FEASIBLE"   # always violates

    sol, status, unsatisfied = g.solve_with_dsl_refinement(
        solve_once, profs, [expr], max_iters=3)
    assert sol == bad
    assert unsatisfied == [expr]
