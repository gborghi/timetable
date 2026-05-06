"""Unit tests for engine.plessi_constraints.check_solution_against_plessi.

The diagnostic helper inspects a finalised solution dict and returns
a list of violation entries -- used by the monitor UI and as a smoke
check for solutions produced by pipelines that do not yet wire the
plessi constraints into their CP-SAT models.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "engine"))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)


def _data():
    """Two plessi (1, 2), four rooms, two teachers, two classes."""
    import plessi_constraints as pc
    d = pc.PlessiData(
        classroom_to_plesso={"A1": 1, "A2": 1, "B1": 2, "B2": 2},
        teacher_name_to_id={"Rossi": 10, "Bianchi": 11},
        class_name_to_id={"1A": 100, "1B": 101},
    )
    return pc, d


def test_check_empty_solution_returns_no_violations():
    pc, d = _data()
    assert pc.check_solution_against_plessi({}, d) == []


def test_check_solution_with_no_rules_returns_no_violations():
    pc, d = _data()
    sol = {
        ("Rossi", "1A", "Mate", 1, 8): "A1",
        ("Rossi", "1B", "Mate", 1, 9): "B1",  # crosses plessi
    }
    assert pc.check_solution_against_plessi(sol, d) == []


def test_check_unknown_classroom_is_flagged():
    pc, d = _data()
    sol = {("Rossi", "1A", "Mate", 1, 8): "GHOST"}
    out = pc.check_solution_against_plessi(sol, d)
    assert len(out) == 1
    assert out[0]["kind"] == "unknown_classroom"
    assert out[0]["classroom"] == "GHOST"


def test_check_teacher_commuting_rule_violation_detected():
    pc, d = _data()
    d.commuting_rules = [pc.CommutingRule(
        id=1, from_plesso_id=1, to_plesso_id=2,
        entity_kind="teacher", entity_id=None,
        min_gap_hours=1, symmetric=True)]
    sol = {
        ("Rossi", "1A", "Mate", 1, 8): "A1",
        ("Rossi", "1B", "Mate", 1, 9): "B1",  # adjacent crossing
    }
    out = pc.check_solution_against_plessi(sol, d)
    assert len(out) == 1
    v = out[0]
    assert v["kind"] == "commuting"
    assert v["entity_kind"] == "teacher"
    assert v["entity_name"] == "Rossi"
    assert v["plesso_a"] == 1 and v["plesso_b"] == 2


def test_check_teacher_commuting_satisfied_when_gap_large_enough():
    pc, d = _data()
    d.commuting_rules = [pc.CommutingRule(
        id=1, from_plesso_id=1, to_plesso_id=2,
        entity_kind="teacher", entity_id=None,
        min_gap_hours=1, symmetric=True)]
    sol = {
        ("Rossi", "1A", "Mate", 1, 8): "A1",
        ("Rossi", "1B", "Mate", 1, 10): "B1",  # gap = 1 hour empty
    }
    assert pc.check_solution_against_plessi(sol, d) == []


def test_check_class_commuting_rule_violation_detected():
    pc, d = _data()
    d.commuting_rules = [pc.CommutingRule(
        id=2, from_plesso_id=1, to_plesso_id=2,
        entity_kind="class", entity_id=None,
        min_gap_hours=1, symmetric=True)]
    sol = {
        ("Rossi", "1A", "Mate", 2, 9): "A1",
        ("Bianchi", "1A", "Ita", 2, 10): "B1",  # 1A crosses
    }
    out = pc.check_solution_against_plessi(sol, d)
    assert any(v["kind"] == "commuting"
               and v["entity_kind"] == "class"
               and v["entity_name"] == "1A"
               for v in out)


def test_check_single_plesso_total_violation_detected():
    pc, d = _data()
    d.entity_policies = [pc.EntityPolicy(
        id=3, entity_kind="teacher", entity_id=10,  # Rossi
        policy="single_plesso_total", plesso_id=2)]
    sol = {
        ("Rossi", "1A", "Mate", 1, 8): "A1",  # plesso 1 -- BAD
        ("Rossi", "1B", "Mate", 3, 11): "B1",  # plesso 2 -- OK
    }
    out = pc.check_solution_against_plessi(sol, d)
    assert any(v["kind"] == "single_total"
               and v["entity_name"] == "Rossi"
               and v["n_slots_in_wrong_plesso"] == 1
               for v in out)


def test_check_single_plesso_per_day_violation_detected():
    pc, d = _data()
    d.entity_policies = [pc.EntityPolicy(
        id=4, entity_kind="class", entity_id=101,  # 1B
        policy="single_plesso_per_day")]
    sol = {
        ("Rossi", "1B", "Mate", 2, 8): "A1",   # day 2, plesso 1
        ("Bianchi", "1B", "Sci", 2, 11): "B1",  # day 2, plesso 2 -- BAD
        ("Rossi", "1B", "Mate", 3, 8): "A1",   # day 3, single ok
    }
    out = pc.check_solution_against_plessi(sol, d)
    days_with_violation = {
        v["day"] for v in out
        if v["kind"] == "single_per_day"
        and v["entity_name"] == "1B"
    }
    assert 2 in days_with_violation
    assert 3 not in days_with_violation


def test_check_clean_solution_has_no_violations():
    """Realistic sanity: a fully-conformant solution returns []."""
    pc, d = _data()
    d.commuting_rules = [pc.CommutingRule(
        id=5, from_plesso_id=1, to_plesso_id=2,
        entity_kind="teacher", entity_id=None,
        min_gap_hours=1, symmetric=True)]
    d.entity_policies = [pc.EntityPolicy(
        id=6, entity_kind="teacher", entity_id=10,
        policy="single_plesso_per_day")]
    sol = {
        ("Rossi", "1A", "Mate", 1, 8): "A1",
        ("Rossi", "1B", "Mate", 1, 9): "A2",  # same plesso, all good
        ("Rossi", "1A", "Mate", 2, 11): "B1",  # different day
    }
    assert pc.check_solution_against_plessi(sol, d) == []
