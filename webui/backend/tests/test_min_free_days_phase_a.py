"""Audit residual: cross-day ``min_free_days`` in the per-day decomposition.

The per-day decomposition builds its day-counts through the NATIVE Phase A
(``pre_distribute_hours`` -> ``cpsat_v2_timetable.solve_phase_a``, no DB), which
used to carry no ``min_free_days`` floor -- only the DB-driven DSL free-day
pragmas (week/monolithic path) did. So a per-day-assembled week could be
full-coverage yet ``metaheuristics.is_hard_feasible`` rejected it, because a
teacher ended up working every day, which a pure per-day solve cannot
coordinate across days.

``solve_phase_a`` now enforces the floor natively from the SAME
``profs["min_free_days"]`` the validator reads, so the day-counts RESERVE the
free days at the source and every downstream per-day solve inherits them.

Instance: one class with six single-subject cattedre (load 4 every day -- a
valid ``{0,4,5,6}`` week). ``T1`` teaches four of those hours; the other five
teachers cover the rest, so ``T1`` can be freed on some days without breaking
class coverage.
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "engine"))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)


def _cv2():
    import cpsat_v2_timetable as cv2  # type: ignore
    return cv2


_FLAGS = {"1A": {"entry_at_8": False, "no_holes": False, "exit_after_12": False}}


def _instance(t1_min_free_days):
    """One class, six 4-hour cattedre (distinct subjects). Only T1 carries a
    free-day floor; the rest cover the class so freeing T1 stays feasible."""
    cv2 = _cv2()
    profs = {
        f"T{i}": {
            "classi": {"1A": {f"S{i}": {"ore": 4}}},
            "max_hours": 30,
            "min_free_days": (t1_min_free_days if i == 1 else 0),
        }
        for i in range(1, 7)
    }
    classes, triples, class_profs = cv2.build_indices(profs)
    return profs, classes, triples, class_profs


def _busy_days(dc_value, teacher, days):
    return [
        d for d in days
        if sum(v for k, v in dc_value.items()
               if isinstance(k, tuple) and len(k) == 4
               and k[0] == teacher and k[3] == d) > 0
    ]


def test_phase_a_reserves_min_free_days():
    cv2 = _cv2()
    profs, classes, triples, class_profs = _instance(t1_min_free_days=4)
    dc = cv2.solve_phase_a(
        profs, classes, triples, class_profs,
        time_limit=20, workers=1, log=False, class_flags=_FLAGS,
    )
    assert dc is not None
    free = len(cv2.DAYS) - len(_busy_days(dc, "T1", cv2.DAYS))
    assert free >= 4, f"T1 got only {free} free day(s), min_free_days=4 dropped"
    # Class coverage is still exact: 6 cattedre x 4 hours = 24 hours.
    total = sum(v for k, v in dc.items()
                if isinstance(k, tuple) and len(k) == 4)
    assert total == 24, total


def test_phase_a_min_free_days_zero_is_unconstrained():
    """min_free_days == 0 adds no floor (regression guard for the common
    case): the solve still succeeds with full coverage."""
    cv2 = _cv2()
    profs, classes, triples, class_profs = _instance(t1_min_free_days=0)
    dc = cv2.solve_phase_a(
        profs, classes, triples, class_profs,
        time_limit=20, workers=1, log=False, class_flags=_FLAGS,
    )
    assert dc is not None
    total = sum(v for k, v in dc.items()
                if isinstance(k, tuple) and len(k) == 4)
    assert total == 24, total


def test_phase_a_min_free_days_floor_is_load_bearing():
    """An impossible floor is a PROVEN infeasibility, not a silent violation.

    T1's four hours cannot fit in a single day (per-triple cap is 2h/day), so
    demanding five free days out of six is genuinely infeasible. Crucially the
    SAME instance is feasible with a lower floor -- so this INFEASIBLE outcome
    is caused ONLY by the new native floor (on the pre-fix solver it would
    have solved fine, silently violating min_free_days).
    """
    cv2 = _cv2()
    profs, classes, triples, class_profs = _instance(
        t1_min_free_days=len(cv2.DAYS) - 1)
    with pytest.raises(cv2.PhaseAInfeasible):
        cv2.solve_phase_a(
            profs, classes, triples, class_profs,
            time_limit=20, workers=1, log=False, class_flags=_FLAGS,
        )
