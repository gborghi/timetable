"""Tests for canonical-pattern pragma functions evaluated post-hoc by
``general_dsl.evaluate``.

The DSL compiler in ``engine.dsl_to_cpsat`` recognizes a vocabulary of
named-call pragmas (``no_holes_class``, ``class_present_at_hour``,
``teacher_max_per_day``, ...) that compile to compact CP-SAT
encodings. The post-hoc evaluator must accept the same names so that
``metaheuristics.is_hard_feasible`` (and any other DSL HARD verifier)
can validate a finalised solution against pragma-style HARD rules.

For each pragma the suite covers a SAT scenario (rule respected ->
True) and an UNSAT scenario (rule violated -> False).
"""
from __future__ import annotations

from backend.utils import general_dsl as G


# ---- world helpers ----

DAYS = list(range(1, 7))
HOURS = list(range(8, 14))


def _world(lessons, **kw):
    base = {
        "teachers": kw.get("teachers", []),
        "classes": kw.get("classes", []),
        "classrooms": [],
        "subjects": [],
        "curricula": [],
        "groups": [],
        "students": [],
        "assignments": kw.get("assignments", []),
        "days": [{"index": d} for d in DAYS],
        "hours": [{"index": h} for h in HOURS],
        "slots": [{"day": d, "hour": h} for d in DAYS for h in HOURS],
        "lessons": lessons,
    }
    return base


def _lesson(t, cl, subj, d, h, **extras):
    base = {
        "teacher": t, "class": cl, "subject": subj,
        "day": d, "hour": h,
        "classroom": "", "classroom_type": "",
        "classroom_kind": "", "classroom_tags": [],
        "classroom_plesso": None,
        "slot": (d, h),
    }
    base.update(extras)
    return base


# ============================================================
# no_holes_class
# ============================================================


def test_no_holes_class_true_when_contiguous_from_h_min():
    """4 consecutive hours starting at h=8 -> rule respected."""
    lessons = [
        _lesson("T", "1A", "Mat", 1, 8),
        _lesson("T", "1A", "Mat", 1, 9),
        _lesson("T", "1A", "Mat", 1, 10),
        _lesson("T", "1A", "Mat", 1, 11),
    ]
    tree = G.parse('no_holes_class("1A")')
    assert G.evaluate(tree, _world(lessons)) is True


def test_no_holes_class_false_when_hole_in_middle():
    """Busy at 8, 9, 11 (free at 10) -> hole."""
    lessons = [
        _lesson("T", "1A", "Mat", 1, 8),
        _lesson("T", "1A", "Mat", 1, 9),
        _lesson("T", "1A", "Mat", 1, 11),
    ]
    tree = G.parse('no_holes_class("1A")')
    assert G.evaluate(tree, _world(lessons)) is False


def test_no_holes_class_false_when_not_anchored_at_h_min():
    """Busy at 9, 10 (h=8 free): the encoding requires the prefix to
    start at h_min (no_holes is non-increasing chain anchored at 8)."""
    lessons = [
        _lesson("T", "1A", "Mat", 1, 9),
        _lesson("T", "1A", "Mat", 1, 10),
    ]
    tree = G.parse('no_holes_class("1A")')
    assert G.evaluate(tree, _world(lessons)) is False


def test_no_holes_class_true_when_class_empty():
    """A class with no lessons trivially has no holes."""
    tree = G.parse('no_holes_class("1A")')
    assert G.evaluate(tree, _world([])) is True


def test_no_holes_class_ignores_other_classes():
    """A hole in a different class does not flag a violation."""
    lessons = [
        _lesson("T", "1A", "Mat", 1, 8),
        _lesson("T", "1B", "Mat", 1, 8),
        _lesson("T", "1B", "Mat", 1, 10),    # 1B has a hole; 1A doesn't
    ]
    tree = G.parse('no_holes_class("1A")')
    assert G.evaluate(tree, _world(lessons)) is True


def test_no_holes_class_excludes_group_lessons():
    """Lessons tagged ``_is_group`` are not counted toward the class's
    busy hours (mirrors the compiler's exclusion)."""
    lessons = [
        _lesson("T", "1A", "Mat", 1, 8),
        _lesson("T", "1A", "Eng", 1, 10, _is_group=True),
    ]
    tree = G.parse('no_holes_class("1A")')
    # Without the group flag the schedule has a hole at 9; with it
    # excluded only h=8 is busy and that's a valid prefix.
    assert G.evaluate(tree, _world(lessons)) is True


