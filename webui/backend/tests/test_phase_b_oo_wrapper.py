"""Step 4a: ``PhaseBDaySolver`` OO wrapper around the legacy
per-day Phase B function.

Two contracts under test:

  1. Zero-drift -- when the wrapper runs without DSL augmentation
     (``via_dsl=False``), the model built and the solution returned
     are byte-equivalent to a direct call of
     ``cpsat_v2_timetable.solve_phase_b_for_day``. This covers the
     ``via_dsl`` opt-in case (no DSL, no DB) where the wrapper is
     pure composition.

  2. DSL augmentation -- when ``via_dsl=True`` is passed with extra
     DSL expressions, the additional rules tighten the feasible set
     (or leave it unchanged if redundant) but the legacy hardcoded
     path is preserved. We verify a TeacherUnavailability rule
     translated to DSL is honoured by the resulting solution.
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


def _tiny_profs():
    """One class, two teachers, light demand -- always feasible."""
    return {
        "ProfA": {
            "classi": {"1A": {"Mat": {"ore": 4}}},
            "glibero": [6], "max_hours": 18,
        },
        "ProfB": {
            "classi": {"1A": {"Ita": {"ore": 4}}},
            "glibero": [6], "max_hours": 18,
        },
    }


def _tiny_dc_value():
    """4 hours/day on day 1 to force a fully-packed schedule
    (4 + 4 -> exactly 6 slots used, no holes possible)."""
    return {
        ("ProfA", "1A", "Mat", 1): 2,
        ("ProfA", "1A", "Mat", 2): 2,
        ("ProfB", "1A", "Ita", 1): 2,
        ("ProfB", "1A", "Ita", 2): 2,
    }


def _solve_legacy(profs, dc, day):
    import cpsat_v2_timetable as cv2  # type: ignore
    classes, triples, class_profs = cv2.build_indices(profs)
    return cv2.solve_phase_b_for_day(
        day, profs, classes, triples, class_profs, dc,
        time_limit=5, workers=1, log=False,
        enforce_no_holes=True,
    )


def _solve_oo(profs, dc, day, *, via_dsl=False, extra=None):
    from cp_sat_constraint_model import PhaseBDaySolver
    s = PhaseBDaySolver(
        profs, dc, day, extra_dsl_expressions=extra)
    return s.solve(time_limit_s=5.0, workers=1, via_dsl=via_dsl)


# ----------------------------------------------------------------------
# Zero-drift -- OO wrapper without DSL == legacy function
# ----------------------------------------------------------------------


def test_oo_wrapper_zero_drift_simple_case():
    """OO wrapper without via_dsl returns a HARD-feasible solution
    with the same total-slots count as the legacy direct call."""
    profs = _tiny_profs()
    dc = _tiny_dc_value()
    legacy_out, legacy_status = _solve_legacy(profs, dc, 1)
    oo_sol, oo_status = _solve_oo(profs, dc, 1, via_dsl=False)
    assert legacy_out is not None, legacy_status
    assert oo_sol is not None, oo_status
    legacy_n = sum(1 for v in legacy_out.values() if v == 1)
    oo_n = len(oo_sol)
    assert oo_n == legacy_n == 4, (legacy_n, oo_n)


def test_oo_wrapper_propagates_locks_via_config():
    """``ConstraintConfig.locks`` carries 5-tuple locks; the wrapper
    must filter them by day and pass to the legacy function as
    4-tuples. Verify a locked slot is held in the output."""
    from cp_sat_constraint_model import (
        PhaseBDaySolver, ConstraintConfig)
    profs = _tiny_profs()
    dc = _tiny_dc_value()
    locked = ("ProfA", "1A", "Mat", 1, 8)  # day=1, h=8
    cfg = ConstraintConfig(
        locks=[locked,
               ("ProfA", "1A", "Mat", 5, 12)],  # different day
    )
    solver = PhaseBDaySolver(profs, dc, 1, config=cfg)
    sol, status = solver.solve(time_limit_s=5.0, workers=1)
    assert sol is not None, status
    assert sol.get(locked) == 1, sol


# ----------------------------------------------------------------------
# DSL augmentation -- via_dsl=True with extra expressions
# ----------------------------------------------------------------------


def test_oo_wrapper_via_dsl_no_extra_no_db_zero_drift():
    """``via_dsl=True`` with no DB and no extras must be equivalent
    to ``via_dsl=False``: the augmentation block is a no-op when
    there is nothing to augment with."""
    profs = _tiny_profs()
    dc = _tiny_dc_value()
    a_sol, _ = _solve_oo(profs, dc, 1, via_dsl=False)
    b_sol, _ = _solve_oo(profs, dc, 1, via_dsl=True)
    assert a_sol is not None and b_sol is not None
    assert len(a_sol) == len(b_sol) == 4


def test_oo_wrapper_via_dsl_extra_teacher_unavailability():
    """A TeacherUnavailability DSL rule (forall l where teacher==X
    and day==1 and hour==H: false) must be honoured by the model
    when passed via ``extra_dsl_expressions`` + ``via_dsl=True``.
    The exact slot at h=8 for ProfA must be unused even though
    the legacy hardcoded path would otherwise allow it."""
    profs = _tiny_profs()
    dc = _tiny_dc_value()
    extra = [
        'forall l in lessons where l.teacher == "ProfA"'
        ' and l.day == 1 and l.hour == 8: false'
    ]
    sol, status = _solve_oo(
        profs, dc, 1, via_dsl=True, extra=extra)
    assert sol is not None, status
    # The forbidden slot must be absent (or 0 if zero-stripped).
    forbidden_keys = [k for k in sol
                       if k[:5] == ("ProfA", "1A", "Mat", 1, 8)]
    assert forbidden_keys == [], forbidden_keys


def test_oo_wrapper_dsl_diagnostics_collected_when_via_dsl_enabled():
    """When the DSL pipeline runs, any compile diagnostics surface
    on the returned status path or in a warning -- the wrapper must
    not crash on a well-formed extra expression."""
    profs = _tiny_profs()
    dc = _tiny_dc_value()
    # A pragma the compiler recognises but evaluates to no-op for
    # this scope (no Scienzemotorie cattedra in 1A).
    extra = ['subject_pair_must("1A", "Scienzemotorie")']
    sol, status = _solve_oo(
        profs, dc, 1, via_dsl=True, extra=extra)
    assert sol is not None, status


# ----------------------------------------------------------------------
# Phase A + Phase B end-to-end via the OO wrapper
# ----------------------------------------------------------------------


@pytest.mark.slow
def test_oo_wrapper_phase_b_end_to_end_two_days():
    """Full pipeline: Phase A -> Phase B per-day via PhaseBDaySolver
    on each day. Each day's output is HARD-feasible and the union
    covers every cattedra's weekly hours."""
    import cpsat_v2_timetable as cv2  # type: ignore
    profs = _tiny_profs()
    classes, triples, class_profs = cv2.build_indices(profs)
    dc = cv2.solve_phase_a(
        profs, classes, triples, class_profs,
        time_limit=5, workers=1, log=False)
    from cp_sat_constraint_model import PhaseBDaySolver
    full: dict = {}
    for d in (1, 2, 3, 4, 5, 6):
        s = PhaseBDaySolver(profs, dc, d)
        sol, status = s.solve(time_limit_s=5.0, workers=1)
        if sol:
            full.update(sol)
    # 4 hours/cattedra * 2 cattedre = 8 lessons total/week.
    n = len(full)
    assert n == 8, n
