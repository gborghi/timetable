"""Tests for the Step 3b canonical-pattern vocabulary.

The DSL compiler recognises a small set of named-call pragmas that
match 1:1 with the legacy hardcoded HARD constraints
(``no_holes_class``, ``class_present_at_hour``,
``teacher_max_per_day``, ...). Each pragma compiles to the same
compact CP-SAT encoding that the legacy code uses. These tests
verify two properties:

  1. Each pragma alone compiles to a feasible CP-SAT model and
     the produced solution honours the rule's semantics.
  2. Pragma vs legacy zero-drift: a model built ONLY from the
     pragma yields the same set of feasible patterns as a model
     built from the equivalent legacy method.
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


# ----- helpers -----


def _make_solver(profs, dc, *, no_holes=False, h11=False,
                  motorie=False, mat_ita=False):
    from cp_sat_constraint_model import (
        MonolithicSolver, ConstraintConfig)
    return MonolithicSolver(profs, dc, ConstraintConfig(
        enforce_no_holes=no_holes,
        enforce_h3_presence_at_11=h11,
        enforce_motorie_pair=motorie,
        enforce_math_italian_pair=mat_ita,
    ))


# ============================================================
# no_holes_class
# ============================================================


def test_no_holes_class_pragma_compiles_and_enforces():
    """The pragma forbids holes (busy, free, busy on the same day)
    for the named class. With 4 hours/day demand and a 6-hour
    window, the solver must place them contiguously starting at
    h_min."""
    profs = {"T1": {"classi": {"1A": {"Mat": {"ore": 4}}},
                     "max_hours": 18}}
    dc = {("T1", "1A", "Mat", 1): 4}
    ms = _make_solver(profs, dc)
    ms.add_dsl_constraint('no_holes_class("1A")')
    sol, status = ms.solve(time_limit_s=5.0, workers=1)
    assert sol is not None, status
    busy_hours = sorted(k[4] for k in sol if k[3] == 1)
    # Contiguous starting at h=8.
    assert busy_hours == [8, 9, 10, 11], busy_hours


def test_no_holes_class_pragma_forbids_isolated_hour():
    """With 1 hr in middle of the day, no-holes still must start at
    h=8 (i.e. the first slot is busy)."""
    profs = {"T1": {"classi": {"1A": {"Mat": {"ore": 1}}},
                     "max_hours": 18}}
    dc = {("T1", "1A", "Mat", 1): 1}
    ms = _make_solver(profs, dc)
    ms.add_dsl_constraint('no_holes_class("1A")')
    sol, status = ms.solve(time_limit_s=5.0, workers=1)
    assert sol is not None, status
    h_busy = next(k[4] for k in sol if k[3] == 1)
    assert h_busy == 8, h_busy  # starts at h_min


def test_no_holes_class_zero_drift_vs_legacy():
    """Same model, same input, same constraints: pragma and legacy
    must produce the same feasibility outcome."""
    profs = {"T1": {"classi": {"1A": {"Mat": {"ore": 4}}},
                     "max_hours": 18}}
    dc = {("T1", "1A", "Mat", 1): 4}
    # Legacy: enforce_no_holes=True via config
    legacy = _make_solver(profs, dc, no_holes=True)
    sol_l, status_l = legacy.solve(time_limit_s=5.0, workers=1)
    # Pragma: no_holes off in config, pragma DSL adds it back
    pragma = _make_solver(profs, dc, no_holes=False)
    pragma.add_dsl_constraint('no_holes_class("1A")')
    sol_p, status_p = pragma.solve(time_limit_s=5.0, workers=1)
    assert (sol_l is not None) == (sol_p is not None)
    if sol_l is not None:
        # Both should find a feasible 4-contiguous-hour pattern
        hb_l = sorted(k[4] for k in sol_l if k[3] == 1)
        hb_p = sorted(k[4] for k in sol_p if k[3] == 1)
        # Same shape: contiguous, 4 hours, starts at h_min.
        assert hb_l == hb_p == [8, 9, 10, 11], (hb_l, hb_p)


# ============================================================
# class_present_at_hour
# ============================================================


def test_class_present_at_hour_forces_h_when_any_lesson():
    """If a class has any lesson on a day, h=11 must be busy."""
    profs = {"T1": {"classi": {"1A": {"Mat": {"ore": 1}}},
                     "max_hours": 18}}
    dc = {("T1", "1A", "Mat", 1): 1}
    ms = _make_solver(profs, dc)
    ms.add_dsl_constraint('class_present_at_hour("1A", 11)')
    sol, status = ms.solve(time_limit_s=5.0, workers=1)
    assert sol is not None, status
    # The single lesson must be at h=11.
    assert next(k[4] for k in sol if k[3] == 1) == 11


def test_class_present_at_hour_zero_drift_vs_legacy():
    """Pragma vs add_h3_presence_at_11. add_h3_presence_at_11 in
    the legacy is only chained on when no-holes is enabled, so we
    invoke it directly on a no-holes-off model to compare apples to
    apples."""
    from cp_sat_constraint_model import (
        MonolithicSolver, ConstraintConfig)
    profs = {"T1": {"classi": {"1A": {"Mat": {"ore": 1}}},
                     "max_hours": 18}}
    dc = {("T1", "1A", "Mat", 1): 1}
    legacy = MonolithicSolver(profs, dc, ConstraintConfig(
        enforce_no_holes=False, enforce_h3_presence_at_11=False))
    legacy.add_teacher_no_overlap()
    legacy.add_h3_presence_at_11()
    obj_terms, _ = legacy.compute_soft_cost_expr()
    if obj_terms:
        legacy.model.Minimize(sum(obj_terms))
    from ortools.sat.python import cp_model
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = 5.0
    s.Solve(legacy.model)
    h_l = next(k[4] for k in legacy.slot
                if k[3] == 1 and s.Value(legacy.slot[k]) == 1)

    pragma = _make_solver(profs, dc)
    pragma.add_dsl_constraint('class_present_at_hour("1A", 11)')
    sol_p, _ = pragma.solve(time_limit_s=5.0, workers=1)
    h_p = next(k[4] for k in sol_p if k[3] == 1)
    assert h_l == h_p == 11


# ============================================================
# teacher_max_per_day
# ============================================================


def test_teacher_max_per_day_caps_daily_load():
    """Teacher load <= 2 / day. With 6 demand-hours forced into one
    day, the rule must make it infeasible."""
    profs = {"T1": {"classi": {"1A": {"Mat": {"ore": 6}}},
                     "max_hours": 18}}
    dc = {("T1", "1A", "Mat", 1): 6}
    ms = _make_solver(profs, dc)
    ms.add_dsl_constraint('teacher_max_per_day("T1", 2)')
    sol, status = ms.solve(time_limit_s=5.0, workers=1)
    assert sol is None and status == "INFEASIBLE"


def test_teacher_max_per_day_allows_when_under_cap():
    """Teacher load <= 5 / day. 4 hours per day passes."""
    profs = {"T1": {"classi": {"1A": {"Mat": {"ore": 4}}},
                     "max_hours": 18}}
    dc = {("T1", "1A", "Mat", 1): 4}
    ms = _make_solver(profs, dc)
    ms.add_dsl_constraint('teacher_max_per_day("T1", 5)')
    sol, _ = ms.solve(time_limit_s=5.0, workers=1)
    assert sol is not None
    assert sum(1 for k in sol) == 4


# ============================================================
# cattedra_max_per_day
# ============================================================


def test_cattedra_max_per_day_pragma():
    """Per-cattedra cap: 2 hours/day for (T1, 1A, Mat). With 4
    forced in one day, infeasible."""
    profs = {"T1": {"classi": {"1A": {"Mat": {"ore": 4}}},
                     "max_hours": 18}}
    dc = {("T1", "1A", "Mat", 1): 4}
    ms = _make_solver(profs, dc)
    ms.add_dsl_constraint(
        'cattedra_max_per_day("T1", "1A", "Mat", 2)')
    sol, status = ms.solve(time_limit_s=5.0, workers=1)
    assert sol is None and status == "INFEASIBLE"


# ============================================================
# subject_pair_must / subject_pair_exists
# ============================================================


def test_subject_pair_must_forces_consecutive():
    """Scienzemotorie pattern: 2 hr/day must be consecutive."""
    profs = {"T1": {"classi": {"1A": {
        "Scienzemotorie": {"ore": 2}}}, "max_hours": 18}}
    dc = {("T1", "1A", "Scienzemotorie", 1): 2}
    ms = _make_solver(profs, dc)
    ms.add_dsl_constraint(
        'subject_pair_must("1A", "Scienzemotorie")')
    sol, status = ms.solve(time_limit_s=5.0, workers=1)
    assert sol is not None, status
    hours = sorted(k[4] for k in sol)
    assert len(hours) == 2 and hours[1] - hours[0] == 1, hours


def test_subject_pair_exists_pragma_with_three_hours():
    """Mat/Ita pattern: when >= 2 hr/day, at least one consecutive
    pair. With 3 hours, any two-of-them being consecutive is fine."""
    profs = {"T1": {"classi": {"1A": {"Mat": {"ore": 3}}},
                     "max_hours": 18}}
    dc = {("T1", "1A", "Mat", 1): 3}
    ms = _make_solver(profs, dc)
    ms.add_dsl_constraint(
        'subject_pair_exists("1A", "Mat")')
    sol, status = ms.solve(time_limit_s=5.0, workers=1)
    assert sol is not None, status
    hours = sorted(k[4] for k in sol)
    # 3 hrs -- the pragma requires at least one consecutive pair.
    has_pair = any(hours[i + 1] - hours[i] == 1
                    for i in range(len(hours) - 1))
    assert has_pair, hours


# ============================================================
# class_day_load_in
# ============================================================


def test_class_day_load_in_forbids_disallowed_load():
    """With (T1, 1A, Mat) 5 hours total + dc spread {0,4,5,6}-only
    rule, ensure 1, 2, 3 hours/day are forbidden."""
    profs = {"T1": {"classi": {"1A": {"Mat": {"ore": 5}}},
                     "max_hours": 18}}
    # Force 3 hrs on day 1 + 2 hrs on day 2 -- both disallowed.
    dc = {("T1", "1A", "Mat", 1): 3,
          ("T1", "1A", "Mat", 2): 2}
    ms = _make_solver(profs, dc)
    ms.add_dsl_constraint(
        'class_day_load_in("1A", 0, 4, 5, 6)')
    sol, status = ms.solve(time_limit_s=5.0, workers=1)
    assert sol is None and status == "INFEASIBLE"


def test_class_day_load_in_accepts_allowed_load():
    """4 hrs in one day is in the allowed set -- feasible."""
    profs = {"T1": {"classi": {"1A": {"Mat": {"ore": 4}}},
                     "max_hours": 18}}
    dc = {("T1", "1A", "Mat", 1): 4}
    ms = _make_solver(profs, dc)
    ms.add_dsl_constraint(
        'class_day_load_in("1A", 0, 4, 5, 6)')
    sol, _ = ms.solve(time_limit_s=5.0, workers=1)
    assert sol is not None and sum(1 for k in sol if k[3] == 1) == 4


# ============================================================
# Translator round-trip
# ============================================================


def test_translator_class_no_holes_emits_pragma():
    """class_no_holes_to_dsl must emit the pragma form, parseable
    by general_dsl, and recognised by the compiler."""
    import dsl_translator as dt
    from webui.backend.utils import general_dsl as gd
    expr = dt.class_no_holes_to_dsl("1A")
    assert "no_holes_class" in expr
    tree = gd.parse(expr)
    assert tree is not None


def test_translator_h11_presence_emits_pragma():
    import dsl_translator as dt
    from webui.backend.utils import general_dsl as gd
    expr = dt.class_h11_presence_to_dsl("1A")
    assert "class_present_at_hour" in expr
    gd.parse(expr)


def test_translator_class_day_load_in_emits_pragma():
    import dsl_translator as dt
    from webui.backend.utils import general_dsl as gd
    expr = dt.class_day_load_in_to_dsl("1A", [0, 4, 5, 6])
    assert "class_day_load_in" in expr
    gd.parse(expr)


def test_translator_teacher_max_per_day_emits_pragma():
    import dsl_translator as dt
    from webui.backend.utils import general_dsl as gd
    expr = dt.teacher_max_per_day_to_dsl("Rossi", 5)
    assert "teacher_max_per_day" in expr
    gd.parse(expr)


def test_translator_subject_pair_must_emits_pragma():
    import dsl_translator as dt
    from webui.backend.utils import general_dsl as gd
    expr = dt.subject_pair_must_to_dsl("1A", "Scienzemotorie")
    assert "subject_pair_must" in expr
    gd.parse(expr)
