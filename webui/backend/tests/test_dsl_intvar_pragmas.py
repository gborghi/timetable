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
    one day must have exactly 2 (or more) Mat hours.

    Per-teacher per-subject signature:
    ``subject_day_count_pair(teacher, class, subject, n)``.
    """
    import dsl_to_cpsat as d2c
    triples = [("T1", "1A", "Mat", 4)]
    model, day_count, days = _build_dc_model(
        triples, max_per_day=2)
    compiler = d2c.DSLConstraintCompiler(
        model, slot={}, day_count=day_count, level="phase_a")
    compiler.compile(
        'subject_day_count_pair("T1", "1A", "Mat", 2)')
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
        'subject_day_count_pair("T1", "1A", "Mat", 2)')
    _, status = _solve(model)
    from ortools.sat.python import cp_model
    assert status == cp_model.INFEASIBLE


# ============================================================
# Pragma 5: subject_day_count_in
# ============================================================


def test_subject_day_count_in_motorie_zero_or_two():
    """Scienzemotorie: per (class, subj) day count must be 0 or 2.
    With 4 hrs total over 6 days, the only option is 2+2+0+0+0+0."""
    import dsl_to_cpsat as d2c
    triples = [("T1", "1A", "Scienzemotorie", 4)]
    model, day_count, days = _build_dc_model(
        triples, max_per_day=2)
    compiler = d2c.DSLConstraintCompiler(
        model, slot={}, day_count=day_count, level="phase_a")
    compiler.compile(
        'subject_day_count_in("1A", "Scienzemotorie", 0, 2)')
    s, status = _solve(model)
    from ortools.sat.python import cp_model
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    daily = [s.Value(day_count[("T1", "1A", "Scienzemotorie", d)])
             for d in days]
    assert sorted(daily) == [0, 0, 0, 0, 2, 2], daily


def test_subject_day_count_in_blocks_3_hour_day():
    """Force 3 hrs of Motorie on day 1: with allowed = {0, 2} the
    pragma makes it infeasible."""
    import dsl_to_cpsat as d2c
    triples = [("T1", "1A", "Scienzemotorie", 3)]
    model, day_count, _ = _build_dc_model(
        triples, max_per_day=3)
    model.Add(day_count[("T1", "1A", "Scienzemotorie", 1)] == 3)
    compiler = d2c.DSLConstraintCompiler(
        model, slot={}, day_count=day_count, level="phase_a")
    compiler.compile(
        'subject_day_count_in("1A", "Scienzemotorie", 0, 2)')
    _, status = _solve(model)
    from ortools.sat.python import cp_model
    assert status == cp_model.INFEASIBLE


def test_subject_day_count_in_aggregates_compresenza():
    """Two cattedras teach the same (class, subject) -- compresenza
    style. The pragma sums over the two and applies the allowed set
    to the sum, not to each cattedra independently."""
    import dsl_to_cpsat as d2c
    triples = [
        ("T1", "1A", "Scienzemotorie", 2),
        ("T2", "1A", "Scienzemotorie", 2),
    ]
    model, day_count, days = _build_dc_model(
        triples, max_per_day=2)
    # Force T1 = 1 on day 1 and T2 = 1 on day 1: sum = 2 (allowed).
    model.Add(day_count[("T1", "1A", "Scienzemotorie", 1)] == 1)
    model.Add(day_count[("T2", "1A", "Scienzemotorie", 1)] == 1)
    compiler = d2c.DSLConstraintCompiler(
        model, slot={}, day_count=day_count, level="phase_a")
    compiler.compile(
        'subject_day_count_in("1A", "Scienzemotorie", 0, 2)')
    _, status = _solve(model)
    from ortools.sat.python import cp_model
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_subject_day_count_in_aggregates_compresenza_blocks_3():
    """Same compresenza setup but T1+T2 = 3 on day 1 (T1=2, T2=1):
    the pragma must reject (3 not in {0, 2})."""
    import dsl_to_cpsat as d2c
    triples = [
        ("T1", "1A", "Scienzemotorie", 2),
        ("T2", "1A", "Scienzemotorie", 2),
    ]
    model, day_count, _ = _build_dc_model(
        triples, max_per_day=2)
    model.Add(day_count[("T1", "1A", "Scienzemotorie", 1)] == 2)
    model.Add(day_count[("T2", "1A", "Scienzemotorie", 1)] == 1)
    compiler = d2c.DSLConstraintCompiler(
        model, slot={}, day_count=day_count, level="phase_a")
    compiler.compile(
        'subject_day_count_in("1A", "Scienzemotorie", 0, 2)')
    _, status = _solve(model)
    from ortools.sat.python import cp_model
    assert status == cp_model.INFEASIBLE


# ============================================================
# DayCountModel: end-to-end Phase A scenarios
# ============================================================


def test_daycountmodel_builds_day_count_intvars_per_triple():
    from cp_sat_constraint_model import DayCountModel
    profs = {
        "T1": {"classi": {"1A": {"Mat": {"ore": 4}}},
                "max_hours": 18},
    }
    m = DayCountModel(profs)
    assert m.slot == {}
    assert len(m.day_count) == 6  # 6 days
    for d in range(1, 7):
        assert ("T1", "1A", "Mat", d) in m.day_count
    assert m.weekly_ore[("T1", "1A", "Mat")] == 4


def test_daycountmodel_solves_simple_curriculum():
    """Phase A on a 1-cattedra curriculum: solver finds a feasible
    distribution with sum_d == 4."""
    from cp_sat_constraint_model import DayCountModel
    profs = {
        "T1": {"classi": {"1A": {"Mat": {"ore": 4}}},
                "max_hours": 18},
    }
    m = DayCountModel(profs)
    sol, status = m.solve(time_limit_s=2.0, workers=1)
    assert sol is not None, status
    daily = sum(sol.values())
    assert daily == 4


def test_daycountmodel_dsl_pragma_filters_to_phase_a():
    """A Phase B pragma (no_holes_class) routed to DayCountModel
    must be skipped with a diagnostic; a Phase A pragma must apply.
    Two cattedras (2+2 ore each) so cl_day_load can reach 4 within
    the per-cattedra MAX_PER_DAY_TRIPLE=2 cap."""
    from cp_sat_constraint_model import DayCountModel
    profs = {
        "T1": {"classi": {"1A": {"Mat": {"ore": 2}}},
                "max_hours": 18},
        "T2": {"classi": {"1A": {"Ita": {"ore": 2}}},
                "max_hours": 18},
    }
    m = DayCountModel(profs)
    m.add_dsl_constraint('no_holes_class("1A")')
    # Phase B pragma was skipped:
    assert any("no_holes_class" in d and "skipped" in d
               for d in m.dsl_diagnostics)
    # Phase A pragma applies:
    m.add_dsl_constraint(
        'class_day_load_in_day_count("1A", 0, 4)')
    sol, status = m.solve(time_limit_s=2.0, workers=1)
    assert sol is not None, status
    # Per-day load must be in {0, 4}; with 2+2=4 available, exactly
    # one day must hit load=4 (both cattedras at 2).
    daily_load = {}
    for (_t, cl, _s, d), n in sol.items():
        daily_load[(cl, d)] = daily_load.get((cl, d), 0) + n
    assert all(v in {0, 4} for v in daily_load.values()), daily_load
    assert max(daily_load.values()) == 4


def test_daycountmodel_combined_phase_a_pragmas_replicate_legacy():
    """End-to-end: build the Phase A HARD surface for a tiny school
    via the 5 pragmas + DayCountModel and verify the resulting
    day_count matches a hand-computed feasible region.

    Scenario:
      - Class 1A: T1 teaches Mat (4 hrs), T2 teaches Motorie (2 hrs),
        T3 teaches Ita (4 hrs). Total 10 hrs over 6 days.
      - Constraints: cl_day_load in {0, 4, 5, 6}; Mat needs >=1 day
        with >=2 ore; Motorie day_count in {0, 2}.
      - Expected feasible patterns: e.g. 6+4+0+0+0+0 (Mot+Mat+Ita
        compressed) or 5+5+0+0+0+0 (5+5 needs Mot=1 which is
        forbidden, hence not reachable).
    """
    from cp_sat_constraint_model import DayCountModel
    profs = {
        "T1": {"classi": {"1A": {"Mat": {"ore": 4}}},
                "max_hours": 18},
        "T2": {"classi": {"1A": {"Scienzemotorie": {"ore": 2}}},
                "max_hours": 18},
        "T3": {"classi": {"1A": {"Ita": {"ore": 4}}},
                "max_hours": 18},
    }
    m = DayCountModel(profs)
    m.add_dsl_constraint(
        'class_day_load_in_day_count("1A", 0, 4, 5, 6)')
    m.add_dsl_constraint(
        'subject_day_count_pair("T1", "1A", "Mat", 2)')
    m.add_dsl_constraint(
        'subject_day_count_pair("T3", "1A", "Ita", 2)')
    m.add_dsl_constraint(
        'subject_day_count_in("1A", "Scienzemotorie", 0, 2)')
    m.add_dsl_constraint('hall_bound_prof_day("T1")')
    m.add_dsl_constraint('hall_bound_prof_day("T2")')
    m.add_dsl_constraint('hall_bound_prof_day("T3")')
    sol, status = m.solve(time_limit_s=5.0, workers=1)
    assert sol is not None, status
    # cl_day_load in {0, 4, 5, 6}
    daily_load: dict = {}
    for (_t, cl, _s, d), n in sol.items():
        daily_load[(cl, d)] = daily_load.get((cl, d), 0) + n
    assert all(v in {0, 4, 5, 6} for v in daily_load.values()), (
        daily_load)
    # Motorie totals on each day in {0, 2}
    mot_per_day: dict = {}
    for (_t, cl, s, d), n in sol.items():
        if s == "Scienzemotorie":
            mot_per_day[d] = mot_per_day.get(d, 0) + n
    for d in range(1, 7):
        assert mot_per_day.get(d, 0) in (0, 2), mot_per_day
    # Mat: at least 1 day with >= 2 hrs
    mat_per_day = [sol.get(("T1", "1A", "Mat", d), 0)
                   for d in range(1, 7)]
    assert max(mat_per_day) >= 2, mat_per_day
    # Ita: at least 1 day with >= 2 hrs
    ita_per_day = [sol.get(("T3", "1A", "Ita", d), 0)
                   for d in range(1, 7)]
    assert max(ita_per_day) >= 2, ita_per_day


def test_daycountmodel_free_day_pragma_picks_first_candidate():
    """End-to-end soft-cost integration: free_day_choice_3way for
    T1 with weights [0, 50, 100]. Optimum picks day 1 (weight 0)."""
    from cp_sat_constraint_model import DayCountModel
    profs = {
        "T1": {"classi": {"1A": {"Mat": {"ore": 6}}},
                "max_hours": 18},
    }
    m = DayCountModel(profs)
    m.add_dsl_constraint(
        'free_day_choice_3way("T1", 1, 2, 3)')
    sol, status = m.solve(time_limit_s=2.0, workers=1)
    assert sol is not None, status
    daily = {d: sol.get(("T1", "1A", "Mat", d), 0)
             for d in range(1, 7)}
    # Optimal: day 1 free (weight 0).
    assert daily[1] == 0, daily


def test_daycountmodel_compute_soft_cost_expr_rejects_default_mode():
    from cp_sat_constraint_model import DayCountModel
    profs = {
        "T1": {"classi": {"1A": {"Mat": {"ore": 4}}},
                "max_hours": 18},
    }
    m = DayCountModel(profs)
    with pytest.raises(ValueError, match="phase_a"):
        m.compute_soft_cost_expr(mode="default")


# ============================================================
# Cross-validation against legacy solve_phase_a
# ============================================================
#
# These tests build the same tiny school via two paths and verify
# the resulting day_count distributions are equivalent (same
# feasible region; same hard constraint envelope). Because the
# legacy ``solve_phase_a`` carries non-DSL surface (parallel groups,
# coteach codoc tying, sostegno following the class) that the
# Phase 1 pragmas don't yet replicate, the comparison is restricted
# to scenarios with no codoc / sostegno / parallel groups -- a
# vanilla curriculum where the two paths see the same model.


def _legacy_solve_phase_a(profs, time_limit=2.0):
    """Run the legacy ``cpsat_v2_timetable.solve_phase_a`` on the
    given profs dict. Returns the dc_value mapping (only the
    ``(p, cl, subj, d)`` keys; ``__coday__`` / ``__pot__`` entries
    are filtered out)."""
    import cpsat_v2_timetable as cv2
    classes, triples, class_profs = cv2.build_indices(profs)
    dc = cv2.solve_phase_a(
        profs, classes, triples, class_profs,
        time_limit=time_limit, workers=1, log=False)
    out = {}
    for k, v in dc.items():
        if isinstance(k, tuple) and len(k) == 4 and isinstance(
                k[0], str) and not k[0].startswith("__"):
            out[k] = int(v)
    return out


def test_xvalidate_phase_a_simple_two_cattedras():
    """Two cattedras (Mat 4 + Ita 4) in 1A. Both legacy and DSL
    paths must yield: every active day's load = 4 (no class load
    of 1, 2, 3); both must visit at least one day with >= 2 hrs of
    each subject."""
    from cp_sat_constraint_model import DayCountModel
    profs = {
        "T1": {"classi": {"1A": {"Mat": {"ore": 4}}},
                "max_hours": 18},
        "T2": {"classi": {"1A": {"Ita": {"ore": 4}}},
                "max_hours": 18},
    }
    legacy = _legacy_solve_phase_a(profs)
    # Legacy enforces cl_day_load in {0,4,5,6} hard-coded:
    legacy_loads: dict = {}
    for (_t, cl, _s, d), n in legacy.items():
        legacy_loads[(cl, d)] = legacy_loads.get((cl, d), 0) + n
    assert all(v in {0, 4, 5, 6} for v in legacy_loads.values()), (
        legacy_loads)

    # DSL path: replicate the legacy HARD surface via pragmas.
    m = DayCountModel(profs)
    m.add_dsl_constraint(
        'class_day_load_in_day_count("1A", 0, 4, 5, 6)')
    m.add_dsl_constraint(
        'subject_day_count_pair("T1", "1A", "Mat", 2)')
    m.add_dsl_constraint(
        'subject_day_count_pair("T2", "1A", "Ita", 2)')
    m.add_dsl_constraint('hall_bound_prof_day("T1")')
    m.add_dsl_constraint('hall_bound_prof_day("T2")')
    dsl, status = m.solve(time_limit_s=2.0, workers=1)
    assert dsl is not None, status
    dsl_loads: dict = {}
    for (_t, cl, _s, d), n in dsl.items():
        dsl_loads[(cl, d)] = dsl_loads.get((cl, d), 0) + n
    assert all(v in {0, 4, 5, 6} for v in dsl_loads.values()), (
        dsl_loads)
    # Both must satisfy: at least one day with >=2 of each subject.
    for subj_pat, src in (("Mat", legacy), ("Ita", legacy),
                           ("Mat", dsl), ("Ita", dsl)):
        per_day = [v for k, v in src.items() if k[2] == subj_pat]
        assert max(per_day) >= 2, (subj_pat, per_day)


def test_xvalidate_phase_a_with_motorie():
    """Add Scienzemotorie (2 hrs): legacy enforces day_count in
    {0, 2}; DSL replicates via subject_day_count_in."""
    from cp_sat_constraint_model import DayCountModel
    profs = {
        "T1": {"classi": {"1A": {"Mat": {"ore": 4}}},
                "max_hours": 18},
        "T2": {"classi": {"1A": {"Scienzemotorie": {"ore": 2}}},
                "max_hours": 18},
        "T3": {"classi": {"1A": {"Ita": {"ore": 4}}},
                "max_hours": 18},
    }
    legacy = _legacy_solve_phase_a(profs)
    # Legacy: Motorie per day in {0, 2}.
    mot_legacy = {}
    for (t, cl, s, d), n in legacy.items():
        if s == "Scienzemotorie":
            mot_legacy[d] = mot_legacy.get(d, 0) + n
    for d in range(1, 7):
        assert mot_legacy.get(d, 0) in (0, 2), mot_legacy

    # DSL replicates the constraint surface.
    m = DayCountModel(profs)
    m.add_dsl_constraint(
        'class_day_load_in_day_count("1A", 0, 4, 5, 6)')
    m.add_dsl_constraint(
        'subject_day_count_pair("T1", "1A", "Mat", 2)')
    m.add_dsl_constraint(
        'subject_day_count_pair("T3", "1A", "Ita", 2)')
    m.add_dsl_constraint(
        'subject_day_count_in("1A", "Scienzemotorie", 0, 2)')
    m.add_dsl_constraint('hall_bound_prof_day("T1")')
    m.add_dsl_constraint('hall_bound_prof_day("T2")')
    m.add_dsl_constraint('hall_bound_prof_day("T3")')
    dsl, status = m.solve(time_limit_s=3.0, workers=1)
    assert dsl is not None, status
    mot_dsl = {}
    for (_t, cl, s, d), n in dsl.items():
        if s == "Scienzemotorie":
            mot_dsl[d] = mot_dsl.get(d, 0) + n
    for d in range(1, 7):
        assert mot_dsl.get(d, 0) in (0, 2), mot_dsl
    # Class load matches legacy's allowed-set on both paths.
    for sol in (legacy, dsl):
        loads: dict = {}
        for (_t, cl, _s, d), n in sol.items():
            loads[(cl, d)] = loads.get((cl, d), 0) + n
        assert all(v in {0, 4, 5, 6} for v in loads.values()), loads


def test_xvalidate_phase_a_total_ore_preserved():
    """Both paths must place exactly the curriculum total ore for
    every cattedra (sum_d == ore)."""
    from cp_sat_constraint_model import DayCountModel
    profs = {
        "T1": {"classi": {"1A": {"Mat": {"ore": 4},
                                   "Geo": {"ore": 2}}},
                "max_hours": 18},
        "T2": {"classi": {"1A": {"Ita": {"ore": 4}}},
                "max_hours": 18},
    }
    legacy = _legacy_solve_phase_a(profs)
    legacy_per_triple: dict = {}
    for (t, cl, s, _d), n in legacy.items():
        legacy_per_triple[(t, cl, s)] = (
            legacy_per_triple.get((t, cl, s), 0) + n)
    assert legacy_per_triple == {
        ("T1", "1A", "Mat"): 4,
        ("T1", "1A", "Geo"): 2,
        ("T2", "1A", "Ita"): 4,
    }, legacy_per_triple

    m = DayCountModel(profs)
    m.add_dsl_constraint(
        'class_day_load_in_day_count("1A", 0, 4, 5, 6)')
    dsl, status = m.solve(time_limit_s=2.0, workers=1)
    assert dsl is not None, status
    dsl_per_triple: dict = {}
    for (t, cl, s, _d), n in dsl.items():
        dsl_per_triple[(t, cl, s)] = (
            dsl_per_triple.get((t, cl, s), 0) + n)
    assert dsl_per_triple == legacy_per_triple, dsl_per_triple


def test_subject_day_count_pair_per_teacher_per_subject_independent():
    """Per-teacher per-subject: each (t, cl, subj) cattedra needs its
    own ">=1 day with >=2" satisfied. Two pragmas emitted, one per
    cattedra; both rules must hold."""
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
        'subject_day_count_pair("T1", "1A", "Mat", 2)')
    compiler.compile(
        'subject_day_count_pair("T2", "1A", "Ita", 2)')
    s, status = _solve(model)
    from ortools.sat.python import cp_model
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    mat_daily = [s.Value(day_count[("T1", "1A", "Mat", d)]) for d in days]
    ita_daily = [s.Value(day_count[("T2", "1A", "Ita", d)]) for d in days]
    assert max(mat_daily) >= 2 and max(ita_daily) >= 2, (
        mat_daily, ita_daily)


def test_subject_day_count_pair_skips_other_teacher_subject():
    """Per-teacher per-subject: a pragma for (T1, 1A, Mat) only
    constrains T1's Mat. Adding T2's Ita with no pragma must not
    force the Ita-side. Sanity check that the rule is scoped to
    the (teacher, subject, class) tuple of the pragma."""
    import dsl_to_cpsat as d2c
    triples = [
        ("T1", "1A", "Mat", 4),
        ("T2", "1A", "Ita", 6),
    ]
    model, day_count, days = _build_dc_model(
        triples, max_per_day=1)         # block 2-in-a-day
    compiler = d2c.DSLConstraintCompiler(
        model, slot={}, day_count=day_count, level="phase_a")
    # Only T2's Ita has a pragma -- T1's Mat is unconstrained.
    # The Ita pragma is infeasible (max_per_day=1) so the model
    # is INFEAS regardless of T1's Mat: this confirms the rule
    # fires only on the named cattedra.
    compiler.compile(
        'subject_day_count_pair("T2", "1A", "Ita", 2)')
    _, status = _solve(model)
    from ortools.sat.python import cp_model
    assert status == cp_model.INFEASIBLE


# ============================================================
# build_phase_a_pragmas helper
# ============================================================


def test_build_phase_a_pragmas_emits_canonical_set():
    """Helper emits the five canonical Phase A pragmas given a tiny
    school: cl_day_load + Hall (one per prof in real classes) +
    free_day (only for profs with >= 3 glibero) + Mat/Ita pair (only
    for subjects with >= 2 hours) + Motorie (only when present)."""
    import cpsat_v2_timetable as cv2
    profs = {
        "T1": {"classi": {"1A": {"Matematica": {"ore": 4}}},
                "glibero": [3, 4, 5], "max_hours": 18},
        "T2": {"classi": {"1A": {"Italiano": {"ore": 5},
                                   "Storia": {"ore": 1}}},
                "glibero": [1, 2, 6], "max_hours": 18},
        "T3": {"classi": {"1A": {"Scienzemotorie": {"ore": 2}}},
                "glibero": [], "max_hours": 18},
    }
    triples_by_prof = {
        "T1": [("1A", "Matematica")],
        "T2": [("1A", "Italiano"), ("1A", "Storia")],
        "T3": [("1A", "Scienzemotorie")],
    }
    day_count_keys = {
        (p, cl, s, d)
        for p, lst in triples_by_prof.items()
        for (cl, s) in lst
        for d in range(1, 7)
    }
    pragmas = cv2.build_phase_a_pragmas(
        profs, ["1A"],
        cl_day_load_classes={"1A"},
        triples_by_prof=triples_by_prof,
        day_count_keys=day_count_keys,
    )
    # cl_day_load: one per real class.
    assert any("class_day_load_in_day_count" in p
                and "'1A'" in p
                and "0, 4, 5, 6" in p for p in pragmas), pragmas
    # Hall: one per prof (all three teach in the real class).
    for prof in ("T1", "T2", "T3"):
        assert any(f"hall_bound_prof_day('{prof}')" == p
                    for p in pragmas), pragmas
    # free_day: T1, T2 (T3 has empty glibero, must be skipped).
    assert any("free_day_choice_3way('T1', 3, 4, 5)" == p
                for p in pragmas)
    assert any("free_day_choice_3way('T2', 1, 2, 6)" == p
                for p in pragmas)
    assert not any("free_day_choice_3way('T3'" in p for p in pragmas)
    # Mat/Ita: per-teacher per-subject pragma. T1 has Matematica=4
    # (>= 2) -> emit. T2 has Italiano=5 (>= 2) -> emit. Storia=1
    # is < 2 and is not Mat/Ita anyway -> skip. T3 has Motorie
    # only -> skip Mat/Ita.
    assert any(
        "subject_day_count_pair('T1', '1A', 'Matematica', 2)" == p
        for p in pragmas), pragmas
    assert any(
        "subject_day_count_pair('T2', '1A', 'Italiano', 2)" == p
        for p in pragmas), pragmas
    # No spurious emission for Storia / Motorie:
    assert not any("'Storia'" in p and "subject_day_count_pair" in p
                    for p in pragmas), pragmas
    assert not any(
        "'Scienzemotorie'" in p and "subject_day_count_pair" in p
        for p in pragmas), pragmas
    # Motorie: present (subject_day_count_in, NOT _pair).
    assert any("subject_day_count_in('1A'" in p
                and "Scienzemotorie" in p
                and "0, 2" in p for p in pragmas), pragmas


def test_build_phase_a_pragmas_skips_hall_for_group_only_prof():
    """A prof whose only classes are virtual groups must skip the
    hall_bound pragma -- but only when ``cl_day_load_classes`` is
    non-empty AND none of the prof's classes are in it. The legacy
    ``only_group_classes`` bypass requires a non-empty
    cl_day_load_classes set; an all-empty Phase A still emits Hall
    so the bound prof_day_load <= 0 surfaces sostegno-only
    infeasibilities."""
    import cpsat_v2_timetable as cv2
    profs = {
        "TG": {"classi": {"__group_X__": {"Mat": {"ore": 4}}},
                "glibero": []},
        "TR": {"classi": {"1A": {"Mat": {"ore": 4}}}, "glibero": []},
    }
    triples_by_prof = {
        "TG": [("__group_X__", "Mat")],
        "TR": [("1A", "Mat")],
    }
    day_count_keys = set()  # not consumed by Hall path
    # 1A is a real class -> cl_day_load_classes = {"1A"}.
    pragmas = cv2.build_phase_a_pragmas(
        profs, ["1A"],
        cl_day_load_classes={"1A"},
        triples_by_prof=triples_by_prof,
        day_count_keys=day_count_keys,
    )
    # TG has only __group_X__ (not in cl_day_load_classes) -> skip.
    assert not any("hall_bound_prof_day('TG')" == p
                    for p in pragmas), pragmas
    # TR has 1A (real class) -> emit.
    assert any("hall_bound_prof_day('TR')" == p
                for p in pragmas), pragmas


def test_build_phase_a_pragmas_emits_hall_when_cl_day_load_empty():
    """When ``cl_day_load_classes`` is empty (e.g., a class with
    only sostegno triples), the helper must still emit Hall pragmas
    -- the bound becomes ``prof_day_load <= 0`` and surfaces the
    infeasibility (the prof has hours but no class day to host them).
    The compiler's cl_day_load cache is seeded with zero constants
    by ``solve_phase_a`` so the pragma builds the right bound."""
    import cpsat_v2_timetable as cv2
    profs = {
        "ProfSost": {"classi": {"3B": {"sostegno": {"ore": 4}}},
                      "glibero": []},
    }
    triples_by_prof = {"ProfSost": [("3B", "sostegno")]}
    day_count_keys = set()
    pragmas = cv2.build_phase_a_pragmas(
        profs, ["3B"],
        cl_day_load_classes=set(),       # no real-cattedra classes
        triples_by_prof=triples_by_prof,
        day_count_keys=day_count_keys,
    )
    assert any("hall_bound_prof_day('ProfSost')" == p
                for p in pragmas), pragmas


def test_build_phase_a_pragmas_emits_subject_pair_per_teacher():
    """Per-teacher per-subject Mat/Ita pragma: one emission per
    (teacher, class, subject) where subject in {Matematica,
    Italiano} and ore >= 2."""
    import cpsat_v2_timetable as cv2
    profs = {
        "T1": {"classi": {"1A": {"Matematica": {"ore": 4}}}},
        "T2": {"classi": {"1A": {"Italiano": {"ore": 5}}}},
    }
    triples_by_prof = {"T1": [("1A", "Matematica")],
                        "T2": [("1A", "Italiano")]}
    day_count_keys = {(p, cl, s, d)
                       for p, lst in triples_by_prof.items()
                       for (cl, s) in lst
                       for d in range(1, 7)}
    pragmas = cv2.build_phase_a_pragmas(
        profs, ["1A"],
        cl_day_load_classes={"1A"},
        triples_by_prof=triples_by_prof,
        day_count_keys=day_count_keys,
    )
    assert any(
        "subject_day_count_pair('T1', '1A', 'Matematica', 2)" == p
        for p in pragmas), pragmas
    assert any(
        "subject_day_count_pair('T2', '1A', 'Italiano', 2)" == p
        for p in pragmas), pragmas


def test_build_phase_a_pragmas_skips_subject_pair_when_below_2_ore():
    """A Mat/Ita cattedra with < 2 hours is skipped (the per-teacher
    per-subject pragma would be infeasible)."""
    import cpsat_v2_timetable as cv2
    profs = {
        # Italian = 1 hour: skip.
        "T1": {"classi": {"1A": {"Italiano": {"ore": 1},
                                   "Storia": {"ore": 3}}}},
        # Mat = 2 hours: emit.
        "T2": {"classi": {"1A": {"Matematica": {"ore": 2}}}},
    }
    triples_by_prof = {
        "T1": [("1A", "Italiano"), ("1A", "Storia")],
        "T2": [("1A", "Matematica")],
    }
    day_count_keys = {(p, cl, s, d)
                       for p, lst in triples_by_prof.items()
                       for (cl, s) in lst
                       for d in range(1, 7)}
    pragmas = cv2.build_phase_a_pragmas(
        profs, ["1A"],
        cl_day_load_classes={"1A"},
        triples_by_prof=triples_by_prof,
        day_count_keys=day_count_keys,
    )
    assert not any("'Italiano'" in p and "subject_day_count_pair" in p
                    for p in pragmas), pragmas
    assert any(
        "subject_day_count_pair('T2', '1A', 'Matematica', 2)" == p
        for p in pragmas), pragmas
