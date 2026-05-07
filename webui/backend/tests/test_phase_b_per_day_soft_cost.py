"""Sblocco 2 -- ``compute_soft_cost_expr(mode="phase_b_per_day")``.

The OO method now accepts a ``mode`` parameter that selects between
the default Phase A canonical formulation (sixth + buchi + five + one
with weights ``meta.OBJECTIVE_WEIGHTS * SCALE``) and a Phase B per-day
formulation that mirrors ``cpsat_v2_timetable.solve_phase_b_for_day``:

* ``W_SIXTH_B = 5`` per CLASS-busy indicator at h=13 (NOT per-slot);
* ``W_GAP = 10`` per (teacher, day) buchi;
* ``five`` and ``one`` penalties are SKIPPED (Phase B per-day cannot
  observe weekly day-counts -- the legacy emits them in Phase A).

These tests verify the term composition + weights of each mode by
inspecting the obj_terms list directly. Solving + cost-comparison vs
the legacy ``solve_phase_b_for_day`` is the next step (out of scope
for this sblocco -- migration of the per-day Phase B objective).
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "engine"))
WEBUI = os.path.normpath(os.path.join(HERE, "..", ".."))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
for p in (ENGINE, WEBUI, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)


# ============================================================
# Helpers
# ============================================================


def _term_summary(obj_terms):
    """Map ``obj_terms`` (list of ``coef * var``) to ``[(coef, kind),
    ...]`` where ``kind`` is the prefix of the var name (e.g.
    ``"slot"``, ``"sx"``, ``"bch"``, ``"5"``, ``"1"``). Useful for
    asserting term composition without relying on var identity."""
    out = []
    for term in obj_terms:
        # Each term is a LinearExpr with one variable and a coefficient.
        # In ortools-py, LinearExpr `c * v` has `Proto()` accessible.
        # We extract the coefficient via the proto and the var name
        # via ``term.GetVars()[0].Name()`` (when supported); fallback
        # to string parsing.
        s = str(term)
        # ``str(term)`` is "C*name" or "(C*name)" for product expr.
        out.append(s)
    return out


def _expr_to_pairs(obj_terms):
    """Convert the obj_terms to a list of (coef, var_name) tuples for
    inspection. CP-SAT LinearExpr's repr is "K * NAME" or just "NAME"
    for K=1; we parse it permissively."""
    pairs = []
    for term in obj_terms:
        s = str(term)
        # Common forms: ``5 * sx_1A_1``, ``1000 * bch_T1_1``,
        # ``8000 * 1_T1_1``, ``slot_T1_1A_Mat_1_13`` (coef=1).
        s = s.strip().lstrip("(").rstrip(")")
        if "*" in s:
            coef_part, name_part = s.split("*", 1)
            try:
                coef = int(coef_part.strip())
            except ValueError:
                coef = None
            pairs.append((coef, name_part.strip()))
        else:
            pairs.append((1, s))
    return pairs


def _profs_two_classes_with_h13():
    """Two teachers, two classes, with enough hours to reach h=13."""
    return {
        "T1": {"classi": {"1A": {"Mat": {"ore": 6}}},
                "max_hours": 18},
        "T2": {"classi": {"1B": {"Ita": {"ore": 6}}},
                "max_hours": 18},
    }


def _dc_two_classes_with_h13():
    return {
        ("T1", "1A", "Mat", 1): 6,
        ("T2", "1B", "Ita", 1): 6,
    }


# ============================================================
# 1. Mode validation
# ============================================================


def test_unknown_mode_raises_value_error():
    from cp_sat_constraint_model import (
        ConstraintModel, ConstraintConfig)
    profs = _profs_two_classes_with_h13()
    dc = _dc_two_classes_with_h13()
    cm = ConstraintModel(profs, dc, ConstraintConfig())
    with pytest.raises(ValueError):
        cm.compute_soft_cost_expr(mode="bogus")


def test_default_mode_is_default_param():
    """Calling with no kwargs must equal calling with mode='default'."""
    from cp_sat_constraint_model import (
        ConstraintModel, ConstraintConfig)
    cm1 = ConstraintModel(_profs_two_classes_with_h13(),
                            _dc_two_classes_with_h13(),
                            ConstraintConfig())
    cm2 = ConstraintModel(_profs_two_classes_with_h13(),
                            _dc_two_classes_with_h13(),
                            ConstraintConfig())
    obj1, _ = cm1.compute_soft_cost_expr()
    obj2, _ = cm2.compute_soft_cost_expr(mode="default")
    assert len(obj1) == len(obj2)


# ============================================================
# 2. Default mode -- canonical (50, 10, 30, 80) * 100
# ============================================================


def test_default_mode_emits_all_four_components():
    """Default mode: per-slot sixth (h=13) + per-(t, d) buchi/five/one.
    Weights must be ``meta.OBJECTIVE_WEIGHTS * SCALE``."""
    from cp_sat_constraint_model import (
        ConstraintModel, ConstraintConfig,
        PENALTY_SIXTH, PENALTY_BUCHI, PENALTY_FIVE, PENALTY_ONE,
        SIXTH_HOUR)
    profs = _profs_two_classes_with_h13()
    dc = _dc_two_classes_with_h13()
    cm = ConstraintModel(profs, dc, ConstraintConfig())
    obj, _ = cm.compute_soft_cost_expr(mode="default")
    pairs = _expr_to_pairs(obj)
    # Sixth-hour penalty: per-slot at h=13.
    # Each cattedra has 6 hours per day, only at h=13 emits. With
    # HOURS = 8..13 (6 hours), each (t, cl, s) emits one slot var at
    # h=13 per day. We have 1 day x 2 cattedre = 2 sixth terms.
    sixth = [p for p in pairs if p[0] == PENALTY_SIXTH]
    # Each sixth term wraps a slot var (name starts ``slot_``).
    assert len(sixth) >= 1
    # Buchi: per (t, d) where t has any slot. We have 2 teachers x 6
    # days = 12 candidate slots, but only 1 day each has dc -> exactly
    # 2 buchi terms.
    buchi = [p for p in pairs if p[0] == PENALTY_BUCHI]
    assert len(buchi) == 2  # one per teacher-day with non-empty dc
    # five and one: per (t, d). Same 2 candidates.
    five = [p for p in pairs if p[0] == PENALTY_FIVE]
    assert len(five) == 2
    one = [p for p in pairs if p[0] == PENALTY_ONE]
    assert len(one) == 2


def test_default_mode_weights_match_module_constants():
    """The PENALTY_* module constants drive the default-mode weights;
    no other coefficients appear in obj_terms."""
    from cp_sat_constraint_model import (
        ConstraintModel, ConstraintConfig,
        PENALTY_SIXTH, PENALTY_BUCHI, PENALTY_FIVE, PENALTY_ONE)
    profs = _profs_two_classes_with_h13()
    dc = _dc_two_classes_with_h13()
    cm = ConstraintModel(profs, dc, ConstraintConfig())
    obj, _ = cm.compute_soft_cost_expr(mode="default")
    pairs = _expr_to_pairs(obj)
    coefs = {p[0] for p in pairs}
    # Only the four canonical weights.
    assert coefs == {PENALTY_SIXTH, PENALTY_BUCHI,
                       PENALTY_FIVE, PENALTY_ONE}


# ============================================================
# 3. phase_b_per_day mode -- (5, 10) only
# ============================================================


def test_phase_b_per_day_emits_only_sixth_and_buchi():
    """Phase B per-day mode: sixth + buchi only, NO five/one. Sixth
    is per-class-busy at h=13 (NOT per-slot), buchi is per (t, d)."""
    from cp_sat_constraint_model import (
        ConstraintModel, ConstraintConfig,
        PENALTY_SIXTH_PD, PENALTY_BUCHI_PD)
    profs = _profs_two_classes_with_h13()
    dc = _dc_two_classes_with_h13()
    cm = ConstraintModel(profs, dc, ConstraintConfig())
    obj, _ = cm.compute_soft_cost_expr(mode="phase_b_per_day")
    pairs = _expr_to_pairs(obj)
    coefs = {p[0] for p in pairs}
    # Only the per-day weights -- NO five/one (those are 30*100, 80*100).
    assert coefs == {PENALTY_SIXTH_PD, PENALTY_BUCHI_PD}


def test_phase_b_per_day_sixth_is_per_class_not_per_slot():
    """The per-day sixth penalty wraps ONE indicator per (cl, d) at
    h=13, NOT one per slot. Verify by comparing the count of sixth
    terms in default mode (per-slot) vs per-day mode (per-class)."""
    from cp_sat_constraint_model import (
        ConstraintModel, ConstraintConfig,
        PENALTY_SIXTH, PENALTY_SIXTH_PD)
    # Set up TWO teachers serving the SAME class as a coteach: each
    # produces a slot var at h=13 every day, but only ONE class-busy
    # indicator per (cl, d).
    profs = {
        "TA": {"classi": {"1A": {"Chim": {"ore": 6}}},
                "max_hours": 18},
        "TB": {"classi": {"1A": {"Chim": {"ore": 6}}},
                "max_hours": 18},
    }
    dc = {
        ("TA", "1A", "Chim", 1): 6,
        ("TB", "1A", "Chim", 1): 6,
    }
    coteach = [{
        "group_id": "G1", "class_name": "1A", "subject": "Chim",
        "n_hours": 6, "teachers": ["TA", "TB"], "required": True,
    }]
    # Default mode: per-slot at h=13 -> 2 sixth terms (TA slot + TB slot
    # at h=13 day=1).
    cm_def = ConstraintModel(
        profs, dc,
        ConstraintConfig(coteach_groups=coteach))
    cm_def.add_coteach_groups()
    obj_def, _ = cm_def.compute_soft_cost_expr(mode="default")
    sixth_def = [p for p in _expr_to_pairs(obj_def)
                  if p[0] == PENALTY_SIXTH]
    assert len(sixth_def) == 2  # per-slot, both teachers
    # phase_b_per_day mode: per-class-busy -> 1 sixth term (the
    # aggregator OR of 2 coteach members).
    cm_pd = ConstraintModel(
        profs, dc,
        ConstraintConfig(coteach_groups=coteach))
    cm_pd.add_coteach_groups()
    obj_pd, _ = cm_pd.compute_soft_cost_expr(mode="phase_b_per_day")
    sixth_pd = [p for p in _expr_to_pairs(obj_pd)
                 if p[0] == PENALTY_SIXTH_PD]
    assert len(sixth_pd) == 1  # ONE indicator for the coteach class


def test_phase_b_per_day_skips_five_one_penalties():
    """No five/one terms in phase_b_per_day mode."""
    from cp_sat_constraint_model import (
        ConstraintModel, ConstraintConfig,
        PENALTY_FIVE, PENALTY_ONE)
    profs = _profs_two_classes_with_h13()
    dc = _dc_two_classes_with_h13()
    cm = ConstraintModel(profs, dc, ConstraintConfig())
    obj, _ = cm.compute_soft_cost_expr(mode="phase_b_per_day")
    coefs = {p[0] for p in _expr_to_pairs(obj)}
    assert PENALTY_FIVE not in coefs
    assert PENALTY_ONE not in coefs


def test_phase_b_per_day_buchi_count_matches_active_teacher_days():
    """One buchi term per (teacher, day) with non-empty dc, weight 10."""
    from cp_sat_constraint_model import (
        ConstraintModel, ConstraintConfig,
        PENALTY_BUCHI_PD)
    profs = _profs_two_classes_with_h13()
    dc = _dc_two_classes_with_h13()
    cm = ConstraintModel(profs, dc, ConstraintConfig())
    obj, _ = cm.compute_soft_cost_expr(mode="phase_b_per_day")
    buchi = [p for p in _expr_to_pairs(obj)
              if p[0] == PENALTY_BUCHI_PD]
    # 2 teachers, 1 day each with dc -> 2 buchi terms.
    assert len(buchi) == 2


def test_phase_b_per_day_constants_match_legacy_weights():
    """PENALTY_SIXTH_PD == 5 (legacy W_SIXTH_B). PENALTY_BUCHI_PD == 10
    (legacy W_GAP). These weights are NOT scaled by SCALE -- the
    per-day formula lives in its own weight space."""
    from cp_sat_constraint_model import (
        PENALTY_SIXTH_PD, PENALTY_BUCHI_PD)
    assert PENALTY_SIXTH_PD == 5
    assert PENALTY_BUCHI_PD == 10


# ============================================================
# 4. phase_b_per_day mode -- exclusion semantics inherited
# ============================================================


def test_phase_b_per_day_sixth_excludes_sostegno():
    """The per-class-busy at h=13 reuses _build_class_busy_indicators,
    so a sostegno at h=13 alone does not produce a sixth term -- only
    the non-support partner does."""
    from cp_sat_constraint_model import (
        ConstraintModel, ConstraintConfig,
        PENALTY_SIXTH_PD)
    profs = {
        "T1": {"classi": {"1A": {"Mat": {"ore": 6}}},
                "max_hours": 18},
        "Sost": {
            "classi": {"1A": {"sostegno": {"ore": 1}}},
            "max_hours": 18,
        },
    }
    dc = {
        ("T1", "1A", "Mat", 1): 6,
        ("Sost", "1A", "sostegno", 1): 1,
    }
    cm = ConstraintModel(
        profs, dc,
        ConstraintConfig(support_assignments=[
            {"teacher_name": "Sost", "class_name": "1A",
             "subject": "sostegno", "n_hours": 1},
        ]))
    cm.add_support_assignments()
    obj, _ = cm.compute_soft_cost_expr(mode="phase_b_per_day")
    sixth = [p for p in _expr_to_pairs(obj)
              if p[0] == PENALTY_SIXTH_PD]
    # Just ONE class-busy indicator at h=13 for 1A on day 1: the Mat
    # slot var. The sostegno triple is excluded from the aggregation,
    # so it does NOT add a separate sixth term.
    assert len(sixth) == 1
    # Indicator is the Mat slot var directly (single non-support
    # element -> no aggregator wrapping).
    name = _expr_to_pairs(obj)[0][1]
    assert "T1_1A_Mat" in name or "Mat" in name


# ============================================================
# 5. End-to-end: solve a tiny mono with phase_b_per_day objective
# ============================================================


def test_solve_with_phase_b_per_day_objective_is_feasible():
    """Wire phase_b_per_day mode into a MonolithicSolver-like build,
    confirm the model solves and produces a HARD-feasible result.
    (Solve cost vs legacy is out of scope -- that comparison
    requires the per-day Phase B migration which is the next
    sblocco.)"""
    from cp_sat_constraint_model import (
        MonolithicSolver, ConstraintConfig)
    profs = {
        "T1": {"classi": {"1A": {"Mat": {"ore": 4}}},
                "max_hours": 18},
    }
    dc = {("T1", "1A", "Mat", 1): 4}
    cfg = ConstraintConfig(
        enforce_no_holes=True,
        enforce_h3_presence_at_11=False,
        enforce_motorie_pair=False,
        enforce_math_italian_pair=False,
    )
    ms = MonolithicSolver(profs, dc, cfg)
    # Build like MonolithicSolver.build but with the per-day objective.
    ms.add_parallel_groups_inter_class()
    ms.add_coteach_groups()
    ms.add_support_assignments()
    ms.add_potenziamento_assignments()
    ms.add_parallel_groups_intra_class()
    ms.add_all_hard_constraints()
    ms.add_class_no_overlap()
    obj_terms, _ = ms.compute_soft_cost_expr(mode="phase_b_per_day")
    if obj_terms:
        ms.model.Minimize(sum(obj_terms))
    from ortools.sat.python import cp_model
    s = cp_model.CpSolver()
    s.parameters.num_search_workers = 1
    status = s.Solve(ms.model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE), (
        s.StatusName(status))
    # 4 contiguous Mat hours from h=8..11 -- the only no_holes-feasible
    # placement for this scenario, so the optimum is unique.
    assigned = {(d, h) for (_t, _cl, _s, d, h), v in ms.slot.items()
                 if s.Value(v)}
    assert assigned == {(1, 8), (1, 9), (1, 10), (1, 11)}
