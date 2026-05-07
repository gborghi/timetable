"""Tests for the Phase A IntVar DSL pragmas (Step 1 of the multi-day
DSL plan).

The DSL compiler grew a new family of pragmas that operate on the
``day_count[(t, c, s, d)]`` IntVar level instead of the per-hour
``slot[(t, c, s, d, h)]`` BoolVar level. They mirror the constraints
``cpsat_v2_timetable.solve_phase_a`` enforces directly so a future
``DayCountModel`` can build the same Phase A problem from DSL alone.

Each test stands up a tiny CP-SAT model with day_count IntVars only
(no slot Bools), compiles a single pragma, then either solves the
model or asserts infeasibility. Pragmas are tagged with ``level=
"phase_a"`` in the compiler's PRAGMA_LEVEL registry; the level
filter on the compiler is also exercised here.
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


def _build_dc_model(triples, *, max_per_day=2, days=range(1, 7)):
    """Construct a tiny CP-SAT model with day_count IntVars for the
    given triples ``(prof, class, subject, ore)``. Enforces the weekly
    sum equality (sum_d day_count == ore) so the solver problem is a
    legitimate Phase A skeleton."""
    from ortools.sat.python import cp_model
    model = cp_model.CpModel()
    days = list(days)
    day_count = {}
    for (p, cl, s, ore) in triples:
        for d in days:
            day_count[(p, cl, s, d)] = model.NewIntVar(
                0, min(max_per_day, ore),
                f"dc_{p}_{cl}_{s}_{d}")
        model.Add(
            sum(day_count[(p, cl, s, d)] for d in days) == ore
        )
    return model, day_count, days


def _solve(model, time_limit=2.0):
    from ortools.sat.python import cp_model
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = time_limit
    s.parameters.num_search_workers = 1
    status = s.Solve(model)
    return s, status


# ============================================================
# PRAGMA_LEVEL registry + level filter
# ============================================================


def test_pragma_level_registry_classifies_phase_a_and_b():
    import dsl_to_cpsat as d2c
    # All five Phase A pragmas registered correctly
    for name in ("class_day_load_in_day_count",
                 "hall_bound_prof_day",
                 "free_day_choice_3way",
                 "subject_day_count_pair",
                 "subject_day_count_in"):
        assert d2c.PRAGMA_LEVEL.get(name) == "phase_a", name
    # Existing Phase B pragmas tagged
    for name in ("no_holes_class", "class_present_at_hour",
                 "teacher_max_per_day", "subject_pair_must",
                 "class_day_load_in"):
        assert d2c.PRAGMA_LEVEL.get(name) == "phase_b", name


def test_phase_b_pragma_skipped_under_phase_a_level():
    """A compiler with level='phase_a' must skip a phase_b pragma
    (no constraints added) and record a diagnostic."""
    from ortools.sat.python import cp_model
    import dsl_to_cpsat as d2c
    model = cp_model.CpModel()
    compiler = d2c.DSLConstraintCompiler(
        model, slot={}, level="phase_a")
    n_constraints_before = len(model.Proto().constraints)
    compiler.compile('no_holes_class("1A")')
    n_constraints_after = len(model.Proto().constraints)
    assert n_constraints_after == n_constraints_before
    assert any("no_holes_class" in d and "skipped" in d
               for d in compiler.diagnostics), compiler.diagnostics


def test_phase_a_pragma_skipped_under_phase_b_level():
    from ortools.sat.python import cp_model
    import dsl_to_cpsat as d2c
    model = cp_model.CpModel()
    compiler = d2c.DSLConstraintCompiler(
        model, slot={}, level="phase_b")
    compiler.compile('class_day_load_in_day_count("1A", 0, 4)')
    assert any("class_day_load_in_day_count" in d and "skipped" in d
               for d in compiler.diagnostics), compiler.diagnostics


def test_level_default_both_accepts_either_family():
    from ortools.sat.python import cp_model
    import dsl_to_cpsat as d2c
    model = cp_model.CpModel()
    # day_count empty but slot empty too; the compiler should not
    # filter either pragma based on level.
    compiler = d2c.DSLConstraintCompiler(model, slot={})
    compiler.compile('no_holes_class("1A")')
    compiler.compile('class_day_load_in_day_count("1A", 0, 4)')
    # Phase A pragma will diagnostic-warn on empty day_count, but the
    # pragma was NOT skipped by the level filter (different reason).
    skipped_by_level = [
        d for d in compiler.diagnostics
        if "compiler level=" in d
    ]
    assert not skipped_by_level, skipped_by_level


# ============================================================
# Pragma 1: class_day_load_in_day_count
# ============================================================


def test_class_day_load_in_day_count_forbids_disallowed():
    """4 hours total, allowed = {0, 4, 5, 6}: must be a single full
    day (4) or zero, no spread. We unblock the per-cattedra cap by
    raising max_per_day so '4 in one day' is reachable."""
    import dsl_to_cpsat as d2c
    triples = [("T1", "1A", "Mat", 4)]
    model, day_count, days = _build_dc_model(triples, max_per_day=4)
    compiler = d2c.DSLConstraintCompiler(
        model, slot={}, day_count=day_count, level="phase_a")
    compiler.compile('class_day_load_in_day_count("1A", 0, 4, 5, 6)')
    s, status = _solve(model)
    from ortools.sat.python import cp_model
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    # Exactly one day with 4 hrs, all others 0.
    daily = [s.Value(day_count[("T1", "1A", "Mat", d)]) for d in days]
    assert sorted(daily) == [0, 0, 0, 0, 0, 4], daily


def test_class_day_load_in_day_count_blocks_three_hour_day():
    """5 hours, allowed = {0, 4, 5, 6}: spread 3+2 disallowed; 5+0
    must be the only option in one day. Force 3 on day 1 -> infeas."""
    import dsl_to_cpsat as d2c
    triples = [("T1", "1A", "Mat", 5)]
    model, day_count, days = _build_dc_model(
        triples, max_per_day=5)
    # Force day-1 to be exactly 3 -- a value not in {0,4,5,6}.
    model.Add(day_count[("T1", "1A", "Mat", 1)] == 3)
    compiler = d2c.DSLConstraintCompiler(
        model, slot={}, day_count=day_count, level="phase_a")
    compiler.compile('class_day_load_in_day_count("1A", 0, 4, 5, 6)')
    _, status = _solve(model)
    from ortools.sat.python import cp_model
    assert status == cp_model.INFEASIBLE


def test_class_day_load_in_day_count_aggregates_across_subjects():
    """Two cattedras in same class: cl_day_load is the sum across
    subjects. With 2+2 forced on day 1 -> load=4 (allowed), with
    1+1 on day 1 -> load=2 (forbidden)."""
    import dsl_to_cpsat as d2c
    triples = [("T1", "1A", "Mat", 2), ("T2", "1A", "Ita", 2)]
    model, day_count, days = _build_dc_model(triples)
    # Force load=2 on day 1: each cattedra contributes 1.
    model.Add(day_count[("T1", "1A", "Mat", 1)] == 1)
    model.Add(day_count[("T2", "1A", "Ita", 1)] == 1)
    compiler = d2c.DSLConstraintCompiler(
        model, slot={}, day_count=day_count, level="phase_a")
    compiler.compile('class_day_load_in_day_count("1A", 0, 4)')
    _, status = _solve(model)
    from ortools.sat.python import cp_model
    assert status == cp_model.INFEASIBLE


def test_class_day_load_empty_dc_warns():
    """No day_count => diagnostic, no constraints."""
    from ortools.sat.python import cp_model
    import dsl_to_cpsat as d2c
    model = cp_model.CpModel()
    compiler = d2c.DSLConstraintCompiler(
        model, slot={}, day_count={}, level="phase_a")
    compiler.compile('class_day_load_in_day_count("1A", 0, 4)')
    assert any("day_count empty" in d for d in compiler.diagnostics)
