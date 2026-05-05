"""Unit tests for the engine helper engine/plessi_constraints.py
(P3 foundation).

Verifies rule resolution + the CP-SAT integration on a tiny
hand-built model.
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "engine"))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)


# ---------- Rule resolution tests ----------

def _make_data(rules, policies=None):
    import plessi_constraints as pc
    data = pc.PlessiData(
        classroom_to_plesso={"A1": 1, "A2": 1, "B1": 2, "B2": 2},
        teacher_name_to_id={"Rossi": 10, "Bianchi": 11},
        class_name_to_id={"1A": 100, "1B": 101},
    )
    data.commuting_rules = list(rules)
    data.entity_policies = list(policies or [])
    return data


def test_resolve_commuting_rule_picks_specific_over_generic():
    import plessi_constraints as pc
    data = _make_data([
        pc.CommutingRule(
            id=1, from_plesso_id=1, to_plesso_id=2,
            entity_kind="teacher", entity_id=None,
            min_gap_hours=0),
        pc.CommutingRule(
            id=2, from_plesso_id=1, to_plesso_id=2,
            entity_kind="teacher", entity_id=10,
            min_gap_hours=2),
    ])
    rule = pc.resolve_commuting_rule(data, 1, 2, "teacher", 10)
    assert rule.id == 2  # per-entity overrides kind-wide


def test_resolve_commuting_rule_kindwide_when_no_specific():
    import plessi_constraints as pc
    data = _make_data([
        pc.CommutingRule(
            id=1, from_plesso_id=1, to_plesso_id=2,
            entity_kind="teacher", entity_id=None,
            min_gap_hours=1),
    ])
    rule = pc.resolve_commuting_rule(data, 1, 2, "teacher", 10)
    assert rule.id == 1


def test_resolve_commuting_rule_symmetric_match():
    """A symmetric rule (default) for (1, 2) also applies to
    (2, 1)."""
    import plessi_constraints as pc
    data = _make_data([
        pc.CommutingRule(
            id=1, from_plesso_id=1, to_plesso_id=2,
            entity_kind="teacher", entity_id=None,
            min_gap_hours=1, symmetric=True),
    ])
    rule = pc.resolve_commuting_rule(data, 2, 1, "teacher", 10)
    assert rule is not None and rule.id == 1


def test_resolve_commuting_rule_returns_none_when_no_match():
    import plessi_constraints as pc
    data = _make_data([
        pc.CommutingRule(
            id=1, from_plesso_id=1, to_plesso_id=2,
            entity_kind="class", entity_id=None,
            min_gap_hours=0),
    ])
    # Wrong kind:
    rule = pc.resolve_commuting_rule(data, 1, 2, "teacher", 10)
    assert rule is None


def test_resolve_entity_policy_specific_beats_kindwide():
    import plessi_constraints as pc
    data = _make_data([], [
        pc.EntityPolicy(
            id=1, entity_kind="teacher", entity_id=None,
            policy="any"),
        pc.EntityPolicy(
            id=2, entity_kind="teacher", entity_id=10,
            policy="single_plesso_per_day"),
    ])
    pol = pc.resolve_entity_policy(data, "teacher", 10)
    assert pol.id == 2


def test_adjacent_violates_rule_min_gap():
    import plessi_constraints as pc
    rule = pc.CommutingRule(
        id=1, from_plesso_id=1, to_plesso_id=2,
        entity_kind="teacher", entity_id=None,
        min_gap_hours=1)
    assert pc._adjacent_violates_rule(rule, 8, 9) is True


def test_adjacent_violates_rule_break_only_outside():
    import plessi_constraints as pc
    rule = pc.CommutingRule(
        id=1, from_plesso_id=1, to_plesso_id=2,
        entity_kind="teacher", entity_id=None,
        min_gap_hours=0, allowed_break_only=True,
        break_start_hour=10, break_end_hour=11)
    # (8, 9) is NOT the break -> violates
    assert pc._adjacent_violates_rule(rule, 8, 9) is True


def test_adjacent_violates_rule_break_only_at_break():
    import plessi_constraints as pc
    rule = pc.CommutingRule(
        id=1, from_plesso_id=1, to_plesso_id=2,
        entity_kind="teacher", entity_id=None,
        min_gap_hours=0, allowed_break_only=True,
        break_start_hour=10, break_end_hour=11)
    # (10, 11) IS the break -> allowed
    assert pc._adjacent_violates_rule(rule, 10, 11) is False


def test_adjacent_violates_rule_no_constraint():
    import plessi_constraints as pc
    rule = pc.CommutingRule(
        id=1, from_plesso_id=1, to_plesso_id=2,
        entity_kind="teacher", entity_id=None,
        min_gap_hours=0, allowed_break_only=False)
    assert pc._adjacent_violates_rule(rule, 8, 9) is False


# ---------- CP-SAT integration tests ----------

def test_add_plesso_commuting_constraints_for_teacher_blocks_pair():
    """A teacher cannot have a class in plesso 1 at h=8 and another
    class in plesso 2 at h=9 if the rule requires min_gap_hours=1.
    The CP-SAT model with that constraint must prove infeasible if
    we force both slots to 1."""
    from ortools.sat.python import cp_model
    import plessi_constraints as pc

    data = pc.PlessiData(
        classroom_to_plesso={"R_central": 1, "R_succ": 2},
        teacher_name_to_id={"Rossi": 10},
        class_name_to_id={"1A": 100, "1B": 101},
    )
    data.commuting_rules = [
        pc.CommutingRule(
            id=1, from_plesso_id=1, to_plesso_id=2,
            entity_kind="teacher", entity_id=None,
            min_gap_hours=1, symmetric=True),
    ]

    model = cp_model.CpModel()
    sa = model.NewBoolVar("sa")
    sb = model.NewBoolVar("sb")
    slot = {
        ("Rossi", "1A", "Mat", 1, 8): sa,
        ("Rossi", "1B", "Mat", 1, 9): sb,
    }
    classroom_for_slot = {
        ("1A", 1, 8): "R_central",
        ("1B", 1, 9): "R_succ",
    }
    pc.add_plesso_commuting_constraints_for_teacher(
        model, slot, data, "Rossi",
        days=[1], hours=[8, 9],
        classroom_for_slot=classroom_for_slot,
    )
    # Force both: must be UNSAT.
    model.Add(sa == 1)
    model.Add(sb == 1)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 1.0
    status = solver.Solve(model)
    assert status == cp_model.INFEASIBLE


def test_add_plesso_commuting_constraints_allows_same_plesso():
    """No constraint added when both slots are in the same plesso."""
    from ortools.sat.python import cp_model
    import plessi_constraints as pc

    data = pc.PlessiData(
        classroom_to_plesso={"R1": 1, "R2": 1},  # same plesso
        teacher_name_to_id={"Rossi": 10},
    )
    data.commuting_rules = [
        pc.CommutingRule(
            id=1, from_plesso_id=1, to_plesso_id=2,
            entity_kind="teacher", entity_id=None,
            min_gap_hours=1, symmetric=True),
    ]

    model = cp_model.CpModel()
    sa = model.NewBoolVar("sa")
    sb = model.NewBoolVar("sb")
    slot = {
        ("Rossi", "1A", "Mat", 1, 8): sa,
        ("Rossi", "1B", "Mat", 1, 9): sb,
    }
    pc.add_plesso_commuting_constraints_for_teacher(
        model, slot, data, "Rossi",
        days=[1], hours=[8, 9],
        classroom_for_slot={("1A", 1, 8): "R1",
                              ("1B", 1, 9): "R2"},
    )
    model.Add(sa == 1)
    model.Add(sb == 1)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 1.0
    status = solver.Solve(model)
    # Same plesso means no plesso constraint -> still feasible.
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_add_plesso_commuting_constraints_no_rule_no_constraint():
    """If no rule applies, no constraint is added."""
    from ortools.sat.python import cp_model
    import plessi_constraints as pc

    data = pc.PlessiData(
        classroom_to_plesso={"R_central": 1, "R_succ": 2},
        teacher_name_to_id={"Rossi": 10},
    )
    # No rules at all.
    data.commuting_rules = []

    model = cp_model.CpModel()
    sa = model.NewBoolVar("sa")
    sb = model.NewBoolVar("sb")
    slot = {
        ("Rossi", "1A", "Mat", 1, 8): sa,
        ("Rossi", "1B", "Mat", 1, 9): sb,
    }
    pc.add_plesso_commuting_constraints_for_teacher(
        model, slot, data, "Rossi",
        days=[1], hours=[8, 9],
        classroom_for_slot={("1A", 1, 8): "R_central",
                              ("1B", 1, 9): "R_succ"},
    )
    model.Add(sa == 1)
    model.Add(sb == 1)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 1.0
    status = solver.Solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_load_plessi_data_from_db(app_with_temp_db):
    """The DB-side loader builds a PlessiData snapshot consistent
    with the ORM rows."""
    import plessi_constraints as pc
    from backend import models
    _app, TestSession = app_with_temp_db
    with TestSession() as db:
        p1 = models.Plesso(name="C", code="C")
        p2 = models.Plesso(name="S", code="S")
        db.add_all([p1, p2])
        db.commit()
        p1_id, p2_id = p1.id, p2.id
        cl1 = models.Classroom(
            name="A1", plesso_id=p1_id, kind="standard")
        cl2 = models.Classroom(
            name="B1", plesso_id=p2_id, kind="standard")
        db.add_all([cl1, cl2])
        db.commit()
        t = models.Teacher(name="Rossi")
        sc = models.SchoolClass(name="1A")
        db.add_all([t, sc])
        db.commit()
        t_id, sc_id = t.id, sc.id
        rule = models.PlessoCommutingRule(
            from_plesso_id=p1_id, to_plesso_id=p2_id,
            entity_kind="teacher", entity_id=None,
            min_gap_hours=1)
        pol = models.PlessoEntityPolicy(
            entity_kind="teacher", entity_id=t_id,
            policy="single_plesso_per_day")
        db.add_all([rule, pol])
        db.commit()

        data = pc.load_plessi_data(db)

    assert data.classroom_to_plesso["A1"] == p1_id
    assert data.classroom_to_plesso["B1"] == p2_id
    assert data.teacher_name_to_id["Rossi"] == t_id
    assert data.class_name_to_id["1A"] == sc_id
    assert len(data.commuting_rules) == 1
    assert data.commuting_rules[0].min_gap_hours == 1
    assert len(data.entity_policies) == 1
    assert data.entity_policies[0].policy == "single_plesso_per_day"
