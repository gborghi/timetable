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


# ============================================================
# consecutive_days predicate
# ============================================================


def test_consecutive_days_int_args():
    """consecutive_days(d1, d2) = True iff |d1 - d2| == 1, no wrap."""
    def _ev(d1, d2):
        return G.evaluate(
            G.parse(f"consecutive_days({d1}, {d2})"), _world([], []))
    # Adjacent
    assert _ev(1, 2) is True
    assert _ev(2, 1) is True
    assert _ev(3, 4) is True
    assert _ev(5, 6) is True
    # Non-adjacent
    assert _ev(1, 3) is False
    assert _ev(1, 1) is False     # same day != consecutive
    # No wrap-around: 6 (sab) is NOT adjacent to 1 (lun)
    assert _ev(6, 1) is False
    assert _ev(1, 6) is False


def test_consecutive_days_via_lesson_refs():
    """Inside a forall over lessons, l1.day extracts the int day; the
    predicate then compares the two lessons' day indices. This is the
    Rossi case (a) pattern: 'no two lessons of the same cattedra on
    consecutive days'."""
    expr = (
        "forall l1 in lessons where l1.teacher == Rossi:\n"
        "  forall l2 in lessons where l2.teacher == Rossi:\n"
        "    not consecutive_days(l1.day, l2.day)"
    )
    tree = G.parse(expr)
    # Days 1, 3, 5 -> all gaps >= 2 -> ok
    w_ok = _world([], [
        {"teacher": "Rossi", "day": 1, "hour": 8, "class": "3A",
         "subject": "Fisica", "classroom": "", "classroom_type": ""},
        {"teacher": "Rossi", "day": 3, "hour": 9, "class": "3A",
         "subject": "Fisica", "classroom": "", "classroom_type": ""},
        {"teacher": "Rossi", "day": 5, "hour": 10, "class": "3A",
         "subject": "Fisica", "classroom": "", "classroom_type": ""},
    ])
    assert G.evaluate(tree, w_ok) is True
    # Days 1, 2, 5 -> 1-2 are consecutive -> violation
    w_bad = _world([], [
        {"teacher": "Rossi", "day": 1, "hour": 8, "class": "3A",
         "subject": "Fisica", "classroom": "", "classroom_type": ""},
        {"teacher": "Rossi", "day": 2, "hour": 9, "class": "3A",
         "subject": "Fisica", "classroom": "", "classroom_type": ""},
        {"teacher": "Rossi", "day": 5, "hour": 10, "class": "3A",
         "subject": "Fisica", "classroom": "", "classroom_type": ""},
    ])
    assert G.evaluate(tree, w_bad) is False


def test_consecutive_days_arity_check():
    """Wrong arity raises a clear DSLError."""
    import pytest
    tree = G.parse("consecutive_days(1)")
    with pytest.raises(G.DSLError):
        G.evaluate(tree, _world([], []))


# ============================================================
# Arithmetic (+, -)
# ============================================================


def test_parse_arith_literal_sum():
    """8 + 2 parses as Arith(+, Lit(8), Lit(2))."""
    tree = G.parse("count l in lessons where l.hour == 8 + 2: l <= 10")
    assert tree.kind == "COUNT"
    cmp_node = tree.where
    assert cmp_node.kind == "CMP"
    rhs = cmp_node.right
    assert rhs.kind == "ARITH"
    assert rhs.op == "+"
    assert rhs.left.value == 8
    assert rhs.right.value == 2


def test_eval_arith_in_count_filter():
    """count l where l.hour == 8 + 2 -> matches lessons at h=10."""
    tree = G.parse(
        "count l in lessons where l.hour == 8 + 2: l <= 10")
    world = _world([], [
        {"teacher": "T", "hour": 9, "day": 1, "class": "1A",
         "subject": "M", "classroom": "", "classroom_type": ""},
        {"teacher": "T", "hour": 10, "day": 1, "class": "1A",
         "subject": "M", "classroom": "", "classroom_type": ""},
        {"teacher": "T", "hour": 10, "day": 2, "class": "1A",
         "subject": "M", "classroom": "", "classroom_type": ""},
    ])
    # 2 lessons match h == 10; count <= 10 is True.
    assert G.evaluate(tree, world) is True


