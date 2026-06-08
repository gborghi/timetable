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
