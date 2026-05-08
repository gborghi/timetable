"""HARD capacity constraint pytest.

Pins the per-room capacity rule:

  for every Lesson L: L.classroom.capacity >= L.school_class.n_students

Implemented natively in ``engine.classroom_assignment._can_host``
(and mirrored as the ``classroom_capacity_ok`` DSL pragma for
solvers that build a joint slot+room decision space).

The tests live under top-level ``tests/`` so
``pytest tests/test_capacity_constraint.py`` works from the project
root without needing the webui backend package.
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
ENGINE = os.path.join(ROOT, "engine")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)


# Lazy import so a missing ortools (CI matrix without the engine deps)
# fails the test cleanly with a skip rather than a collection error.
ortools = pytest.importorskip("ortools.sat.python.cp_model")
ca = pytest.importorskip("classroom_assignment")


def _make_lessons(class_name: str, n_students: int):
    """One lesson per slot for the same class -- exercises capacity
    against every candidate room independently."""
    return [
        {"teacher": "T", "co_teachers": [],
         "class": class_name, "subject": "Mat",
         "day": 1, "hour": 1, "n_students": n_students},
    ]


def _make_room(name: str, capacity: int, *, kind: str = "standard"):
    return {
        "name": name, "kind": kind, "capacity": capacity,
        "multi_class": False, "multi_class_max": 1,
        "multi_class_pref": 1, "multi_class_pref_weight": 0.0,
        "unavailability": set(),
        "subject_required": set(),
        "subject_pref_weight": {},
        "class_pref_weight": {},
        "is_home_for": set(),
    }


# ---------- _can_host unit tests (pure HARD eligibility) ----------


def test_can_host_blocks_room_too_small():
    lesson = _make_lessons("3A", n_students=28)[0]
    room_small = _make_room("Aula 1", capacity=24)
    assert ca._can_host(room_small, lesson) is False


def test_can_host_allows_room_exactly_fitting():
    lesson = _make_lessons("3A", n_students=28)[0]
    room_fit = _make_room("Aula Magna", capacity=28)
    assert ca._can_host(room_fit, lesson) is True


def test_can_host_skips_capacity_when_n_students_missing():
    lesson = _make_lessons("3A", n_students=0)[0]
    room_small = _make_room("Aula 1", capacity=10)
    # n_students=0 (or absent) bypasses the rule for legacy callers
    assert ca._can_host(room_small, lesson) is True


# ---------- end-to-end CP-SAT solve: the 28-student class only fits
# in rooms with capacity >= 28. With one big room and several small
# ones, the solver must pick the big room. ----------


def test_solve_picks_big_room_for_big_class():
    lessons = _make_lessons("3A", n_students=28)
    rooms = [
        _make_room("Aula 1",     capacity=20),
        _make_room("Aula 2",     capacity=24),
        _make_room("Aula Magna", capacity=30),
    ]
    out, status = ca.solve_classroom_assignment(
        lessons, rooms, time_limit_s=10, workers=1)
    assert out is not None, f"unexpectedly infeasible: {status}"
    assert out[("3A", "Mat", 1, 1)] == "Aula Magna"


def test_solve_returns_no_eligible_when_all_rooms_too_small():
    """28 students, every room <= 24 capacity -- no eligible room
    means the solver returns the diagnostic ``NO_ELIGIBLE:...`` code
    (set in ``solve_classroom_assignment`` before the model is even
    built)."""
    lessons = _make_lessons("3A", n_students=28)
    rooms = [
        _make_room("Aula 1", capacity=20),
        _make_room("Aula 2", capacity=24),
    ]
    out, status = ca.solve_classroom_assignment(
        lessons, rooms, time_limit_s=10, workers=1)
    assert out is None
    assert status.startswith("NO_ELIGIBLE")


def test_greedy_respects_capacity():
    """Greedy fallback also goes through ``_can_host`` so it can't
    place an oversized class in a small room."""
    lessons = _make_lessons("3A", n_students=28)
    rooms = [
        _make_room("Aula Piccola", capacity=18),
        _make_room("Aula Magna",   capacity=30),
    ]
    out = ca.greedy_classroom_assignment(lessons, rooms)
    assert out[("3A", "Mat", 1, 1)] == "Aula Magna"


def test_solve_two_classes_must_each_get_a_fitting_room():
    """A 28-student class and an 18-student class share two rooms
    (one big, one small) at the same slot -- the solver must place
    the big class in the big room and the small class in the small
    one. With a 1-room-per-slot HARD limit, swapping is infeasible."""
    lessons = [
        {"teacher": "T1", "co_teachers": [], "class": "3A",
         "subject": "Mat", "day": 1, "hour": 1, "n_students": 28},
        {"teacher": "T2", "co_teachers": [], "class": "1B",
         "subject": "Sto", "day": 1, "hour": 1, "n_students": 18},
    ]
    rooms = [
        _make_room("Aula Piccola", capacity=20),
        _make_room("Aula Magna",   capacity=30),
    ]
    out, status = ca.solve_classroom_assignment(
        lessons, rooms, time_limit_s=10, workers=1)
    assert out is not None, f"unexpectedly infeasible: {status}"
    assert out[("3A", "Mat", 1, 1)] == "Aula Magna"
    assert out[("1B", "Sto", 1, 1)] == "Aula Piccola"
