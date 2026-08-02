"""The ``lagrangian_penalties`` hook on ``solve_phase_b_for_day``.

The genuine Lagrangian dualizes the cross-cluster bridge-teacher no-overlap
coupling and PRICES it into each cluster's per-day objective through this
hook: ``lagrangian_penalties={(teacher, hour): weight}`` adds ``weight *
slot`` for every slot of that teacher at that hour, so the CP objective is
steered to place the teacher's (dc_value-fixed) hours away from contended
slots. ``None`` leaves the objective byte-identical for every other caller.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "engine"))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

_FLAGS = {"1A": {"entry_at_8": False, "no_holes": False,
                 "exit_after_12": False}}


def _cv2():
    import cpsat_v2_timetable as cv2  # type: ignore
    return cv2


def _instance():
    cv2 = _cv2()
    profs = {"T1": {"classi": {"1A": {"Mat": {"ore": 1}}},
                    "max_hours": 18, "min_free_days": 0}}
    classes, triples, class_profs = cv2.build_indices(profs)
    dc_value = {("T1", "1A", "Mat", 1): 1}
    return profs, classes, triples, class_profs, dc_value


def _placed(sol):
    return {k for k, v in (sol or {}).items() if int(v) == 1}


def test_penalty_steers_placement_off_contended_hours():
    cv2 = _cv2()
    profs, classes, triples, class_profs, dc = _instance()
    pen = {("T1", h): 1000 for h in (8, 9, 10, 11, 12)}
    out, _ = cv2.solve_phase_b_for_day(
        1, profs, classes, triples, class_profs, dc,
        time_limit=5, workers=1, class_flags=_FLAGS,
        lagrangian_penalties=pen)
    placed = _placed(out)
    assert len(placed) == 1, placed
    # every hour but 13 is heavily penalized -> the one Mat hour lands on 13.
    assert ("T1", "1A", "Mat", 1, 13) in placed, placed


def test_no_penalty_is_unchanged():
    cv2 = _cv2()
    profs, classes, triples, class_profs, dc = _instance()
    base, _ = cv2.solve_phase_b_for_day(
        1, profs, classes, triples, class_profs, dc,
        time_limit=5, workers=1, class_flags=_FLAGS)
    none_pen, _ = cv2.solve_phase_b_for_day(
        1, profs, classes, triples, class_profs, dc,
        time_limit=5, workers=1, class_flags=_FLAGS,
        lagrangian_penalties=None)
    empty_pen, _ = cv2.solve_phase_b_for_day(
        1, profs, classes, triples, class_profs, dc,
        time_limit=5, workers=1, class_flags=_FLAGS,
        lagrangian_penalties={})
    assert _placed(base) == _placed(none_pen) == _placed(empty_pen)
