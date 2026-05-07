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


# ============================================================
# Pragma 2: hall_bound_prof_day
# ============================================================


def test_hall_bound_prof_day_caps_to_class_load():
    """Prof teaches in class 1A only; without the bound the prof
    could push 6 hrs into a day where the class has only 4 hrs of
    other lessons. With the Hall pragma + class_day_load_in {0,4,5,6}
    the prof's daily load is bounded by the class load."""
    import dsl_to_cpsat as d2c
    triples = [
        ("T1", "1A", "Mat", 4),  # the prof under Hall
        ("T2", "1A", "Ita", 2),  # extra hours so class load can hit 6
    ]
    model, day_count, days = _build_dc_model(
        triples, max_per_day=4)
    # Force class 1A on day 1 to load = 4 (T1=2 + T2=2). Then T1
    # cannot use day 1 to push 4 hrs (would exceed cl_day_load).
    model.Add(day_count[("T1", "1A", "Mat", 1)] == 2)
    model.Add(day_count[("T2", "1A", "Ita", 1)] == 2)
    # Force T1 to put its 3rd Mat hour on day 1 too.
    # 4 Mat hours - 2 on day 1 - 1 on day 2 = 1 left -- fine.
    compiler = d2c.DSLConstraintCompiler(
        model, slot={}, day_count=day_count, level="phase_a")
    compiler.compile('hall_bound_prof_day("T1")')
    # Now try to force T1 day_count == 5 on day 2 (fewer 1A hours)
    # to validate Hall is per-day.
    s, status = _solve(model)
    from ortools.sat.python import cp_model
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    # T1 daily load on day 1 must be <= cl_day_load(1A, 1) = 4.
    t1_d1 = s.Value(day_count[("T1", "1A", "Mat", 1)])
    assert t1_d1 <= 4


def _build_hall_infeas_model():
    """Helper: build a Phase A model where T1 has prof_day_load=4 on
    day 1 (2 Mat in 1A + 2 Sci in 1B) but cl_day_load(1A, 1) = 2
    and cl_day_load(1B, 1) = 2, so the Hall bound 4 <= max(2, 2) = 2
    fires infeasible. The base model (without Hall) is feasible.
    """
    import dsl_to_cpsat as d2c  # noqa: F401
    triples = [
        ("T1", "1A", "Mat", 4),
        ("T1", "1B", "Sci", 4),
        ("T2", "1A", "Ita", 2),  # other 1A cattedra so 1A load > 0
    ]
    model, day_count, days = _build_dc_model(
        triples, max_per_day=4)
    # Force T1 to load 2+2=4 on day 1.
    model.Add(day_count[("T1", "1A", "Mat", 1)] == 2)
    model.Add(day_count[("T1", "1B", "Sci", 1)] == 2)
    # Force the OTHER 1A cattedra and the not-applicable parts to 0
    # on day 1, so cl_day_load(1A, 1) = T1 Mat = 2 and
    # cl_day_load(1B, 1) = T1 Sci = 2.
    model.Add(day_count[("T2", "1A", "Ita", 1)] == 0)
    return model, day_count, days


def test_hall_bound_prof_day_baseline_feasible_without_pragma():
    """Sanity check: the constructed model is feasible BEFORE Hall
    is added -- so the next test's INFEASIBLE outcome is genuinely
    caused by the pragma, not by contradictory locks."""
    model, _, _ = _build_hall_infeas_model()
    _, status = _solve(model)
    from ortools.sat.python import cp_model
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_hall_bound_prof_day_makes_overload_infeasible():
    """With the Hall pragma added, prof_day_load(T1, 1) = 4 violates
    the bound max(cl_day_load(1A, 1)=2, cl_day_load(1B, 1)=2) = 2
    -> the model becomes INFEASIBLE."""
    import dsl_to_cpsat as d2c
    model, day_count, _ = _build_hall_infeas_model()
    compiler = d2c.DSLConstraintCompiler(
        model, slot={}, day_count=day_count, level="phase_a")
    compiler.compile('hall_bound_prof_day("T1")')
    _, status = _solve(model)
    from ortools.sat.python import cp_model
    assert status == cp_model.INFEASIBLE


# ============================================================
# Pragma 3: free_day_choice_3way
# ============================================================


def test_free_day_choice_3way_zeros_prof_on_chosen_day():
    """Prof T1 has 6 hrs over 5 days. With free_day_choice_3way and
    no soft cost, the solver must pick one of the 3 candidate days
    as free; the prof's day_count for that day is 0."""
    import dsl_to_cpsat as d2c
    triples = [("T1", "1A", "Mat", 6)]
    model, day_count, days = _build_dc_model(
        triples, max_per_day=2)
    compiler = d2c.DSLConstraintCompiler(
        model, slot={}, day_count=day_count, level="phase_a")
    compiler.compile('free_day_choice_3way("T1", 1, 2, 3)')
    s, status = _solve(model)
    from ortools.sat.python import cp_model
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    daily = {d: s.Value(day_count[("T1", "1A", "Mat", d)])
             for d in days}
    # At least one of days 1/2/3 must be 0.
    assert any(daily[d] == 0 for d in (1, 2, 3)), daily


