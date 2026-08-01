"""Finding 15: inter-plesso commuting rules must also apply to classes and
groups (a class that moves to the gym in the other site), not only teachers.
"""
import general_dsl as gd
from dsl_translator import plesso_commuting_rule_to_dsl
from plessi_constraints import CommutingRule


def _rule(kind, entity_id=None):
    return CommutingRule(
        id=1, from_plesso_id=1, to_plesso_id=2,
        entity_kind=kind, entity_id=entity_id,
        min_gap_hours=1, allowed_break_only=False,
        break_start_hour=None, break_end_hour=None,
        symmetric=True, priority=0)


def test_class_commuting_kind_wide():
    clauses = plesso_commuting_rule_to_dsl(_rule("class"))
    assert len(clauses) == 2   # symmetric
    for c in clauses:
        gd.parse(c)            # parseable
        assert "l2.class == l1.class" in c
        assert "l1.teacher" not in c


def test_class_commuting_per_entity_binds_name():
    clauses = plesso_commuting_rule_to_dsl(
        _rule("class", entity_id=7), entity_name="1L")
    assert clauses and all('l1.class == "1L"' in c for c in clauses)


def test_group_commuting_binds_group_attr():
    clauses = plesso_commuting_rule_to_dsl(_rule("group"))
    for c in clauses:
        gd.parse(c)
        assert "l2.group == l1.group" in c


def test_unknown_entity_kind_still_raises():
    import pytest
    with pytest.raises(NotImplementedError):
        plesso_commuting_rule_to_dsl(_rule("student"))
