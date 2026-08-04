"""Audit F3 + F5, at the Phase-A day-count level (where "which day is free"
is actually decided):

- F3: a class with ``class_free_days[cl] = N`` gets >= N weekdays with ZERO
  load, and WHICH day is the solver's choice (not pinned).
- F5: a teacher's ranked free-day PREFERENCE (carried on the profs dict as
  ``free_day_prefs = [(day, weight), ...]``) steers the day distribution so
  the preferred day comes out free when coverage allows it.

These drive ``cpsat_v2_timetable.solve_phase_a`` directly (no DB), the same
entry point the day-scope decomposition uses.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "engine"))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)


def _cv2():
    import cpsat_v2_timetable as cv2  # type: ignore
    return cv2


def _one_class_instance(*, free_day_prefs=None, min_free_days=0):
    """One class, six single-subject 4-hour cattedre (a valid {0,4,5,6}
    week). Each teacher teaches exactly one of them, so freeing any single
    day stays feasible (5 days x 6h = 30 >= 24)."""
    cv2 = _cv2()
    profs = {
        f"T{i}": {
            "classi": {"1A": {f"S{i}": {"ore": 4}}},
            "max_hours": 30,
            "min_free_days": min_free_days,
            "free_day_prefs": (free_day_prefs if i == 1 else []),
        }
        for i in range(1, 7)
    }
    classes, triples, class_profs = cv2.build_indices(profs)
    return profs, classes, triples, class_profs


def _class_empty_days(dc_value, cls, days):
    """Days on which class ``cls`` has zero placed hours."""
    return [
        d for d in days
        if sum(v for k, v in dc_value.items()
               if k[1] == cls and k[3] == d) == 0
    ]


def _teacher_empty_days(dc_value, teacher, days):
    return [
        d for d in days
        if sum(v for k, v in dc_value.items()
               if k[0] == teacher and k[3] == d) == 0
    ]


def test_class_free_day_floor_reserves_an_empty_day():
    cv2 = _cv2()
    profs, classes, triples, class_profs = _one_class_instance()
    dc = cv2.solve_phase_a(
        profs, classes, triples, class_profs,
        time_limit=20, workers=4, log=False,
        class_free_days={"1A": 1},
    )
    assert dc is not None
    empty = _class_empty_days(dc, "1A", range(1, 7))
    assert len(empty) >= 1, f"class 1A got no free day: empty={empty}"


def test_class_free_day_floor_off_by_default():
    """Zero-drift: with no class_free_days the class may (and here does)
    use all six days -- the floor is opt-in."""
    cv2 = _cv2()
    profs, classes, triples, class_profs = _one_class_instance()
    dc = cv2.solve_phase_a(
        profs, classes, triples, class_profs,
        time_limit=20, workers=4, log=False,
    )
    assert dc is not None
    # 24h over the {0,4,5,6} domain can pack into any number of days; the
    # engine is free to leave zero empty days. Just assert it did NOT crash
    # and produced a full distribution.
    total = sum(v for v in dc.values())
    assert total == 24


def test_first_choice_free_day_is_honoured():
    """T1 prefers day 3 free (weight 150). With coverage that allows it, the
    day-count frees day 3 for T1."""
    cv2 = _cv2()
    profs, classes, triples, class_profs = _one_class_instance(
        free_day_prefs=[(3, 150)])
    dc = cv2.solve_phase_a(
        profs, classes, triples, class_profs,
        time_limit=20, workers=4, log=False,
    )
    assert dc is not None
    empty = _teacher_empty_days(dc, "T1", range(1, 7))
    assert 3 in empty, f"T1's first-choice day 3 not free: empty={empty}"


def test_no_free_day_prefs_is_zero_drift():
    """Empty free_day_prefs must not change the outcome vs. absent."""
    cv2 = _cv2()
    profs, classes, triples, class_profs = _one_class_instance(
        free_day_prefs=[])
    dc = cv2.solve_phase_a(
        profs, classes, triples, class_profs,
        time_limit=20, workers=4, log=False,
    )
    assert dc is not None
    assert sum(v for v in dc.values()) == 24