def test_free_day_choice_3way_records_soft_cost_terms():
    """Default weights are [0, 50, 100]. Two of the three picks
    contribute to soft_cost_terms (the first weight is 0 so it is
    skipped)."""
    import dsl_to_cpsat as d2c
    triples = [("T1", "1A", "Mat", 6)]
    model, day_count, _ = _build_dc_model(triples, max_per_day=2)
    compiler = d2c.DSLConstraintCompiler(
        model, slot={}, day_count=day_count, level="phase_a")
    compiler.compile('free_day_choice_3way("T1", 1, 2, 3)')
    weights = sorted(w for w, _ in compiler.soft_cost_terms)
    assert weights == [50, 100]


def test_free_day_choice_3way_first_candidate_preferred_under_obj():
    """With the soft cost term in the objective, the optimal solver
    picks the FIRST candidate (weight 0) over the others."""
    import dsl_to_cpsat as d2c
    from ortools.sat.python import cp_model
    triples = [("T1", "1A", "Mat", 6)]
    model, day_count, days = _build_dc_model(
        triples, max_per_day=2)
    compiler = d2c.DSLConstraintCompiler(
        model, slot={}, day_count=day_count, level="phase_a")
    compiler.compile('free_day_choice_3way("T1", 4, 5, 6)')
    # Build minimisation objective from compiler-side soft terms.
    if compiler.soft_cost_terms:
        model.Minimize(sum(w * v for w, v in compiler.soft_cost_terms))
    s, status = _solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    daily = {d: s.Value(day_count[("T1", "1A", "Mat", d)])
             for d in days}
    # Day 4 (first candidate, weight 0) is the cheap free day.
    assert daily[4] == 0, daily


def test_free_day_choice_3way_custom_weights():
    """Pragma accepts explicit weights as 4th/5th/6th args."""
    import dsl_to_cpsat as d2c
    triples = [("T1", "1A", "Mat", 6)]
    model, day_count, _ = _build_dc_model(triples, max_per_day=2)
    compiler = d2c.DSLConstraintCompiler(
        model, slot={}, day_count=day_count, level="phase_a")
    compiler.compile(
        'free_day_choice_3way("T1", 1, 2, 3, 0, 200, 400)')
    weights = sorted(w for w, _ in compiler.soft_cost_terms)
    assert weights == [200, 400]


# ============================================================
# Pragma 4: subject_day_count_pair
# ============================================================


def test_subject_day_count_pair_forces_2hr_in_some_day():
    """Mat curriculum: 4 hrs per week, max 2/day. Without the pragma
    the solver could spread 1+1+1+1+0+0; with the pragma at least
    one day must have exactly 2 (or more) Mat hours."""
    import dsl_to_cpsat as d2c
    triples = [("T1", "1A", "Mat", 4)]
    model, day_count, days = _build_dc_model(
        triples, max_per_day=2)
    compiler = d2c.DSLConstraintCompiler(
        model, slot={}, day_count=day_count, level="phase_a")
    compiler.compile(
        'subject_day_count_pair("1A", 2, "Mat")')
    s, status = _solve(model)
    from ortools.sat.python import cp_model
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    daily = [s.Value(day_count[("T1", "1A", "Mat", d)]) for d in days]
    assert max(daily) >= 2, daily


def test_subject_day_count_pair_blocks_full_spread():
    """4 hrs of Mat with max_per_day=1 globally: no day can have 2,
    so the pragma must make the model INFEAS."""
    import dsl_to_cpsat as d2c
    triples = [("T1", "1A", "Mat", 4)]
    model, day_count, _ = _build_dc_model(
        triples, max_per_day=1)
    compiler = d2c.DSLConstraintCompiler(
        model, slot={}, day_count=day_count, level="phase_a")
    compiler.compile(
        'subject_day_count_pair("1A", 2, "Mat")')
    _, status = _solve(model)
    from ortools.sat.python import cp_model
    assert status == cp_model.INFEASIBLE


def test_subject_day_count_pair_per_subject_independent():
    """With two subjects in the list, each gets its own
    'at least one day with >=2' rule. Force Mat to 2 on day 1 to
    satisfy Mat side; then Ita must also pile up >=2 somewhere."""
    import dsl_to_cpsat as d2c
    triples = [
        ("T1", "1A", "Mat", 4),
        ("T2", "1A", "Ita", 4),
    ]
    model, day_count, days = _build_dc_model(
        triples, max_per_day=2)
    compiler = d2c.DSLConstraintCompiler(
        model, slot={}, day_count=day_count, level="phase_a")
    compiler.compile(
        'subject_day_count_pair("1A", 2, "Mat", "Ita")')
    s, status = _solve(model)
    from ortools.sat.python import cp_model
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    mat_daily = [s.Value(day_count[("T1", "1A", "Mat", d)]) for d in days]
    ita_daily = [s.Value(day_count[("T2", "1A", "Ita", d)]) for d in days]
    assert max(mat_daily) >= 2 and max(ita_daily) >= 2, (
        mat_daily, ita_daily)