def test_eval_arith_with_ref_d_index_plus_1():
    """`d.index + 1` in a forall body resolves at evaluation time
    against the bound day variable. Used in 'next-day' kinds of
    rules."""
    tree = G.parse(
        "forall d in days: count l in lessons where "
        "l.day == d.index + 1: l >= 0")
    world = _world([], [
        {"teacher": "T", "hour": 8, "day": 2, "class": "1A",
         "subject": "M", "classroom": "", "classroom_type": ""},
    ])
    # All days have count >= 0; trivially True.
    assert G.evaluate(tree, world) is True


def test_eval_arith_subtraction():
    """h - 2 evaluates and works in a comparison."""
    tree = G.parse("count l in lessons where l.hour == 12 - 2: l == 1")
    world = _world([], [
        {"teacher": "T", "hour": 10, "day": 1, "class": "1A",
         "subject": "M", "classroom": "", "classroom_type": ""},
    ])
    assert G.evaluate(tree, world) is True


def test_eval_arith_unary_minus():
    """`-5` parses as Arith(-, Lit(0), Lit(5)) and evaluates to -5."""
    tree = G.parse("count l in lessons: l >= -5")
    world = _world([], [])
    assert G.evaluate(tree, world) is True


def test_eval_arith_chained_left_associative():
    """10 - 3 - 2 == 5 (left-associative)."""
    tree = G.parse("count l in lessons where l.hour == 10 - 3 - 2: l <= 0")
    world = _world([], [
        {"teacher": "T", "hour": 5, "day": 1, "class": "1A",
         "subject": "M", "classroom": "", "classroom_type": ""},
    ])
    # 10 - 3 - 2 = 5; the lesson at h=5 matches; count == 1, but
    # the count constraint is `<= 0` which fails -> evaluator returns
    # False. This proves the arithmetic was evaluated to 5.
    assert G.evaluate(tree, world) is False


def test_eval_arith_string_operand_raises():
    """1 + "x" raises a clear DSLError, no silent string concat."""
    import pytest
    tree = G.parse('count l in lessons: l == 1 + "x"')
    world = _world([], [])
    with pytest.raises(G.DSLError) as ei:
        G.evaluate(tree, world)
    assert "numerici" in str(ei.value).lower() or "numeric" in str(ei.value).lower()


def test_eval_arith_parenthesised():
    """Parens around an arithmetic value work at value level."""
    tree = G.parse("count l in lessons where l.hour == (8 + 2): l <= 10")
    world = _world([], [
        {"teacher": "T", "hour": 10, "day": 1, "class": "1A",
         "subject": "M", "classroom": "", "classroom_type": ""},
    ])
    assert G.evaluate(tree, world) is True


def test_arith_static_evaluator_compile_time():
    """Compile-time evaluator: 8 + 2 evaluates without running the
    solver, so the compiler can fold static-arith filters into
    forbid/permit decisions.

    Note: imports the parser via the same module path that
    dsl_to_cpsat uses (``webui.backend.utils.general_dsl``) so the
    Arith / Lit dataclasses have the same identity for the
    isinstance checks inside _eval_static.
    """
    import sys, os
    HERE = os.path.dirname(os.path.abspath(__file__))
    ENGINE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "engine"))
    if ENGINE not in sys.path:
        sys.path.insert(0, ENGINE)
    import dsl_to_cpsat as dtc
    from webui.backend.utils import general_dsl as gd
    tree = gd.parse("8 + 2")
    assert dtc._eval_static(tree, {}, {}) == 10
    tree2 = gd.parse("12 - 3 - 4")
    assert dtc._eval_static(tree2, {}, {}) == 5
    # Static arith with a string operand raises.
    import pytest
    tree3 = gd.parse('1 + "x"')
    with pytest.raises(ValueError):
        dtc._eval_static(tree3, {}, {})
