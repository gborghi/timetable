"""Audit F6: the post-hoc ``subject_pair_*`` evaluator must agree with the
native compiler (``add_consecutive_constraints_phase_b``), which pairs on the
TEACHER's combined presence across all their subjects in the class -- NOT on
the specific subject's hours. Option A: keep the compiler's semantics and make
the evaluator match, so an audit / is_hard_feasible stops flagging timetables
the solver deliberately produced.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "engine"))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)


def _ok(expr, lessons):
    import general_dsl as G  # type: ignore
    ok, err = G.evaluate_safe(G.parse(expr), {"lessons": lessons})
    assert err is None, err
    return ok


def _L(teacher, cl, subj, day, hour):
    return {"teacher": teacher, "class": cl, "subject": subj,
            "day": day, "hour": hour}


def test_split_subject_but_teacher_block_is_satisfied():
    """Mate at 8 and 11 (split) but the SAME teacher teaches Fisica at 9, so
    the teacher has an adjacent 8-9 block -> the compiler allows it, so the
    evaluator must too."""
    lessons = [
        _L("T", "1A", "Matematica", 1, 8),
        _L("T", "1A", "Fisica", 1, 9),
        _L("T", "1A", "Matematica", 1, 11),
    ]
    assert _ok('subject_pair_exists("1A", "Matematica")', lessons) is True
    assert _ok('subject_pair_must("1A", "Matematica")', lessons) is True


def test_no_teacher_block_is_violated():
    """The teacher's only two hours in the class are non-adjacent (8, 11) ->
    no block anywhere -> violated."""
    lessons = [
        _L("T", "1A", "Matematica", 1, 8),
        _L("T", "1A", "Matematica", 1, 11),
    ]
    assert _ok('subject_pair_exists("1A", "Matematica")', lessons) is False


def test_adjacent_subject_hours_are_satisfied():
    """The plain case: the two Matematica hours are themselves adjacent."""
    lessons = [
        _L("T", "1A", "Matematica", 1, 8),
        _L("T", "1A", "Matematica", 1, 9),
    ]
    assert _ok('subject_pair_exists("1A", "Matematica")', lessons) is True


def test_single_hour_needs_no_pair():
    lessons = [_L("T", "1A", "Matematica", 1, 8)]
    assert _ok('subject_pair_exists("1A", "Matematica")', lessons) is True