# ============================================================
# no_holes_all_classes
# ============================================================


def test_no_holes_all_classes_true_when_all_contiguous():
    lessons = [
        _lesson("T", "1A", "Mat", 1, 8),
        _lesson("T", "1A", "Mat", 1, 9),
        _lesson("T", "1B", "Mat", 1, 8),
    ]
    tree = G.parse('no_holes_all_classes()')
    assert G.evaluate(tree, _world(lessons)) is True


def test_no_holes_all_classes_false_when_one_class_violates():
    lessons = [
        _lesson("T", "1A", "Mat", 1, 8),
        _lesson("T", "1B", "Mat", 1, 9),    # 1B has gap at 8
    ]
    tree = G.parse('no_holes_all_classes()')
    assert G.evaluate(tree, _world(lessons)) is False


# ============================================================
# class_present_at_hour
# ============================================================


def test_class_present_at_hour_true_when_busy_hour_includes_target():
    lessons = [
        _lesson("T", "1A", "Mat", 1, 8),
        _lesson("T", "1A", "Mat", 1, 11),
    ]
    tree = G.parse('class_present_at_hour("1A", 11)')
    assert G.evaluate(tree, _world(lessons)) is True


def test_class_present_at_hour_false_when_busy_day_misses_target():
    lessons = [
        _lesson("T", "1A", "Mat", 1, 8),
        _lesson("T", "1A", "Mat", 1, 9),
    ]
    tree = G.parse('class_present_at_hour("1A", 11)')
    assert G.evaluate(tree, _world(lessons)) is False


def test_class_present_at_hour_true_when_class_idle_that_day():
    """When the class has no lessons on day d, the rule is vacuously
    satisfied for that day."""
    lessons = []
    tree = G.parse('class_present_at_hour("1A", 11)')
    assert G.evaluate(tree, _world(lessons)) is True


def test_class_present_at_hour_all_true():
    lessons = [
        _lesson("T", "1A", "Mat", 1, 11),
        _lesson("T", "1B", "Mat", 1, 11),
    ]
    tree = G.parse('class_present_at_hour_all(11)')
    assert G.evaluate(tree, _world(lessons)) is True


def test_class_present_at_hour_all_false_when_one_class_misses():
    lessons = [
        _lesson("T", "1A", "Mat", 1, 11),
        _lesson("T", "1B", "Mat", 1, 8),    # busy but not at 11
    ]
    tree = G.parse('class_present_at_hour_all(11)')
    assert G.evaluate(tree, _world(lessons)) is False


# ============================================================
# teacher_max_per_day
# ============================================================


def test_teacher_max_per_day_true_when_under_cap():
    lessons = [
        _lesson("T", "1A", "Mat", 1, 8),
        _lesson("T", "1B", "Mat", 1, 9),
        _lesson("T", "1C", "Mat", 2, 8),
    ]
    tree = G.parse('teacher_max_per_day("T", 2)')
    assert G.evaluate(tree, _world(lessons)) is True


def test_teacher_max_per_day_false_when_over_cap():
    lessons = [
        _lesson("T", "1A", "Mat", 1, 8),
        _lesson("T", "1B", "Mat", 1, 9),
        _lesson("T", "1C", "Mat", 1, 10),    # 3 lessons on day 1
    ]
    tree = G.parse('teacher_max_per_day("T", 2)')
    assert G.evaluate(tree, _world(lessons)) is False


# ============================================================
# cattedra_max_per_day
# ============================================================


def test_cattedra_max_per_day_true_when_under_cap():
    lessons = [
        _lesson("T", "1A", "Mat", 1, 8),
        _lesson("T", "1A", "Mat", 1, 9),
    ]
    tree = G.parse('cattedra_max_per_day("T", "1A", "Mat", 2)')
    assert G.evaluate(tree, _world(lessons)) is True


