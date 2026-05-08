"""HARD-OR floor + SOFT priority free-day pragma tests.

Pins the new free-day semantics:

* HARD floor: ``teacher_at_least_n_free_days(name, n)`` -- every
  teacher must have at least ``n`` weekdays with zero lessons.
  With ``n=1`` (the universal CCNL default) the rule reads
  "almeno un giorno libero a settimana".

* SOFT priority: ``teacher_preferred_free_day_penalty(name, day, w)``
  contributes ``w * busy[name, day]`` to the soft objective. Used
  with three priority weights (30, 20, 10 for priority 1/2/3) so
  the solver tends to honor the highest-priority pick first.

Both pragmas are level=both in PRAGMA_LEVEL so they apply in
Phase A (day_count IntVars), Phase B (slot Bools), and the
monolithic / cpsat_week / cpsat_day_skip_phase_a /
cpsat_day_soft_hint contexts uniformly. The previous Phase-A-only
``free_day_choice_3way`` pragma was bypassed by those techniques and
produced ``hard_violation`` rows on the v2 SQLite bench; the four
tests below pin the post-fix behaviour.
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
ENGINE = os.path.join(ROOT, "engine")
WEBUI = os.path.join(ROOT, "webui")
for p in (ENGINE, WEBUI, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)


cp_model = pytest.importorskip("ortools.sat.python.cp_model")
d2c = pytest.importorskip("dsl_to_cpsat")


# ----- helpers (mirror the Phase-A skeleton used by the IntVar pragma
# tests in webui/backend/tests/test_dsl_intvar_pragmas.py) -----------


def _build_dc_model(triples, *, max_per_day=2, days=range(1, 7)):
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
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = time_limit
    s.parameters.num_search_workers = 1
    status = s.Solve(model)
    return s, status


def _busy_days(solver, day_count, prof, days):
    """Return the set of days where the prof has at least one
    lesson according to the solver's solution."""
    return {d for d in days
            if any(solver.Value(day_count[(p, c, s, d)]) > 0
                   for (p, c, s, dd) in day_count
                   if p == prof and dd == d)}


# ============================================================
# Test 1 -- HARD floor: 5 hours over a week with at_least_1
#          free day forces the prof onto at most 4 days.
# ============================================================


def test_at_least_one_free_day_caps_busy_days_at_five():
    """Prof T1 has 5 hours total. With
    ``teacher_at_least_n_free_days('T1', 1)`` the solver must leave
    at least one weekday with zero lessons."""
    triples = [("T1", "1A", "Mat", 5)]
    model, day_count, days = _build_dc_model(
        triples, max_per_day=2)
    compiler = d2c.DSLConstraintCompiler(
        model, slot={}, day_count=day_count, level="both")
    compiler.compile('teacher_at_least_n_free_days("T1", 1)')
    solver, status = _solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    busy = _busy_days(solver, day_count, "T1", days)
    assert len(busy) <= len(days) - 1, (
        f"prof busy on {len(busy)}/{len(days)} days; expected <= "
        f"{len(days) - 1}")


def test_at_least_two_free_days_caps_busy_days_at_four():
    """Higher floor: ``n=2`` forces two free days on a 5-hour week."""
    triples = [("T1", "1A", "Mat", 5)]
    model, day_count, days = _build_dc_model(
        triples, max_per_day=2)
    compiler = d2c.DSLConstraintCompiler(
        model, slot={}, day_count=day_count, level="both")
    compiler.compile('teacher_at_least_n_free_days("T1", 2)')
    solver, status = _solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    busy = _busy_days(solver, day_count, "T1", days)
    assert len(busy) <= len(days) - 2, busy


def test_at_least_n_free_days_infeasible_when_n_exceeds_capacity():
    """``n=6`` on a 6-day week + non-zero hours is infeasible."""
    triples = [("T1", "1A", "Mat", 4)]
    model, day_count, _ = _build_dc_model(triples, max_per_day=2)
    compiler = d2c.DSLConstraintCompiler(
        model, slot={}, day_count=day_count, level="both")
    compiler.compile('teacher_at_least_n_free_days("T1", 6)')
    _, status = _solve(model)
    assert status == cp_model.INFEASIBLE


# ============================================================
# Test 2 -- SOFT priority preferences. With Mon=30, Tue=20, Wed=10
#          and only 2 hours to place across 6 days, the optimal
#          solution leaves Monday free (highest weight to pay).
# ============================================================


def test_priority_weights_drive_solver_to_pick_highest_weight():
    """SOFT priorities 30/20/10 on Mon/Tue/Wed: the solver under
    minimisation leaves Monday (the most expensive to violate)
    free."""
    triples = [("T1", "1A", "Mat", 2)]
    model, day_count, _ = _build_dc_model(
        triples, max_per_day=2)
    compiler = d2c.DSLConstraintCompiler(
        model, slot={}, day_count=day_count, level="both")
    compiler.compile(
        'teacher_preferred_free_day_penalty("T1", 1, 30)')
    compiler.compile(
        'teacher_preferred_free_day_penalty("T1", 2, 20)')
    compiler.compile(
        'teacher_preferred_free_day_penalty("T1", 3, 10)')
    if compiler.soft_cost_terms:
        model.Minimize(sum(w * v for w, v in compiler.soft_cost_terms))
    solver, status = _solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    daily = {d: solver.Value(day_count[("T1", "1A", "Mat", d)])
             for d in range(1, 7)}
    assert daily[1] == 0, (
        f"expected Monday (priority 1, weight 30) free; got {daily}")


