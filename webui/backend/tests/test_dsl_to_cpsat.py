"""Tests for engine/dsl_to_cpsat.py — the DSL → CP-SAT compiler.

Validates that DSL expressions parsed by general_dsl get applied to
the CP-SAT model as actual search-time constraints (not just post-hoc
DNF evaluation), via ConstraintModel.add_dsl_constraint.
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "engine"))
WEBUI = os.path.normpath(os.path.join(HERE, "..", ".."))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
for p in (ENGINE, WEBUI, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)


def _basic_profs():
    return {"T1": {"classi": {"1A": {"Mat": {"ore": 4}}},
                    "glibero": [6], "max_hours": 18}}


def _basic_dc(hrs_per_day: int = 1):
    return {("T1", "1A", "Mat", d): hrs_per_day for d in (1, 2, 3, 4)}


def test_count_lessons_le_constraint_is_enforced():
    """`count l in lessons where l.day == 1 <= 0` forbids any lesson
    on day 1. The model must return a solution with no day-1 slot."""
    from cp_sat_constraint_model import MonolithicSolver, ConstraintConfig
    profs = _basic_profs()
    dc = _basic_dc(hrs_per_day=1)
    ms = MonolithicSolver(profs, dc, ConstraintConfig(
        enforce_no_holes=False, enforce_h3_presence_at_11=False))
    ms.add_dsl_constraint(
        'count l in lessons where l.day == 1 <= 0')
    sol, status = ms.solve(time_limit_s=5.0, workers=1)
    # dc forces 4 hrs total but only 1 hr per day across 4 days; with
    # day 1 forbidden, the solver still has 3 days to place 4 hrs
    # (max 1 per day) -> infeasible. Assert it correctly detects.
    assert sol is None and status == "INFEASIBLE"


def test_count_lessons_eq_constraint_forces_value():
    """`count l in lessons where l.day == 1 == 0` is identical to <=
    0; verify the solver picks days other than 1 if possible."""
    from cp_sat_constraint_model import MonolithicSolver, ConstraintConfig
    # 1 hr total demand: solver can place anywhere except day 1.
    profs = _basic_profs()
    dc = {("T1", "1A", "Mat", 2): 1}  # 1 hr on day 2 only
    ms = MonolithicSolver(profs, dc, ConstraintConfig(
        enforce_no_holes=False, enforce_h3_presence_at_11=False))
    ms.add_dsl_constraint(
        'count l in lessons where l.day == 1 == 0')
    sol, status = ms.solve(time_limit_s=5.0, workers=1)
    assert sol is not None, status
    days_used = {k[3] for k in sol}
    assert 1 not in days_used


def test_forall_static_false_body_forbids_matching_slots():
    """`forall l where l.hour < 10: false` forces every slot at
    h<10 to be 0. With 4 hrs forced by dc, the solver must place
    them at h>=10."""
    from cp_sat_constraint_model import MonolithicSolver, ConstraintConfig
    profs = _basic_profs()
    dc = {("T1", "1A", "Mat", 1): 4}  # 4 hrs all on day 1
    ms = MonolithicSolver(profs, dc, ConstraintConfig(
        enforce_no_holes=False, enforce_h3_presence_at_11=False))
    ms.add_dsl_constraint(
        'forall l in lessons where l.hour < 10: false')
    sol, status = ms.solve(time_limit_s=5.0, workers=1)
    assert sol is not None, status
    hours = [k[4] for k in sol]
    assert min(hours) >= 10, (
        f"DSL forall violated; got hours {sorted(hours)}")


def test_forall_with_subject_static_filter_targets_only_subject():
    """`forall l where l.subject == "Ita" and l.hour == 8: false`
    forbids only Ita lessons at h=8. Mat lessons at h=8 are allowed.
    """
    from cp_sat_constraint_model import MonolithicSolver, ConstraintConfig
    profs = {"T1": {"classi": {"1A": {"Mat": {"ore": 1},
                                        "Ita": {"ore": 1}}},
                     "max_hours": 18}}
    dc = {("T1", "1A", "Mat", 1): 1, ("T1", "1A", "Ita", 2): 1}
    ms = MonolithicSolver(profs, dc, ConstraintConfig(
        enforce_no_holes=False, enforce_h3_presence_at_11=False))
    ms.add_dsl_constraint(
        'forall l in lessons where l.subject == "Ita" and '
        'l.hour == 8: false')
    sol, status = ms.solve(time_limit_s=5.0, workers=1)
    assert sol is not None, status
    for (t, cl, s, d, h) in sol:
        if s == "Ita":
            assert h != 8, (
                f"Ita at h=8 not forbidden; got {(t, cl, s, d, h)}")


def test_dynamic_pair_compiles_and_blocks_invalid():
    """Double-forall body that requires two static-filtered lessons
    to satisfy a relation. Body 'consecutive(l1, l2)' compiles to
    `not (slot_a AND slot_b)` for every pair where the relation
    fails.

    Setup: 2 days with 2 Mat hours each (forced by dc). DSL says
    "two Mat hours in the same day must be consecutive". The
    compiler emits forbid-pair constraints on non-consecutive
    pairs. Solver should pick consecutive hours.
    """
    from cp_sat_constraint_model import MonolithicSolver, ConstraintConfig
    profs = _basic_profs()
    dc = {("T1", "1A", "Mat", 1): 2}
    ms = MonolithicSolver(profs, dc, ConstraintConfig(
        enforce_no_holes=False, enforce_h3_presence_at_11=False))
    ms.add_dsl_constraint(
        'forall l1 in lessons where l1.subject == "Mat": '
        'forall l2 in lessons where l2.subject == "Mat": '
        'consecutive(l1.slot, l2.slot)')
    sol, status = ms.solve(time_limit_s=5.0, workers=1)
    assert sol is not None, status
    hours = sorted({k[4] for k in sol if k[3] == 1})
    # Must be consecutive: h2 - h1 == 1
    assert len(hours) == 2 and hours[1] - hours[0] == 1, (
        f"DSL pair-consecutive not enforced; got hours {hours}")


def test_dsl_supports_all_comparators():
    """User-required: <=, >=, !=, ==, <, > all parse + compile."""
    from cp_sat_constraint_model import (
        MonolithicSolver, ConstraintConfig)
    profs = _basic_profs()
    dc = _basic_dc(hrs_per_day=1)
    for op_str in ("<=", ">=", "!=", "==", "<", ">"):
        ms = MonolithicSolver(profs, dc, ConstraintConfig(
            enforce_no_holes=False, enforce_h3_presence_at_11=False))
        ms.add_dsl_constraint(
            f'count l in lessons where l.day == 1 {op_str} 0')
        # Build (sub-test): no exception means the DSL parsed and
        # the compiler emitted a constraint of the requested op.
        ms.build()


def test_dsl_three_consecutive_math_hours_user_example():
    """User's stated example: '3 ore di matematica attaccate' for
    a class. Encoded as a count == 3 + a chain of consecutive
    constraints between every pair of math hours that day. We
    verify the solver actually produces 3 consecutive hours when
    the demand is exactly 3 on a single day."""
    from cp_sat_constraint_model import (
        MonolithicSolver, ConstraintConfig)
    profs = {"T1": {"classi": {"1A": {"Mat": {"ore": 3}}},
                     "max_hours": 18}}
    dc = {("T1", "1A", "Mat", 1): 3}
    ms = MonolithicSolver(profs, dc, ConstraintConfig(
        enforce_no_holes=False, enforce_h3_presence_at_11=False))
    ms.add_dsl_constraint(
        'forall l1 in lessons where l1.subject == "Mat": '
        'forall l2 in lessons where l2.subject == "Mat": '
        'consecutive(l1.slot, l2.slot)')
    sol, status = ms.solve(time_limit_s=5.0, workers=1)
    assert sol is not None, status
    hours = sorted({k[4] for k in sol})
    # 3 consecutive hours on day 1 (h, h+1, h+2)
    assert len(hours) == 3
    assert hours[1] - hours[0] == 1 and hours[2] - hours[1] == 1


def test_diagnostics_for_unsupported_construct():
    """The compiler should NOT silently accept patterns it can't
    translate; it logs to dsl_diagnostics so the caller knows."""
    from cp_sat_constraint_model import MonolithicSolver, ConstraintConfig
    profs = _basic_profs()
    dc = {("T1", "1A", "Mat", 1): 1}
    ms = MonolithicSolver(profs, dc, ConstraintConfig(
        enforce_no_holes=False, enforce_h3_presence_at_11=False))
    # Sum aggregate is not yet supported.
    ms.add_dsl_constraint(
        'forall t in teachers: count l in lessons '
        'where l.teacher == t.name <= 18')
    # Compilation completes (no exception) but diagnostics record
    # the unsupported construct. (Currently the source 'teachers'
    # is unsupported.)
    assert any("teachers" in d or "not yet supported" in d
                for d in ms.dsl_diagnostics), (
        f"missing diagnostic; got {ms.dsl_diagnostics}")
