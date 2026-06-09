"""Task 4: the convenience pragma ``no_same_class_consecutive_days(cl)``.

Semantics: for the given class, no two of its lessons fall on
consecutive days. Equivalent verbose form:

    forall l1 in lessons where l1.class == CL:
      forall l2 in lessons where l2.class == CL:
        not consecutive_days(l1.day, l2.day)

Covers BOTH the post-hoc evaluator (general_dsl) and the CP-SAT
compiler (dsl_to_cpsat forbid-pair path).
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "engine"))
WEBUI = os.path.normpath(os.path.join(HERE, "..", ".."))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
for p in (ENGINE, WEBUI, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from backend.utils import general_dsl as G  # noqa: E402


def _world(lessons, **kw):
    base = {
        "teachers": [], "lessons": lessons,
        "classes": [], "classrooms": [], "subjects": [],
        "curricula": [], "groups": [], "assignments": [],
        "days": [{"index": d} for d in range(1, 7)],
        "hours": [{"index": h} for h in range(8, 14)],
        "slots": [{"day": d, "hour": h}
                  for d in range(1, 7) for h in range(8, 14)],
    }
    base.update(kw)
    return base


# ============================================================
# Post-hoc evaluator
# ============================================================


def test_eval_consecutive_days_violation():
    """1A lessons on days 1 and 2 (consecutive) -> VIOLATION."""
    tree = G.parse('no_same_class_consecutive_days("1A")')
    w_bad = _world([
        {"teacher": "Rossi", "day": 1, "hour": 8, "class": "1A",
         "subject": "Fisica", "classroom": "", "classroom_type": ""},
        {"teacher": "Rossi", "day": 2, "hour": 9, "class": "1A",
         "subject": "Fisica", "classroom": "", "classroom_type": ""},
    ])
    assert G.evaluate(tree, w_bad) is False
    ok, err = G.evaluate_safe(tree, w_bad)
    assert err is None
    assert ok is False


def test_eval_non_consecutive_ok():
    """1A lessons on days 1 and 3 (not consecutive) -> satisfied."""
    tree = G.parse('no_same_class_consecutive_days("1A")')
    w_ok = _world([
        {"teacher": "Rossi", "day": 1, "hour": 8, "class": "1A",
         "subject": "Fisica", "classroom": "", "classroom_type": ""},
        {"teacher": "Rossi", "day": 3, "hour": 9, "class": "1A",
         "subject": "Fisica", "classroom": "", "classroom_type": ""},
    ])
    assert G.evaluate(tree, w_ok) is True
    ok, err = G.evaluate_safe(tree, w_ok)
    assert err is None
    assert ok is True


def test_eval_other_class_unaffected():
    """A consecutive-day pair in 2B does not violate the 1A rule."""
    tree = G.parse('no_same_class_consecutive_days("1A")')
    w = _world([
        {"teacher": "Rossi", "day": 1, "hour": 8, "class": "2B",
         "subject": "Fisica", "classroom": "", "classroom_type": ""},
        {"teacher": "Rossi", "day": 2, "hour": 9, "class": "2B",
         "subject": "Fisica", "classroom": "", "classroom_type": ""},
        {"teacher": "Rossi", "day": 1, "hour": 8, "class": "1A",
         "subject": "Fisica", "classroom": "", "classroom_type": ""},
    ])
    assert G.evaluate(tree, w) is True


# ============================================================
# CP-SAT compiler
# ============================================================


def test_compile_forbids_consecutive_day_pair():
    """The compiler must FORBID having a 1A lesson on day 1 AND a 1A
    lesson on day 2 simultaneously. Pin both to 1 -> INFEASIBLE."""
    from ortools.sat.python import cp_model
    from dsl_to_cpsat import DSLConstraintCompiler

    model = cp_model.CpModel()
    # 1A lessons on day 1 (hour 8) and day 2 (hour 8); plus a day-3
    # slot that should remain co-selectable with day 1.
    slot = {
        ("T1", "1A", "Mat", 1, 8): model.NewBoolVar("d1"),
        ("T1", "1A", "Mat", 2, 8): model.NewBoolVar("d2"),
        ("T1", "1A", "Mat", 3, 8): model.NewBoolVar("d3"),
    }
    comp = DSLConstraintCompiler(model, slot)
    comp.compile('no_same_class_consecutive_days("1A")')

    # Day 1 + Day 2 (consecutive) must be infeasible together.
    m1 = model.Clone()
    m1.Add(slot[("T1", "1A", "Mat", 1, 8)] == 1)
    m1.Add(slot[("T1", "1A", "Mat", 2, 8)] == 1)
    s1 = cp_model.CpSolver()
    st1 = s1.Solve(m1)
    assert st1 == cp_model.INFEASIBLE

    # Day 1 + Day 3 (gap >= 2) must remain feasible together.
    m2 = model.Clone()
    m2.Add(slot[("T1", "1A", "Mat", 1, 8)] == 1)
    m2.Add(slot[("T1", "1A", "Mat", 3, 8)] == 1)
    s2 = cp_model.CpSolver()
    st2 = s2.Solve(m2)
    assert st2 in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_compile_other_class_not_constrained():
    """A different class (2B) on consecutive days stays feasible."""
    from ortools.sat.python import cp_model
    from dsl_to_cpsat import DSLConstraintCompiler

    model = cp_model.CpModel()
    slot = {
        ("T1", "2B", "Mat", 1, 8): model.NewBoolVar("b1"),
        ("T1", "2B", "Mat", 2, 8): model.NewBoolVar("b2"),
    }
    comp = DSLConstraintCompiler(model, slot)
    comp.compile('no_same_class_consecutive_days("1A")')

    m = model.Clone()
    m.Add(slot[("T1", "2B", "Mat", 1, 8)] == 1)
    m.Add(slot[("T1", "2B", "Mat", 2, 8)] == 1)
    s = cp_model.CpSolver()
    st = s.Solve(m)
    assert st in (cp_model.OPTIMAL, cp_model.FEASIBLE)
