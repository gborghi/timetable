"""Task C1 — shadow (sostegno) constraint in CP-SAT.

Tests that solve_phase_a + solve_phase_b_for_day, given a list
of support assignments, place the sostegno hours such that:
- Each support slot coincides with a non-support lesson in the
  same class at the same hour.
- The class-busy constraint counts that slot as ONE occupation
  (not two).
- Per-day support hours <= cl_day_load.
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(HERE)
WEBUI_DIR = os.path.dirname(BACKEND_DIR)
REPO_ROOT = os.path.dirname(WEBUI_DIR)
ENGINE_DIR = os.path.join(REPO_ROOT, "engine")
for p in (WEBUI_DIR, ENGINE_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


def _profs_with_sostegno():
    """3B with 12 weekly hours (Mat 4 + Ita 4 + Sto 4) split 6+6
    over two days, plus a sostegno teacher with 4 hours that must
    fall on slots where the class has another (non-support) lesson.
    """
    return {
        "ProfA": {
            "classi": {"3B": {"Matematica": {"ore": 4}}},
            "glibero": [6, 5, 4],
        },
        "ProfB": {
            "classi": {"3B": {"Italiano": {"ore": 4}}},
            "glibero": [6, 5, 4],
        },
        "ProfC": {
            "classi": {"3B": {"Storia": {"ore": 4}}},
            "glibero": [6, 5, 4],
        },
        "ProfSost": {
            "classi": {"3B": {"sostegno": {"ore": 4}}},
            "glibero": [6, 5, 4],
        },
    }


def _solve(profs, support_assignments=None, *, time_a=2, time_b=2):
    import cpsat_v2_timetable as cv2  # type: ignore
    classes_v, triples, class_profs = cv2.build_indices(profs)
    dc = cv2.solve_phase_a(
        profs, classes_v, triples, class_profs,
        time_limit=time_a, workers=2, log=False,
        support_assignments=support_assignments,
    )
    full = {}
    for d in cv2.DAYS:
        out, _ = cv2.solve_phase_b_for_day(
            d, profs, classes_v, triples, class_profs, dc,
            time_limit=time_b, workers=2, log=False,
            support_assignments=support_assignments,
        )
        if out:
            full.update(out)
    return dc, full


def test_sostegno_follows_class():
    """Every support slot must coincide with a non-support lesson
    in 3B at the same hour."""
    profs = _profs_with_sostegno()
    sup = [{"teacher_name": "ProfSost", "class_name": "3B",
            "subject": "sostegno", "n_hours": 4}]
    dc, sol = _solve(profs, support_assignments=sup)

    # ProfSost has 4 hours total.
    n = sum(v for (p, c, s, _, _), v in sol.items()
            if p == "ProfSost" and c == "3B" and s == "sostegno")
    assert n == 4, f"ProfSost should have 4h, got {n}"

    # Every support slot has at least one non-support 3B lesson at
    # the same (day, hour).
    for k, v in list(sol.items()):
        p, c, s, d, h = k
        if p != "ProfSost" or v != 1:
            continue
        non_support = [
            kk for kk, kv in sol.items()
            if kk[1] == "3B" and kk[3] == d and kk[4] == h
            and kk[2] != "sostegno" and kv == 1
        ]
        assert non_support, (
            f"support slot ({d},{h}) without any non-support "
            f"lesson in 3B")


def test_sostegno_does_not_add_class_occupation():
    """The class-busy constraint must NOT count support slots as a
    fresh class occupation; without the exclusion the class would
    be considered double-booked at every support hour."""
    profs = _profs_with_sostegno()
    sup = [{"teacher_name": "ProfSost", "class_name": "3B",
            "subject": "sostegno", "n_hours": 4}]
    dc, sol = _solve(profs, support_assignments=sup)
    # 12 weekly non-support hours for 3B (Mat 4 + Ita 4 + Sto 4).
    distinct_non_support_slots = {
        (k[3], k[4]) for k, v in sol.items()
        if k[1] == "3B" and v == 1 and k[2] != "sostegno"
    }
    assert len(distinct_non_support_slots) == 12, (
        f"expected 12 non-support slots in 3B, got "
        f"{len(distinct_non_support_slots)}")


def test_sostegno_infeasible_class_has_no_lessons():
    """ProfSost has 4 sostegno hours but the class has 0 non-support
    triples -> infeasible."""
    profs = {
        "ProfSost": {
            "classi": {"3B": {"sostegno": {"ore": 4}}},
            "glibero": [6, 5, 4],
        },
    }
    sup = [{"teacher_name": "ProfSost", "class_name": "3B",
            "subject": "sostegno", "n_hours": 4}]
    with pytest.raises(RuntimeError):
        _solve(profs, support_assignments=sup)
