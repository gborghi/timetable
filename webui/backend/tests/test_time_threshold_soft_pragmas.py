"""Time-threshold SOFT pragmas (B-gen): ``slot_after_hour_penalty`` and
``teacher_max_hours_after``.

User-facing examples these express:
  * "avoid afternoons (hour >= 14)"  -> slot_after_hour_penalty(14, W)
  * "max one hour after 15:00"        -> teacher_max_hours_after(15, 1, W)

``threshold_hour`` is in the SAME units as the slot key's hour field (the
frontend/translator maps clock time -> hour index; the engine stays
agnostic). Covered at all three layers:
  1. soft_costs.py   -- pure CP encoders
  2. dsl_to_cpsat.py -- DSLConstraintCompiler soft pragmas
  3. general_dsl.py  -- canonical boolean eval (round-trips through meta)
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "engine"))
WEBUI = os.path.normpath(os.path.join(HERE, "..", ".."))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
for _p in (ENGINE, WEBUI, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ortools.sat.python import cp_model  # noqa: E402


def _model_with_day1_slots(hours):
    m = cp_model.CpModel()
    slot = {("T1", "1A", "Mat", 1, h): m.NewBoolVar(f"s_{h}") for h in hours}
    return m, slot


# --------------------------------------------------------------------------
# Layer 1: soft_costs pure encoders
# --------------------------------------------------------------------------

def test_late_slot_pairs_one_per_late_var():
    import soft_costs as sc
    m, slot = _model_with_day1_slots([8, 9, 14, 15])
    pairs, aux = sc.late_slot_pairs(m, slot, weight=7, threshold_hour=14)
    assert aux == []
    assert len(pairs) == 2
    assert all(w == 7 for w, _ in pairs)
    late = {v for _, v in pairs}
    assert slot[("T1", "1A", "Mat", 1, 14)] in late
    assert slot[("T1", "1A", "Mat", 1, 15)] in late


def test_teacher_late_excess_pairs_semantics():
    import soft_costs as sc
    m, slot = _model_with_day1_slots([14, 15, 16])
    pairs, aux = sc.teacher_late_excess_pairs(
        m, slot, ["T1"], [1], weight=50, threshold_hour=14, max_n=1)
    assert len(pairs) == 1 and len(aux) == 1
    for v in slot.values():
        m.Add(v == 1)                       # all 3 late slots occupied
    m.Minimize(sum(w * v for w, v in pairs))
    s = cp_model.CpSolver()
    st = s.Solve(m)
    assert st in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert int(s.ObjectiveValue()) == 50 * (3 - 1)   # excess = 2


# --------------------------------------------------------------------------
# Layer 2: DSLConstraintCompiler soft pragmas
# --------------------------------------------------------------------------

def test_slot_after_hour_penalty_compiles_and_steers():
    import dsl_to_cpsat as dc
    m, slot = _model_with_day1_slots([8, 9, 14, 15])
    comp = dc.DSLConstraintCompiler(
        m, slot, is_hard=False, soft_weight=0, level="phase_b")
    comp.compile("slot_after_hour_penalty(14, 100)")
    assert len(comp.soft_cost_terms) == 2, comp.diagnostics
    m.Add(sum(slot.values()) == 1)          # one lesson must be placed
    m.Minimize(sum(w * v for w, v in comp.soft_cost_terms))
    s = cp_model.CpSolver()
    st = s.Solve(m)
    assert st in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    chosen = [k for k, v in slot.items() if s.Value(v) == 1]
    assert chosen and chosen[0][4] < 14, chosen   # picked an early slot


def test_teacher_max_hours_after_compiles_and_penalises_excess():
    import dsl_to_cpsat as dc
    m, slot = _model_with_day1_slots([14, 15, 16])
    comp = dc.DSLConstraintCompiler(
        m, slot, is_hard=False, soft_weight=0, level="phase_b")
    comp.compile("teacher_max_hours_after(14, 1, 50)")
    assert len(comp.soft_cost_terms) == 1, comp.diagnostics
    for v in slot.values():
        m.Add(v == 1)
    m.Minimize(sum(w * v for w, v in comp.soft_cost_terms))
    s = cp_model.CpSolver()
    st = s.Solve(m)
    assert st in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert int(s.ObjectiveValue()) == 50 * 2


def test_time_pragmas_skipped_on_phase_a_level():
    import dsl_to_cpsat as dc
    m, slot = _model_with_day1_slots([14, 15])
    comp = dc.DSLConstraintCompiler(
        m, slot, is_hard=False, soft_weight=0, level="phase_a")
    comp.compile("slot_after_hour_penalty(14, 100)")
    assert comp.soft_cost_terms == []
    assert any("skipped" in d for d in comp.diagnostics)


# --------------------------------------------------------------------------
# Layer 3: general_dsl canonical boolean eval
# --------------------------------------------------------------------------

def test_eval_slot_after_hour_penalty_bool():
    from backend.utils import general_dsl as G
    clean = {"lessons": [{"teacher": "T1", "class": "1A", "day": 1,
                          "hour": 9}]}
    late = {"lessons": [{"teacher": "T1", "class": "1A", "day": 1,
                         "hour": 15}]}
    tree = G.parse("slot_after_hour_penalty(14, 100)")
    assert G.evaluate(tree, clean) is True
    assert G.evaluate(tree, late) is False


def test_eval_teacher_max_hours_after_bool():
    from backend.utils import general_dsl as G
    ok = {"lessons": [{"teacher": "T1", "class": "1A", "day": 1,
                       "hour": 15}]}                       # 1 late hour <= 1
    bad = {"lessons": [
        {"teacher": "T1", "class": "1A", "day": 1, "hour": 15},
        {"teacher": "T1", "class": "1A", "day": 1, "hour": 16},  # 2 > 1
    ]}
    tree = G.parse("teacher_max_hours_after(14, 1, 50)")
    assert G.evaluate(tree, ok) is True
    assert G.evaluate(tree, bad) is False
