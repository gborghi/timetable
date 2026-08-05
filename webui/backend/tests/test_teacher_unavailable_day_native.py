"""Audit F7: a mandatory free day (`teacher_unavailable_day`) must be
COMPILED NATIVELY on the Phase-B / week path, not left to the no-good gate.
The compiler has always had the path (`_compile_teacher_unavailable_day` ->
`_compile_teacher_day_capacity(t, d, 0)` -> `sum(slots) <= 0`); the week run
that failed did so because the post-hoc GATE verifier could not evaluate the
rule (missing `general_dsl` evaluator -> fail-closed -> no-good exhaustion),
which the F1 evaluators fixed. These lock in the native compile at the week
level (`level="phase_b"`), so the gate is only ever a passing safety net.
"""
from ortools.sat.python import cp_model

import dsl_to_cpsat as d2c


def _model_with_teacher_on_two_days():
    m = cp_model.CpModel()
    slot = {}
    for d in (1, 2):
        for h in (8, 9):
            slot[("T", "1A", "Mat", d, h)] = m.NewBoolVar(f"s_{d}_{h}")
    return m, slot


def test_native_compile_forbids_the_free_day_at_phase_b_level():
    m, slot = _model_with_teacher_on_two_days()
    m.Add(sum(slot.values()) >= 2)   # 2 lessons must be placed somewhere
    comp = d2c.DSLConstraintCompiler(m, slot, level="phase_b", is_hard=True)
    comp.compile('teacher_unavailable_day("T", 1)')
    # No compile_failed / "nothing to bound" diagnostic: it compiled natively.
    assert comp.diagnostics == [], comp.diagnostics
    s = cp_model.CpSolver()
    assert s.Solve(m) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    day1 = sum(s.Value(slot[("T", "1A", "Mat", 1, h)]) for h in (8, 9))
    assert day1 == 0, "teacher scheduled on their mandatory free day"


def test_forcing_work_on_the_free_day_is_infeasible():
    """The native constraint is HARD: pin a lesson on the blocked day and the
    model is INFEASIBLE (proving it is a real constraint, not a soft hint)."""
    m, slot = _model_with_teacher_on_two_days()
    m.Add(slot[("T", "1A", "Mat", 1, 8)] == 1)   # force work on day 1
    comp = d2c.DSLConstraintCompiler(m, slot, level="phase_b", is_hard=True)
    comp.compile('teacher_unavailable_day("T", 1)')
    assert comp.diagnostics == [], comp.diagnostics
    assert cp_model.CpSolver().Solve(m) == cp_model.INFEASIBLE
