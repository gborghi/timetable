"""Atom 7 — native lock support in classroom assignment.

Tests that solve_classroom_assignment honours `locked_classrooms`:
the listed rooms are forced; an ineligible-room lock is reported
as INFEASIBLE with a clear status.
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


def _scenario():
    """3 lessons, 2 classrooms (R1 standard, R2 lab)."""
    lessons = [
        {"teacher": "ProfA", "co_teachers": [],
         "class": "1A", "subject": "Mat", "day": 1, "hour": 8},
        {"teacher": "ProfB", "co_teachers": [],
         "class": "1A", "subject": "Ita", "day": 1, "hour": 9},
        {"teacher": "ProfC", "co_teachers": [],
         "class": "1A", "subject": "Sci", "day": 1, "hour": 10},
    ]
    classrooms = [
        {"name": "R1", "kind": "standard", "capacity": 30,
         "multi_class": False, "multi_class_max": 1,
         "unavailability": set(), "subject_required": set(),
         "subject_pref_weight": {}, "class_pref_weight": {},
         "is_home_for": set()},
        {"name": "R2", "kind": "lab_chimica", "capacity": 30,
         "multi_class": False, "multi_class_max": 1,
         "unavailability": set(),
         "subject_required": {"Sci"},  # Sci-only lab
         "subject_pref_weight": {}, "class_pref_weight": {},
         "is_home_for": set()},
    ]
    return lessons, classrooms


def test_classroom_lock_honoured():
    import classroom_assignment as ca  # type: ignore
    lessons, classrooms = _scenario()
    # Lock Mat lun-8 -> R1 (eligible: standard room).
    locked = [("1A", "Mat", 1, 8, "R1")]
    mapping, status = ca.solve_classroom_assignment(
        lessons, classrooms, time_limit_s=2, workers=2,
        locked_classrooms=locked,
    )
    assert mapping is not None, status
    assert mapping[("1A", "Mat", 1, 8)] == "R1"


def test_classroom_lock_to_ineligible_room_is_infeasible():
    import classroom_assignment as ca  # type: ignore
    lessons, classrooms = _scenario()
    # Lock Mat -> R2: R2 is Sci-only; eligibility filter rejects R2
    # for Mat. solver returns None with LOCKED_INELIGIBLE status.
    locked = [("1A", "Mat", 1, 8, "R2")]
    mapping, status = ca.solve_classroom_assignment(
        lessons, classrooms, time_limit_s=2, workers=2,
        locked_classrooms=locked,
    )
    assert mapping is None
    assert status.startswith("LOCKED_INELIGIBLE")
