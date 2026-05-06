"""Smoke tests for the general DSL parser + evaluator.

Includes Giovanni's canonical "lab fisica" example as a regression
guard so future refactors of build_world / _apply_op don't break it.
"""
from __future__ import annotations

from backend.utils import general_dsl as G


# ============================================================
# Parser
# ============================================================


def test_parse_minimal_forall():
    tree = G.parse("forall l in lessons: l.hour < 14")
    assert tree.kind == "QUANT"
    assert tree.quant == "forall"


def test_parse_count_with_op():
    tree = G.parse("count l in lessons where l.day == 1: l <= 5")
    assert tree.kind == "COUNT"
    assert tree.op == "<="


def test_parse_class_name_with_digit_prefix():
    """1A, 3B_scientifico must tokenize as IDENT (single token)."""
    tree = G.parse("forall l in lessons where l.class == 1A: l.hour != 6")
    assert tree.kind == "QUANT"


def test_parse_implies_and_iff():
    G.parse("(exists l in lessons: l.teacher == X) => "
            "(exists l in lessons: l.teacher == Y)")
    G.parse("a == 1 <=> b == 2")


# ============================================================
# Evaluator
# ============================================================


def _world(teachers, lessons, **kw):
    base = {
        "teachers": teachers, "lessons": lessons,
        "classes": [], "classrooms": [], "subjects": [],
        "curricula": [], "groups": [], "assignments": [],
        "days": [{"index": d} for d in range(1, 7)],
        "hours": [{"index": h} for h in range(8, 14)],
        "slots": [{"day": d, "hour": h}
                  for d in range(1, 7) for h in range(8, 14)],
    }
    base.update(kw)
    return base


def test_eval_simple_forall_true():
    tree = G.parse("forall l in lessons: l.hour < 14")
    world = _world([], [
        {"teacher": "T", "hour": 8, "day": 1, "class": "1A",
         "subject": "Mat", "classroom": "A1", "classroom_type": ""},
    ])
    assert G.evaluate(tree, world) is True


def test_eval_count_le():
    tree = G.parse("count l in lessons where l.day == 1: l <= 2")
    world = _world([], [
        {"teacher": "T", "hour": 8, "day": 1, "class": "1A",
         "subject": "Mat", "classroom": "", "classroom_type": ""},
        {"teacher": "T", "hour": 9, "day": 1, "class": "1A",
         "subject": "Mat", "classroom": "", "classroom_type": ""},
    ])
    assert G.evaluate(tree, world) is True


def test_eval_giovanni_lab_fisica():
    """forall t in teachers where t.subject == 'Fisica':
        count l in lessons where l.teacher == t
                              and l.classroom.type == 'lab_fisica': l == 1
    """
    expr = (
        'forall t in teachers where t.subject == "Fisica":\n'
        '    count l in lessons where l.teacher == t '
        'and l.classroom.type == "lab_fisica": l == 1'
    )
    tree = G.parse(expr)
    # Case 1: each Fisica teacher has exactly 1 lab_fisica lesson -> SAT
    world = _world(
        [
            {"name": "Rossi", "subject": ["Fisica"], "subjects": ["Fisica"]},
            {"name": "Bianchi", "subject": ["Mat"], "subjects": ["Mat"]},
        ],
        [
            {"teacher": "Rossi", "classroom": "LabFis",
             "classroom_type": "lab_fisica", "day": 1, "hour": 8,
             "class": "1A", "subject": "Fisica"},
            {"teacher": "Rossi", "classroom": "A1",
             "classroom_type": "standard", "day": 2, "hour": 9,
             "class": "1A", "subject": "Fisica"},
        ],
    )
    assert G.evaluate(tree, world) is True

    # Case 2: Rossi has zero lab_fisica lessons -> UNSAT
    world2 = _world(
        [{"name": "Rossi", "subject": ["Fisica"], "subjects": ["Fisica"]}],
        [{"teacher": "Rossi", "classroom": "A1",
          "classroom_type": "standard", "day": 1, "hour": 8,
          "class": "1A", "subject": "Fisica"}],
    )
    assert G.evaluate(tree, world2) is False

    # Case 3: Rossi has TWO lab_fisica lessons -> UNSAT (count must be 1)
    world3 = _world(
        [{"name": "Rossi", "subject": ["Fisica"], "subjects": ["Fisica"]}],
        [
            {"teacher": "Rossi", "classroom": "LabFis",
             "classroom_type": "lab_fisica", "day": 1, "hour": 8,
             "class": "1A", "subject": "Fisica"},
            {"teacher": "Rossi", "classroom": "LabFis",
             "classroom_type": "lab_fisica", "day": 2, "hour": 9,
             "class": "2A", "subject": "Fisica"},
        ],
    )
    assert G.evaluate(tree, world3) is False


