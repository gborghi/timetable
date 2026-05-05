"""End-to-end CP-SAT tests: plessi rules wired into
engine/classroom_assignment.py (P3 follow-up).

A small synthetic instance with rooms split across two plessi proves
the solver:
  - moves the teacher's two adjacent lessons to the SAME plesso
    when a teacher commuting rule forbids cross-plesso moves;
  - obeys single_plesso_per_day even when only one slot is in
    common with a different-plesso lesson.

The tests do NOT touch the database; they feed PlessiData directly,
matching how unit tests for plessi_constraints already work.
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "engine"))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)


def _basic_rooms():
    """Two rooms in plesso 1 (A-side), two in plesso 2 (B-side).
    All accept any subject."""
    return [
        {"name": "A1", "kind": "standard", "capacity": 30,
         "multi_class": False, "multi_class_max": 1},
        {"name": "A2", "kind": "standard", "capacity": 30,
         "multi_class": False, "multi_class_max": 1},
        {"name": "B1", "kind": "standard", "capacity": 30,
         "multi_class": False, "multi_class_max": 1},
        {"name": "B2", "kind": "standard", "capacity": 30,
         "multi_class": False, "multi_class_max": 1},
    ]


def _make_plessi(rules=(), policies=()):
    import plessi_constraints as pc
    data = pc.PlessiData(
        classroom_to_plesso={"A1": 1, "A2": 1, "B1": 2, "B2": 2},
        teacher_name_to_id={"Rossi": 10, "Bianchi": 11},
        class_name_to_id={"1A": 100, "1B": 101},
    )
    data.commuting_rules = list(rules)
    data.entity_policies = list(policies)
    return data


def test_solver_runs_without_plessi_data():
    """Sanity: pre-existing behaviour preserved when plessi_data=None."""
    from classroom_assignment import solve_classroom_assignment

    lessons = [
        {"teacher": "Rossi", "co_teachers": [], "class": "1A",
         "subject": "Mate", "day": 1, "hour": 8},
        {"teacher": "Rossi", "co_teachers": [], "class": "1B",
         "subject": "Mate", "day": 1, "hour": 9},
    ]
    out, status = solve_classroom_assignment(
        lessons, _basic_rooms(),
        time_limit_s=5.0, workers=1)
    assert out is not None, status
    assert (("1A", "Mate", 1, 8) in out) and (("1B", "Mate", 1, 9) in out)


def test_commuting_rule_keeps_teacher_in_one_plesso():
    """Rossi has two adjacent lessons (1A@h8, 1B@h9). A commuting
    rule says no teacher may move between plesso 1 and plesso 2 in
    less than 1 hour. Expect both lessons placed in the SAME
    plesso."""
    import plessi_constraints as pc
    from classroom_assignment import solve_classroom_assignment

    lessons = [
        {"teacher": "Rossi", "co_teachers": [], "class": "1A",
         "subject": "Mate", "day": 1, "hour": 8},
        {"teacher": "Rossi", "co_teachers": [], "class": "1B",
         "subject": "Mate", "day": 1, "hour": 9},
    ]
    plessi = _make_plessi(rules=[
        pc.CommutingRule(
            id=1, from_plesso_id=1, to_plesso_id=2,
            entity_kind="teacher", entity_id=None,
            min_gap_hours=1, symmetric=True),
    ])
    out, status = solve_classroom_assignment(
        lessons, _basic_rooms(),
        time_limit_s=5.0, workers=1, plessi_data=plessi)
    assert out is not None, status
    pl_a = plessi.classroom_to_plesso[out[("1A", "Mate", 1, 8)]]
    pl_b = plessi.classroom_to_plesso[out[("1B", "Mate", 1, 9)]]
    assert pl_a == pl_b, (
        f"teacher Rossi crosses plessi: {pl_a} -> {pl_b}")


def test_commuting_rule_specific_overrides_generic():
    """Kind-wide rule says no cross-plesso, but Rossi has a
    per-teacher rule with min_gap_hours=0 (allowing the move).
    Bianchi (no override) must stay in one plesso."""
    import plessi_constraints as pc
    from classroom_assignment import solve_classroom_assignment

    lessons = [
        {"teacher": "Rossi", "co_teachers": [], "class": "1A",
         "subject": "Mate", "day": 1, "hour": 8},
        {"teacher": "Rossi", "co_teachers": [], "class": "1B",
         "subject": "Mate", "day": 1, "hour": 9},
        {"teacher": "Bianchi", "co_teachers": [], "class": "1A",
         "subject": "Ita", "day": 2, "hour": 8},
        {"teacher": "Bianchi", "co_teachers": [], "class": "1B",
         "subject": "Ita", "day": 2, "hour": 9},
    ]
    plessi = _make_plessi(rules=[
        pc.CommutingRule(
            id=1, from_plesso_id=1, to_plesso_id=2,
            entity_kind="teacher", entity_id=None,
            min_gap_hours=1, symmetric=True),
        pc.CommutingRule(
            id=2, from_plesso_id=1, to_plesso_id=2,
            entity_kind="teacher", entity_id=10,  # Rossi
            min_gap_hours=0, symmetric=True),
    ])
    out, _ = solve_classroom_assignment(
        lessons, _basic_rooms(),
        time_limit_s=5.0, workers=1, plessi_data=plessi)
    assert out is not None
    bianchi_a = plessi.classroom_to_plesso[out[("1A", "Ita", 2, 8)]]
    bianchi_b = plessi.classroom_to_plesso[out[("1B", "Ita", 2, 9)]]
    assert bianchi_a == bianchi_b, "Bianchi forbidden from crossing"


def test_single_plesso_per_day_keeps_teacher_in_one_plesso_all_day():
    """Policy single_plesso_per_day: even with a 1-hour gap, the
    teacher's whole day must be in one plesso. Insert two slots at
    h=8 and h=10 (gap = 2) for the same teacher; commuting rule
    says only min_gap=0; the policy still forces same plesso."""
    import plessi_constraints as pc
    from classroom_assignment import solve_classroom_assignment

    lessons = [
        {"teacher": "Rossi", "co_teachers": [], "class": "1A",
         "subject": "Mate", "day": 3, "hour": 8},
        {"teacher": "Rossi", "co_teachers": [], "class": "1B",
         "subject": "Mate", "day": 3, "hour": 10},
    ]
    plessi = _make_plessi(policies=[
        pc.EntityPolicy(
            id=1, entity_kind="teacher", entity_id=10,  # Rossi
            policy="single_plesso_per_day"),
    ])
    out, status = solve_classroom_assignment(
        lessons, _basic_rooms(),
        time_limit_s=5.0, workers=1, plessi_data=plessi)
    assert out is not None, status
    pl_a = plessi.classroom_to_plesso[out[("1A", "Mate", 3, 8)]]
    pl_b = plessi.classroom_to_plesso[out[("1B", "Mate", 3, 10)]]
    assert pl_a == pl_b


def test_single_plesso_total_pins_to_target_plesso():
    """Policy single_plesso_total with plesso_id=2: every room
    assigned to that teacher must be in plesso 2 (B-side)."""
    import plessi_constraints as pc
    from classroom_assignment import solve_classroom_assignment

    lessons = [
        {"teacher": "Rossi", "co_teachers": [], "class": "1A",
         "subject": "Mate", "day": 1, "hour": 8},
        {"teacher": "Rossi", "co_teachers": [], "class": "1B",
         "subject": "Mate", "day": 4, "hour": 11},  # diff day
    ]
    plessi = _make_plessi(policies=[
        pc.EntityPolicy(
            id=1, entity_kind="teacher", entity_id=10,
            policy="single_plesso_total", plesso_id=2),
    ])
    out, status = solve_classroom_assignment(
        lessons, _basic_rooms(),
        time_limit_s=5.0, workers=1, plessi_data=plessi)
    assert out is not None, status
    for k, v in out.items():
        assert plessi.classroom_to_plesso[v] == 2, (
            f"{k} -> {v} (plesso "
            f"{plessi.classroom_to_plesso[v]}) expected plesso 2")


def test_class_commuting_rule_keeps_class_in_one_plesso():
    """Class-kind commuting rule. Class 1A has Mate at h=8 (teacher
    Rossi) and Sci at h=9 (teacher Bianchi). The class moves between
    rooms. With a class-kind no-cross rule, both rooms must be in
    the same plesso."""
    import plessi_constraints as pc
    from classroom_assignment import solve_classroom_assignment

    lessons = [
        {"teacher": "Rossi", "co_teachers": [], "class": "1A",
         "subject": "Mate", "day": 1, "hour": 8},
        {"teacher": "Bianchi", "co_teachers": [], "class": "1A",
         "subject": "Sci", "day": 1, "hour": 9},
    ]
    plessi = _make_plessi(rules=[
        pc.CommutingRule(
            id=1, from_plesso_id=1, to_plesso_id=2,
            entity_kind="class", entity_id=None,
            min_gap_hours=1, symmetric=True),
    ])
    out, status = solve_classroom_assignment(
        lessons, _basic_rooms(),
        time_limit_s=5.0, workers=1, plessi_data=plessi)
    assert out is not None, status
    pl_a = plessi.classroom_to_plesso[out[("1A", "Mate", 1, 8)]]
    pl_b = plessi.classroom_to_plesso[out[("1A", "Sci", 1, 9)]]
    assert pl_a == pl_b, (
        f"class 1A crosses plessi: {pl_a} -> {pl_b}")


def test_class_single_plesso_total_pins_class_to_target():
    """Class-kind single_plesso_total: class 1A is pinned to plesso
    2 for the whole week."""
    import plessi_constraints as pc
    from classroom_assignment import solve_classroom_assignment

    lessons = [
        {"teacher": "Rossi", "co_teachers": [], "class": "1A",
         "subject": "Mate", "day": 1, "hour": 8},
        {"teacher": "Bianchi", "co_teachers": [], "class": "1A",
         "subject": "Sci", "day": 3, "hour": 11},
    ]
    plessi = _make_plessi(policies=[
        pc.EntityPolicy(
            id=1, entity_kind="class", entity_id=100,  # 1A
            policy="single_plesso_total", plesso_id=2),
    ])
    out, status = solve_classroom_assignment(
        lessons, _basic_rooms(),
        time_limit_s=5.0, workers=1, plessi_data=plessi)
    assert out is not None, status
    for k, v in out.items():
        assert plessi.classroom_to_plesso[v] == 2, (
            f"{k} -> {v} not in plesso 2")


def test_class_single_plesso_per_day_pins_day_to_one_plesso():
    """Class-kind single_plesso_per_day: same class on the same day
    must end up in one plesso even with hour gaps."""
    import plessi_constraints as pc
    from classroom_assignment import solve_classroom_assignment

    lessons = [
        {"teacher": "Rossi", "co_teachers": [], "class": "1A",
         "subject": "Mate", "day": 2, "hour": 8},
        {"teacher": "Bianchi", "co_teachers": [], "class": "1A",
         "subject": "Sci", "day": 2, "hour": 11},  # 3-hour gap
    ]
    plessi = _make_plessi(policies=[
        pc.EntityPolicy(
            id=1, entity_kind="class", entity_id=100,  # 1A
            policy="single_plesso_per_day"),
    ])
    out, status = solve_classroom_assignment(
        lessons, _basic_rooms(),
        time_limit_s=5.0, workers=1, plessi_data=plessi)
    assert out is not None, status
    pl_a = plessi.classroom_to_plesso[out[("1A", "Mate", 2, 8)]]
    pl_b = plessi.classroom_to_plesso[out[("1A", "Sci", 2, 11)]]
    assert pl_a == pl_b


def test_no_plessi_constraints_when_no_rules_no_policies():
    """When PlessiData has no rules and no policies, the solver
    behaves identically to plessi_data=None."""
    import plessi_constraints as pc
    from classroom_assignment import solve_classroom_assignment

    lessons = [
        {"teacher": "Rossi", "co_teachers": [], "class": "1A",
         "subject": "Mate", "day": 1, "hour": 8},
    ]
    plessi = pc.PlessiData(
        classroom_to_plesso={"A1": 1},
        teacher_name_to_id={"Rossi": 10},
    )
    out, status = solve_classroom_assignment(
        lessons,
        [{"name": "A1", "kind": "standard", "capacity": 30,
          "multi_class": False, "multi_class_max": 1}],
        time_limit_s=5.0, workers=1, plessi_data=plessi)
    assert out is not None, status
    assert out[("1A", "Mate", 1, 8)] == "A1"
