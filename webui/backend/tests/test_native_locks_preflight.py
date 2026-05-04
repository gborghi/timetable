"""FU-3 — pre-flight lock validation.

Tests the structural HARD checks performed in
optimization.validate_locks_vs_constraints. They run on a synthetic
snapshot list (no DB needed), so the test is fast.
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(HERE)
WEBUI_DIR = os.path.dirname(BACKEND_DIR)
if WEBUI_DIR not in sys.path:
    sys.path.insert(0, WEBUI_DIR)


def _snap(t, c, s, d, h, room=None):
    return {"teacher_name": t, "class_name": c, "subject": s,
            "day": d, "hour": h, "classroom_name": room,
            "cotaught_with": None}


def test_preflight_passes_on_empty():
    from backend.optimization import validate_locks_vs_constraints
    assert validate_locks_vs_constraints([]) == []


def test_preflight_passes_on_clean_snapshot():
    from backend.optimization import validate_locks_vs_constraints
    snap = [
        _snap("ProfA", "1A", "Mat", 2, 8, "R1"),
        _snap("ProfA", "1A", "Mat", 2, 9, "R1"),
        _snap("ProfB", "1A", "Ita", 2, 10),
    ]
    violations = validate_locks_vs_constraints(snap)
    assert violations == [], violations


def test_preflight_flags_too_many_hours_same_cattedra_one_day():
    from backend.optimization import validate_locks_vs_constraints
    snap = [
        _snap("ProfA", "1A", "Mat", 2, 8),
        _snap("ProfA", "1A", "Mat", 2, 9),
        _snap("ProfA", "1A", "Mat", 2, 10),  # 3 > MAX_PER_DAY_TRIPLE=2
    ]
    violations = validate_locks_vs_constraints(snap)
    assert violations
    msg = " ".join(violations)
    assert "ProfA" in msg and "Mat" in msg and "cattedra" in msg


def test_preflight_flags_class_in_two_lessons_simultaneously():
    from backend.optimization import validate_locks_vs_constraints
    snap = [
        _snap("ProfA", "1A", "Mat", 2, 8),
        _snap("ProfB", "1A", "Ita", 2, 8),  # 1A already busy
    ]
    violations = validate_locks_vs_constraints(snap)
    assert violations
    msg = " ".join(violations)
    assert "1A" in msg
    assert "contemporanea" in msg.lower()


def test_preflight_flags_prof_in_two_classes_simultaneously():
    from backend.optimization import validate_locks_vs_constraints
    snap = [
        _snap("ProfA", "1A", "Mat", 2, 8),
        _snap("ProfA", "1B", "Mat", 2, 8),  # ProfA double-booked
    ]
    violations = validate_locks_vs_constraints(snap)
    assert violations
    msg = " ".join(violations)
    assert "ProfA" in msg


def test_preflight_flags_classroom_double_book():
    from backend.optimization import validate_locks_vs_constraints
    snap = [
        _snap("ProfA", "1A", "Mat", 2, 8, "R1"),
        _snap("ProfB", "1B", "Ita", 2, 8, "R1"),  # same room, same slot
    ]
    violations = validate_locks_vs_constraints(snap)
    assert violations
    msg = " ".join(violations)
    assert "R1" in msg


def test_preflight_flags_too_many_prof_hours_per_day():
    """6 lock for the same prof in one day exceeds
    MAX_PROF_HOURS_PER_DAY=5."""
    from backend.optimization import validate_locks_vs_constraints
    snap = [
        _snap("ProfA", "1A", "Mat", 2, 8),
        _snap("ProfA", "1A", "Mat", 2, 9),
        _snap("ProfA", "1B", "Mat", 2, 10),
        _snap("ProfA", "1B", "Mat", 2, 11),
        _snap("ProfA", "1C", "Mat", 2, 12),
        _snap("ProfA", "1C", "Mat", 2, 13),
    ]
    violations = validate_locks_vs_constraints(snap)
    msg = " ".join(violations)
    assert "ProfA" in msg
    assert "docente" in msg