def test_cattedra_max_per_day_false_when_over_cap():
    lessons = [
        _lesson("T", "1A", "Mat", 1, 8),
        _lesson("T", "1A", "Mat", 1, 9),
        _lesson("T", "1A", "Mat", 1, 10),    # 3 hours of (T, 1A, Mat)
    ]
    tree = G.parse('cattedra_max_per_day("T", "1A", "Mat", 2)')
    assert G.evaluate(tree, _world(lessons)) is False


def test_cattedra_max_per_day_does_not_count_other_cattedre():
    lessons = [
        _lesson("T", "1A", "Mat", 1, 8),
        _lesson("T", "1B", "Mat", 1, 9),    # different class
        _lesson("T", "1A", "Eng", 1, 10),    # different subj
    ]
    tree = G.parse('cattedra_max_per_day("T", "1A", "Mat", 1)')
    assert G.evaluate(tree, _world(lessons)) is True


# ============================================================
# subject_pair_{must, exists}
# ============================================================


def test_subject_pair_exists_true_when_consecutive():
    lessons = [
        _lesson("T", "1A", "Mat", 1, 8),
        _lesson("T", "1A", "Mat", 1, 9),
    ]
    tree = G.parse('subject_pair_exists("1A", "Mat")')
    assert G.evaluate(tree, _world(lessons)) is True


def test_subject_pair_exists_false_when_split():
    """2 hours on the same day but separated -> no consecutive pair."""
    lessons = [
        _lesson("T", "1A", "Mat", 1, 8),
        _lesson("T", "1A", "Mat", 1, 11),
    ]
    tree = G.parse('subject_pair_exists("1A", "Mat")')
    assert G.evaluate(tree, _world(lessons)) is False


def test_subject_pair_must_same_as_exists_for_two_hours():
    lessons = [
        _lesson("T", "1A", "Mat", 1, 8),
        _lesson("T", "1A", "Mat", 1, 9),
    ]
    tree = G.parse('subject_pair_must("1A", "Mat")')
    assert G.evaluate(tree, _world(lessons)) is True


def test_subject_pair_exists_vacuous_when_one_hour():
    """1 hour on the day -> rule does not trigger."""
    lessons = [_lesson("T", "1A", "Mat", 1, 8)]
    tree = G.parse('subject_pair_exists("1A", "Mat")')
    assert G.evaluate(tree, _world(lessons)) is True


def test_subject_pair_exists_three_hours_one_pair_ok():
    """3 hours: 8, 9, 11 -> at least one consecutive pair (8,9)."""
    lessons = [
        _lesson("T", "1A", "Mat", 1, 8),
        _lesson("T", "1A", "Mat", 1, 9),
        _lesson("T", "1A", "Mat", 1, 11),
    ]
    tree = G.parse('subject_pair_exists("1A", "Mat")')
    assert G.evaluate(tree, _world(lessons)) is True


# ============================================================
# class_day_load_in
# ============================================================


def test_class_day_load_in_true_when_all_days_in_set():
    """1A: day 1 = 4 hours, day 2 = 5 hours, every other day = 0."""
    lessons = [
        _lesson("T", "1A", "Mat", 1, 8),
        _lesson("T", "1A", "Mat", 1, 9),
        _lesson("T", "1A", "Mat", 1, 10),
        _lesson("T", "1A", "Mat", 1, 11),
        _lesson("T", "1A", "Mat", 2, 8),
        _lesson("T", "1A", "Mat", 2, 9),
        _lesson("T", "1A", "Mat", 2, 10),
        _lesson("T", "1A", "Mat", 2, 11),
        _lesson("T", "1A", "Mat", 2, 12),
    ]
    tree = G.parse('class_day_load_in("1A", 0, 4, 5)')
    assert G.evaluate(tree, _world(lessons)) is True


def test_class_day_load_in_false_when_one_day_outside():
    """1A: day 1 = 3 hours -> not in {0, 4, 5}."""
    lessons = [
        _lesson("T", "1A", "Mat", 1, 8),
        _lesson("T", "1A", "Mat", 1, 9),
        _lesson("T", "1A", "Mat", 1, 10),
    ]
    tree = G.parse('class_day_load_in("1A", 0, 4, 5)')
    assert G.evaluate(tree, _world(lessons)) is False


