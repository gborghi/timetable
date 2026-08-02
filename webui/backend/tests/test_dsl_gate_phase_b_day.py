"""Audit H6: the per-day monolithic solver enforces non-compilable HARD DSL.

``cpsat_v2_timetable.solve_phase_b_for_day`` compiles the compilable DSL
fragment natively but, before this change, silently SKIPPED any HARD rule
the CP compiler (``dsl_to_cpsat``) could not emit -- recording a
``compile_failed:`` diagnostic and shipping a timetable that violates it.

This test drives the day solver with a HARD rule the compiler cannot model
(a ``forall c in classes: count ...`` aggregate -- ``forall`` over a source
other than ``lessons`` is explicitly unsupported by the compiler, but the
post-hoc ``general_dsl`` evaluator handles it) and asserts:

  1. WITH the rule + ``via_dsl=True``: the returned day satisfies it (the
     verify + no-good refinement gate forces a compliant placement).
  2. WITHOUT the rule: the solve is unchanged (still returns a placement).
  3. A forced violation (native lock on the forbidden cell) makes the gate
     fail closed -- the exact no-good deterministically drives the model
     INFEASIBLE, so a rule the engine cannot satisfy is never shipped.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "engine"))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

# A HARD rule the CP compiler CANNOT emit (forall over `classes`, plus a
# `count` aggregate) but the general_dsl evaluator CAN check: "no class has
# Matematica at the first hour (8)".
NONCOMPILABLE_HARD = (
    'forall c in classes: count l in lessons '
    'where l.class == c.name and l.subject == "Mat" and l.hour == 8 <= 0'
)

# Per-class flags that switch OFF the ex-officio invariants (entry-at-8,
# no-holes, exit-after-12) so a single-hour toy instance is feasible and the
# lesson is free to land on any hour 8..13.
_FLAGS = {"1A": {"entry_at_8": False, "no_holes": False,
                 "exit_after_12": False}}


def _instance():
    profs = {"T1": {"classi": {"1A": {"Mat": {"ore": 1}}},
                    "max_hours": 18, "min_free_days": 0}}
    classes, triples, class_profs = _cv2().build_indices(profs)
    dc_value = {("T1", "1A", "Mat", 1): 1}   # 1 Mat hour on day 1
    return profs, classes, triples, class_profs, dc_value


def _cv2():
    import cpsat_v2_timetable as cv2  # type: ignore
    return cv2


def _placed(sol):
    return {k for k, v in (sol or {}).items() if int(v) == 1}


def test_noncompilable_hard_rule_is_enforced_on_day_path():
    cv2 = _cv2()
    profs, classes, triples, class_profs, dc_value = _instance()

    out, status = cv2.solve_phase_b_for_day(
        1, profs, classes, triples, class_profs, dc_value,
        time_limit=10, workers=1, class_flags=_FLAGS,
        via_dsl=True, dsl_hard_expressions=[NONCOMPILABLE_HARD],
    )
    assert out is not None, f"gated solve infeasible (status={status})"
    placed = _placed(out)
    # exactly one Mat hour placed, and NOT at the forbidden hour 8.
    assert len(placed) == 1, placed
    assert ("T1", "1A", "Mat", 1, 8) not in placed, placed
    # the post-hoc evaluator confirms full compliance on the day slice.
    import dsl_cp_gate as g  # type: ignore
    assert g.verify_dsl_hard(out, profs, [NONCOMPILABLE_HARD], day=1) == []


def test_without_rule_day_solve_unchanged():
    cv2 = _cv2()
    profs, classes, triples, class_profs, dc_value = _instance()

    out, status = cv2.solve_phase_b_for_day(
        1, profs, classes, triples, class_profs, dc_value,
        time_limit=10, workers=1, class_flags=_FLAGS,
    )
    assert out is not None, status
    # one Mat hour placed somewhere in 8..13 (legacy behaviour: the rule is
    # absent, so hour 8 is a perfectly valid placement).
    assert len(_placed(out)) == 1, out


def test_gate_fails_closed_on_forced_violation():
    """A native lock pinning Mat to the forbidden cell makes the only
    solution violate the rule; the no-good gate drives it INFEASIBLE
    (fail-closed) rather than shipping the violation."""
    cv2 = _cv2()
    profs, classes, triples, class_profs, dc_value = _instance()
    lock = [("T1", "1A", "Mat", 8)]      # 4-tuple (p, cl, subj, hour)

    # Without the rule: the lock is honoured, Mat lands at hour 8.
    out_free, _ = cv2.solve_phase_b_for_day(
        1, profs, classes, triples, class_profs, dc_value,
        time_limit=10, workers=1, class_flags=_FLAGS,
        locked_slots_for_day=lock,
    )
    assert ("T1", "1A", "Mat", 1, 8) in _placed(out_free), out_free

    # With the rule: the locked-in violation cannot be escaped, so the
    # gate exhausts the no-goods and fails closed (returns None).
    out_gated, status = cv2.solve_phase_b_for_day(
        1, profs, classes, triples, class_profs, dc_value,
        time_limit=10, workers=1, class_flags=_FLAGS,
        locked_slots_for_day=lock,
        via_dsl=True, dsl_hard_expressions=[NONCOMPILABLE_HARD],
    )
    assert out_gated is None, f"expected fail-closed, got {out_gated}"


# A HARD rule the CP compiler cannot emit AND general_dsl cannot parse: it
# can be neither compiled natively nor certified by the evaluator -- the
# audit H6 residual the True-on-error default used to let slip through.
UNCERTIFIABLE_HARD = 'forall c in classes: count l in lessons where !! ::'


def test_uncertifiable_hard_rule_fails_closed_on_day_path():
    """A non-compilable HARD rule that also cannot be parsed/evaluated must
    fail closed (return None), not silently ship: the day gate can neither
    model it natively nor certify it, so accepting the solve would be the
    silent-pass residual."""
    cv2 = _cv2()
    profs, classes, triples, class_profs, dc_value = _instance()

    out, status = cv2.solve_phase_b_for_day(
        1, profs, classes, triples, class_profs, dc_value,
        time_limit=10, workers=1, class_flags=_FLAGS,
        via_dsl=True, dsl_hard_expressions=[UNCERTIFIABLE_HARD],
    )
    assert out is None, f"expected fail-closed on uncertifiable HARD, got {out}"


def test_validator_fails_closed_on_uncertifiable_hard_rule():
    """``metaheuristics.is_hard_feasible`` must refuse to certify a solution
    against a HARD rule it cannot parse/evaluate -- otherwise the activation
    gate would green-light an unenforced HARD constraint."""
    import metaheuristics as mh  # type: ignore
    profs, classes, triples, class_profs, dc_value = _instance()
    # A perfectly legal placement -- the only reason to reject is that the
    # HARD rule is uncertifiable.
    sol = {("T1", "1A", "Mat", 1, 9): 1}
    assert mh.is_hard_feasible(
        sol, profs, dsl_hard_expressions=[UNCERTIFIABLE_HARD]) is False
    # Without the uncertifiable rule the same solution is feasible.
    assert mh.is_hard_feasible(sol, profs, class_flags=_FLAGS) is True
