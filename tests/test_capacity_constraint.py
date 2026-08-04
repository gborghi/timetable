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
    """Built through the engine's own ``_normalize_classroom`` rather
    than hand-listing keys: ``_can_host`` reads several of them with
    ``room[...]``, so a room dict assembled by hand starts raising
    ``KeyError`` the moment the engine grows a new HARD axis (that is
    exactly how ``subject_forbidden`` broke these tests). Only the
    values this suite actually varies are spelled out."""
    return ca._normalize_classroom({
        "name": name, "kind": kind, "capacity": capacity,
        "multi_class": False, "multi_class_max": 1,
        "multi_class_pref": 1, "multi_class_pref_weight": 0.0,
    })


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


# ---------- Required-kind HARD: subject must land in matching room ----


def test_can_host_blocks_wrong_kind():
    """required_kind='palestra' rejects every non-palestra room."""
    lesson = {
        "teacher": "T", "co_teachers": [],
        "class": "3A", "subject": "Educazione Fisica",
        "day": 1, "hour": 1, "n_students": 22,
        "required_kind": "palestra",
    }
    standard = _make_room("Aula 12", capacity=30, kind="standard")
    palestra = _make_room("Palestra A", capacity=60, kind="palestra")
    assert ca._can_host(standard, lesson) is False
    assert ca._can_host(palestra, lesson) is True


def test_can_host_required_kind_empty_means_any():
    lesson = {
        "teacher": "T", "co_teachers": [],
        "class": "3A", "subject": "Mat", "day": 1, "hour": 1,
        "n_students": 22, "required_kind": "",
    }
    standard = _make_room("Aula 12", capacity=30, kind="standard")
    palestra = _make_room("Palestra A", capacity=60, kind="palestra")
    assert ca._can_host(standard, lesson) is True
    assert ca._can_host(palestra, lesson) is True


def test_solve_picks_palestra_for_eduf_subject():
    """End-to-end: a single Educazione Fisica lesson must land in
    the palestra even when other rooms have plenty of capacity."""
    lessons = [{
        "teacher": "T", "co_teachers": [], "class": "3A",
        "subject": "Educazione Fisica", "day": 1, "hour": 1,
        "n_students": 22, "required_kind": "palestra",
    }]
    rooms = [
        _make_room("Aula 12",    capacity=30, kind="standard"),
        _make_room("Aula Magna", capacity=80, kind="standard"),
        _make_room("Palestra A", capacity=60, kind="palestra"),
    ]
    out, status = ca.solve_classroom_assignment(
        lessons, rooms, time_limit_s=10, workers=1)
    assert out is not None, f"unexpectedly infeasible: {status}"
    assert out[("3A", "Educazione Fisica", 1, 1)] == "Palestra A"


def test_solve_lab_fisica_hard():
    """Physics lesson with required_kind='lab_fisica' rejects
    every other lab kind."""
    lessons = [{
        "teacher": "T", "co_teachers": [], "class": "5A",
        "subject": "Fisica", "day": 1, "hour": 1, "n_students": 22,
        "required_kind": "lab_fisica",
    }]
    rooms = [
        _make_room("Aula 12",       capacity=30, kind="standard"),
        _make_room("Lab chimica",   capacity=24, kind="lab_chimica"),
        _make_room("Lab fisica",    capacity=24, kind="lab_fisica"),
    ]
    out, status = ca.solve_classroom_assignment(
        lessons, rooms, time_limit_s=10, workers=1)
    assert out is not None, f"unexpectedly infeasible: {status}"
    assert out[("5A", "Fisica", 1, 1)] == "Lab fisica"


def test_solve_no_eligible_when_required_kind_missing():
    """Asking for a palestra when none exists -> NO_ELIGIBLE."""
    lessons = [{
        "teacher": "T", "co_teachers": [], "class": "3A",
        "subject": "Educazione Fisica", "day": 1, "hour": 1,
        "n_students": 22, "required_kind": "palestra",
    }]
    rooms = [
        _make_room("Aula 12",    capacity=30, kind="standard"),
        _make_room("Aula Magna", capacity=80, kind="standard"),
    ]
    out, status = ca.solve_classroom_assignment(
        lessons, rooms, time_limit_s=10, workers=1)
    assert out is None
    assert status.startswith("NO_ELIGIBLE")