def test_parse_classroom_plesso_path():
    """l.classroom.plesso parses as a 3-step Ref path."""
    tree = G.parse(
        'forall l in lessons where l.classroom.plesso == 1: true')
    assert tree.kind == "QUANT"


def test_eval_classroom_plesso_predicate_via_world_alias():
    """``l.classroom.plesso`` resolves via the ``classroom_plesso``
    pre-resolved field on the lesson dict (the same two-step chain
    shortcut that ``l.classroom.type`` uses). Required for the
    post-hoc evaluator to consume plesso commuting DSL clauses on
    a finalised solution."""
    tree = G.parse(
        'forall l in lessons where l.classroom.plesso == 1: '
        'l.hour < 14')
    world = _world([], [
        {"teacher": "T", "hour": 8, "day": 1, "class": "1A",
         "subject": "Mat", "classroom": "A1", "classroom_type": "",
         "classroom_plesso": 1},
        {"teacher": "T", "hour": 9, "day": 1, "class": "1A",
         "subject": "Mat", "classroom": "B1", "classroom_type": "",
         "classroom_plesso": 2},
    ])
    assert G.evaluate(tree, world) is True
    # And the negative: false body on the matched plesso must yield
    # False if any plesso=1 lesson exists, True if none do.
    tree2 = G.parse(
        'forall l in lessons where l.classroom.plesso == 1: false')
    assert G.evaluate(tree2, world) is False
    world_no_p1 = _world([], [
        {"teacher": "T", "hour": 9, "day": 1, "class": "1A",
         "subject": "Mat", "classroom": "B1", "classroom_type": "",
         "classroom_plesso": 2},
    ])
    assert G.evaluate(tree2, world_no_p1) is True


def test_eval_implies():
    tree = G.parse("(exists l in lessons: l.teacher == X)"
                   " => (exists l in lessons: l.teacher == Y)")
    # antecedent false -> implication vacuously true
    world = _world([], [
        {"teacher": "Z", "day": 1, "hour": 8, "class": "1A",
         "subject": "M", "classroom": "", "classroom_type": ""},
    ])
    assert G.evaluate(tree, world) is True
    # antecedent true, consequent false -> false
    world2 = _world([], [
        {"teacher": "X", "day": 1, "hour": 8, "class": "1A",
         "subject": "M", "classroom": "", "classroom_type": ""},
    ])
    assert G.evaluate(tree, world2) is False


def test_eval_subject_list_shorthand():
    """t.subject == 'X' should be 'X' in t.subject (which is a list)."""
    tree = G.parse('forall t in teachers where t.subject == "Fisica": true')
    world = _world(
        [
            {"name": "A", "subject": ["Fisica", "Mat"], "subjects": ["Fisica", "Mat"]},
            {"name": "B", "subject": [], "subjects": []},
        ],
        [],
    )
    # The body is just `true`, so the forall reduces to "iterate the
    # filtered set". Both teachers are checked; only A passes the
    # where clause. Body is true for A. Result: True.
    assert G.evaluate(tree, world) is True


# ============================================================
# Validation
# ============================================================


def test_validate_unknown_source():
    import pytest
    with pytest.raises(G.DSLError):
        G.parse("forall x in flying_pigs: true")


def test_validate_atom_explosion_guard():
    # Single forall with the largest source (slots = 36) and a
    # shallow body should NOT trigger the atom-explosion guard.
    tree = G.parse("forall s in slots: s.day <= 6")
    res = G.validate(tree)
    assert res.ok