def test_priority_pragma_records_one_soft_term_per_call():
    """Each ``teacher_preferred_free_day_penalty`` call appends one
    (weight, busy_indicator) tuple to soft_cost_terms."""
    triples = [("T1", "1A", "Mat", 2)]
    model, day_count, _ = _build_dc_model(
        triples, max_per_day=2)
    compiler = d2c.DSLConstraintCompiler(
        model, slot={}, day_count=day_count, level="both")
    compiler.compile(
        'teacher_preferred_free_day_penalty("T1", 1, 30)')
    compiler.compile(
        'teacher_preferred_free_day_penalty("T1", 2, 20)')
    compiler.compile(
        'teacher_preferred_free_day_penalty("T1", 3, 10)')
    weights = sorted(int(w) for w, _ in compiler.soft_cost_terms)
    assert weights == [10, 20, 30]


# ============================================================
# Test 3 -- HARD floor + SOFT priority composed: 5 hours + n=1 +
#          three priorities. The free day must coincide with the
#          highest-weight (priority 1) preference.
# ============================================================


def test_hard_floor_plus_soft_priority_picks_priority_one():
    """The HARD floor forces at least one free day; the SOFT
    priorities steer that free day to Monday (highest weight)."""
    triples = [("T1", "1A", "Mat", 5)]
    model, day_count, days = _build_dc_model(
        triples, max_per_day=2)
    compiler = d2c.DSLConstraintCompiler(
        model, slot={}, day_count=day_count, level="both")
    compiler.compile('teacher_at_least_n_free_days("T1", 1)')
    compiler.compile(
        'teacher_preferred_free_day_penalty("T1", 1, 30)')
    compiler.compile(
        'teacher_preferred_free_day_penalty("T1", 2, 20)')
    compiler.compile(
        'teacher_preferred_free_day_penalty("T1", 3, 10)')
    if compiler.soft_cost_terms:
        model.Minimize(sum(w * v for w, v in compiler.soft_cost_terms))
    solver, status = _solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    busy = _busy_days(solver, day_count, "T1", days)
    assert 1 not in busy, (
        f"priority-1 day Monday should be free; busy={busy}")
    assert len(busy) <= len(days) - 1, busy


# ============================================================
# Test 4 -- Bench-bypass regression: the new pragmas are emitted by
#          the DSL translator so they apply across Phase A / Phase B
#          / cpsat_week / cpsat_day_skip_phase_a / cpsat_day_soft_hint
#          uniformly. Pinning the contract: the small SQLite profile
#          DB produces a load_all_dsl_constraints output that
#          includes the new HARD floor pragma for every teacher and
#          three SOFT priority pragmas per teacher.
# ============================================================


def test_small_profile_emits_at_least_one_free_day_per_teacher():
    """Loading the regenerated small.sqlite profile through the
    DSL translator yields one
    ``teacher_at_least_n_free_days(name, 1)`` HARD rule per teacher
    and three ``teacher_preferred_free_day_penalty(name, day, w)``
    SOFT rules per teacher (priorities 30/20/10)."""
    sqlite_path = os.path.join(
        ROOT, "engine", "scripts", "data", "small", "small.sqlite")
    if not os.path.isfile(sqlite_path):
        pytest.skip("small.sqlite profile not built")

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from backend import db as backend_db  # noqa: F401
    from backend import models  # noqa: F401  -- registers tables
    from engine.dsl_translator import load_all_dsl_constraints

    engine = create_engine(
        f"sqlite:///{sqlite_path}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    Session = sessionmaker(bind=engine, future=True)
    sess = Session()
    try:
        rules = load_all_dsl_constraints(sess, include_soft=True)
        n_teachers = sess.query(models.Teacher).count()
    finally:
        sess.close()
        engine.dispose()

    assert n_teachers > 0
    floor_rules = [r for r in rules
                   if r["source"] == "teacher_at_least_n_free_days"]
    soft_rules = [r for r in rules
                  if r["source"] == "teacher_free_day_preference"]
    legacy_rules = [r for r in rules
                    if "free_day_choice_3way" in r.get("expression", "")]
    assert len(floor_rules) == n_teachers, (
        f"expected one HARD floor per teacher; got "
        f"{len(floor_rules)}/{n_teachers}")
    assert len(soft_rules) == 3 * n_teachers, (
        f"expected 3 SOFT priority rules per teacher; got "
        f"{len(soft_rules)} (with {n_teachers} teachers)")
    soft_weights = sorted({int(r["weight"]) for r in soft_rules})
    assert soft_weights == [10, 20, 30], soft_weights
    assert not legacy_rules, (
        f"no rule must use the legacy free_day_choice_3way pragma "
        f"(found {len(legacy_rules)})")