def test_class_day_load_in_zero_required_when_class_idle():
    """If 0 is NOT in the allowed set, an idle day flags violation."""
    lessons = [
        _lesson("T", "1A", "Mat", 1, 8),
        _lesson("T", "1A", "Mat", 1, 9),
        _lesson("T", "1A", "Mat", 1, 10),
        _lesson("T", "1A", "Mat", 1, 11),
    ]
    tree = G.parse('class_day_load_in("1A", 4, 5)')
    # Days 2..6 are idle (load=0) -> 0 not in {4,5} -> False
    assert G.evaluate(tree, _world(lessons)) is False


def test_class_day_load_in_day_count_alias():
    """Phase A alias compiles to the same post-hoc check on lessons."""
    lessons = [
        _lesson("T", "1A", "Mat", 1, 8),
        _lesson("T", "1A", "Mat", 1, 9),
        _lesson("T", "1A", "Mat", 1, 10),
        _lesson("T", "1A", "Mat", 1, 11),
    ]
    tree = G.parse('class_day_load_in_day_count("1A", 0, 4)')
    assert G.evaluate(tree, _world(lessons)) is True


# ============================================================
# subject_day_count_in
# ============================================================


def test_subject_day_count_in_true_when_load_in_set():
    """(1A, Motoria): day 1 has 2 hours, every other day has 0."""
    lessons = [
        _lesson("T", "1A", "Motoria", 1, 8),
        _lesson("T", "1A", "Motoria", 1, 9),
    ]
    tree = G.parse('subject_day_count_in("1A", "Motoria", 0, 2)')
    assert G.evaluate(tree, _world(lessons)) is True


def test_subject_day_count_in_false_when_load_outside_set():
    """3 hours of Motoria on day 1 -> 3 not in {0, 2}."""
    lessons = [
        _lesson("T", "1A", "Motoria", 1, 8),
        _lesson("T", "1A", "Motoria", 1, 9),
        _lesson("T", "1A", "Motoria", 1, 10),
    ]
    tree = G.parse('subject_day_count_in("1A", "Motoria", 0, 2)')
    assert G.evaluate(tree, _world(lessons)) is False


# ============================================================
# subject_day_count_pair
# ============================================================


def test_subject_day_count_pair_true_when_at_least_one_dense_day():
    """Day 1 has 2 hours of Mat for the cattedra -> >=1 day with >=2."""
    lessons = [
        _lesson("T", "1A", "Mat", 1, 8),
        _lesson("T", "1A", "Mat", 1, 9),
        _lesson("T", "1A", "Mat", 2, 8),
    ]
    tree = G.parse('subject_day_count_pair("T", "1A", "Mat", 2)')
    assert G.evaluate(tree, _world(lessons)) is True


def test_subject_day_count_pair_false_when_all_days_thin():
    """Every day has at most 1 Mat hour for the cattedra."""
    lessons = [
        _lesson("T", "1A", "Mat", 1, 8),
        _lesson("T", "1A", "Mat", 2, 8),
        _lesson("T", "1A", "Mat", 3, 8),
    ]
    tree = G.parse('subject_day_count_pair("T", "1A", "Mat", 2)')
    assert G.evaluate(tree, _world(lessons)) is False


# ============================================================
# hall_bound_prof_day
# ============================================================


def test_hall_bound_prof_day_true_when_pdl_le_max_cl_load():
    """Day 1: prof T does 2 hours in 1A; 1A has 3 busy hours -> 2 <= 3."""
    lessons = [
        _lesson("T", "1A", "Mat", 1, 8),
        _lesson("T", "1A", "Mat", 1, 9),
        _lesson("U", "1A", "Eng", 1, 10),
    ]
    tree = G.parse('hall_bound_prof_day("T")')
    assert G.evaluate(tree, _world(lessons)) is True


def test_hall_bound_prof_day_false_when_pdl_exceeds():
    """Day 1: T does 1 hour in 1A and 1 hour in 1B; 1A has 1 busy
    hour, 1B has 1 -> max class load = 1 < prof_load 2 -> violation.
    """
    lessons = [
        _lesson("T", "1A", "Mat", 1, 8),
        _lesson("T", "1B", "Mat", 1, 9),
    ]
    tree = G.parse('hall_bound_prof_day("T")')
    assert G.evaluate(tree, _world(lessons)) is False


