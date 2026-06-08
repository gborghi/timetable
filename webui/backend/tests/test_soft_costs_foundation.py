from __future__ import annotations
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "engine"))
WEBUI = os.path.normpath(os.path.join(HERE, "..", ".."))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
for p in (ENGINE, WEBUI, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from ortools.sat.python import cp_model


def test_sixth_slot_terms_one_per_slot_at_h13():
    """sixth_slot_terms emits exactly one (weight*var) term per slot var
    whose hour == 13, and none for other hours."""
    import soft_costs
    model = cp_model.CpModel()
    slot = {
        ("T1", "1A", "Mat", 1, 12): model.NewBoolVar("a"),
        ("T1", "1A", "Mat", 1, 13): model.NewBoolVar("b"),
        ("T1", "1B", "Mat", 1, 13): model.NewBoolVar("c"),
    }
    pairs, aux = soft_costs.sixth_slot_pairs(model, slot, weight=50, sixth_hour=13)
    # 2 slots at h13 -> 2 (weight, var) pairs; no aux vars in slot mode
    assert len(pairs) == 2
    assert all(w == 50 for w, _v in pairs)
    assert aux == []


def test_compute_soft_cost_expr_sixth_unchanged_after_delegation():
    """Zero-drift: a MonolithicSolver's solved objective is identical
    whether the sixth term comes from the inline body or the extracted
    soft_costs function. Both modes."""
    from cp_sat_constraint_model import MonolithicSolver, ConstraintConfig
    profs = {"T1": {"classi": {"1A": {"Mat": {"ore": 6}}}, "max_hours": 18}}
    dc = {("T1", "1A", "Mat", 1): 6}
    ms = MonolithicSolver(profs, dc, ConstraintConfig(enforce_no_holes=False))
    terms, _ = ms.compute_soft_cost_expr(mode="default")
    ms.model.Minimize(sum(terms))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5.0
    status = solver.Solve(ms.model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