# ============================================================
# free_day_choice_3way
# ============================================================


def test_free_day_choice_3way_true_when_one_candidate_is_free():
    """Prof T busy on days 1, 2; candidates {3, 4, 5} all free."""
    lessons = [
        _lesson("T", "1A", "Mat", 1, 8),
        _lesson("T", "1A", "Mat", 2, 8),
    ]
    tree = G.parse('free_day_choice_3way("T", 3, 4, 5)')
    assert G.evaluate(tree, _world(lessons)) is True


def test_free_day_choice_3way_false_when_all_candidates_busy():
    """Prof T busy on every candidate day -> no free choice."""
    lessons = [
        _lesson("T", "1A", "Mat", 3, 8),
        _lesson("T", "1A", "Mat", 4, 8),
        _lesson("T", "1A", "Mat", 5, 8),
    ]
    tree = G.parse('free_day_choice_3way("T", 3, 4, 5)')
    assert G.evaluate(tree, _world(lessons)) is False


# ============================================================
# Validation: unknown function still raises
# ============================================================


def test_unknown_pragma_raises():
    """A call to an unknown function must raise DSLError so the
    surrounding harness can report a typo."""
    import pytest
    tree = G.parse('frobnicate("1A")')
    with pytest.raises(G.DSLError):
        G.evaluate(tree, _world([]))


# ============================================================
# Integration: rule wrapped in implies, used in is_hard_feasible style
# ============================================================


def test_pragma_inside_implies_short_circuit():
    """A pragma can appear under any boolean wrapper. When the
    antecedent is False, the consequent's pragma never evaluates."""
    lessons = [_lesson("T", "1A", "Mat", 1, 8)]
    tree = G.parse('false => no_holes_class("DOES_NOT_EXIST")')
    assert G.evaluate(tree, _world(lessons)) is True


def test_pragma_combined_with_and():
    """``no_holes AND class_load_in`` evaluates both."""
    lessons = [
        _lesson("T", "1A", "Mat", 1, 8),
        _lesson("T", "1A", "Mat", 1, 9),
    ]
    tree = G.parse(
        'no_holes_class("1A") AND class_day_load_in("1A", 0, 2)')
    assert G.evaluate(tree, _world(lessons)) is True


# ============================================================
# is_hard_feasible integration: pragma rules drive HARD verdict
# ============================================================


def test_is_hard_feasible_consumes_pragma_expression():
    """End-to-end: a metaheuristic-built world is fed through
    ``metaheuristics.is_hard_feasible`` with a pragma DSL expression.
    A respected schedule returns True; a violation returns False.
    """
    import os
    import sys
    HERE = os.path.dirname(os.path.abspath(__file__))
    ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from engine.metaheuristics import is_hard_feasible

    profs = {
        "T": {"classi": {"1A": {"Mat": {"ore": 4}}}, "max_hours": 18}
    }
    # 4 contiguous Mat hours on day 1 starting at h=8 -> no holes,
    # cattedra_max_per_day(T,1A,Mat,4) ok, class_day_load_in(1A,0,4) ok
    sol_ok = {("T", "1A", "Mat", 1, 8): 1,
              ("T", "1A", "Mat", 1, 9): 1,
              ("T", "1A", "Mat", 1, 10): 1,
              ("T", "1A", "Mat", 1, 11): 1}
    assert is_hard_feasible(
        sol_ok, profs,
        dsl_hard_expressions=['no_holes_class("1A")']) is True
    assert is_hard_feasible(
        sol_ok, profs,
        dsl_hard_expressions=[
            'class_day_load_in("1A", 0, 4)']) is True

    # The same 4-hour schedule passes the built-in H1/H2/H3 checks
    # (contiguous from h=8 to h=11). With the pragma asking at most
    # 3 hours/day for the cattedra, the day-1 load (4) violates.
    assert is_hard_feasible(
        sol_ok, profs,
        dsl_hard_expressions=[
            'cattedra_max_per_day("T", "1A", "Mat", 3)']) is False
    assert is_hard_feasible(
        sol_ok, profs,
        dsl_hard_expressions=[
            'cattedra_max_per_day("T", "1A", "Mat", 4)']) is True
