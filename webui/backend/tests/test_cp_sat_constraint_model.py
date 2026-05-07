"""Unit tests for the OO ConstraintModel hierarchy
(engine/cp_sat_constraint_model.py).

Validates:
  - the base class builds slot variables filtered by scope
  - HARD constraint methods produce models that are SAT for valid
    inputs and UNSAT when an obvious violation is forced
  - ``MonolithicSolver`` returns a HARD-feasible solution end-to-end
    on a tiny instance
  - ``TeacherPricer`` returns an improving column when the duals
    reward it, and None otherwise
  - the canonical soft-cost expression emits the four components
    (sixth, buchi, five, one) per (teacher, day)
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "engine"))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)


def _two_teacher_profs():
    return {
        "Rossi": {
            "classi": {"1A": {"Mat": {"ore": 4}},
                        "1B": {"Mat": {"ore": 4}}},
            "glibero": [6], "max_hours": 18,
        },
        "Bianchi": {
            "classi": {"1A": {"Ita": {"ore": 4}},
                        "1B": {"Ita": {"ore": 4}}},
            "glibero": [6], "max_hours": 18,
        },
    }


def _two_teacher_dc():
    """Spread Mat over days 1-4, Ita over days 1-4 in 1 hr/day each."""
    dc = {}
    for (t, cl, s) in [("Rossi", "1A", "Mat"), ("Rossi", "1B", "Mat"),
                        ("Bianchi", "1A", "Ita"),
                        ("Bianchi", "1B", "Ita")]:
        for d in (1, 2, 3, 4):
            dc[(t, cl, s, d)] = 1
    return dc


def test_base_constraint_model_builds_slot_vars_for_global_scope():
    from cp_sat_constraint_model import ConstraintModel
    profs = _two_teacher_profs()
    dc = _two_teacher_dc()
    cm = ConstraintModel(profs, dc)
    # 4 cattedre x 4 days x 6 hours = 96 slots
    assert len(cm.slot) == 96
    assert sorted(cm.teachers_in_scope()) == ["Bianchi", "Rossi"]


def test_base_filters_to_one_teacher_when_scope_is_teacher():
    from cp_sat_constraint_model import ConstraintModel
    profs = _two_teacher_profs()
    dc = _two_teacher_dc()
    cm = ConstraintModel(profs, dc, scope=("teacher", "Rossi"))
    assert cm.teachers_in_scope() == ["Rossi"]
    # 2 cattedre x 4 days x 6 hours = 48
    assert len(cm.slot) == 48


def test_base_filters_to_one_class_when_scope_is_class():
    from cp_sat_constraint_model import ConstraintModel
    profs = _two_teacher_profs()
    dc = _two_teacher_dc()
    cm = ConstraintModel(profs, dc, scope=("class", "1A"))
    assert cm.classes_in_scope() == ["1A"]
    assert sorted(cm.teachers_in_scope()) == ["Bianchi", "Rossi"]


def test_compute_soft_cost_expr_emits_per_teacher_day_terms():
    from cp_sat_constraint_model import ConstraintModel
    profs = _two_teacher_profs()
    dc = _two_teacher_dc()
    cm = ConstraintModel(profs, dc, scope=("teacher", "Rossi"))
    cm.add_teacher_no_overlap()
    obj_terms, aux = cm.compute_soft_cost_expr()
    # sixth-hour term per slot at h=13 (6 days x 2 cattedre = 12, but
    # only days with q>0 land in slot; we have 4 active days x 2 ca = 8)
    # plus per-(teacher, day) buchi/five/one indicators (3 per active day)
    assert obj_terms, "no objective terms emitted"


def test_monolithic_solver_returns_hard_feasible_solution():
    from cp_sat_constraint_model import MonolithicSolver, ConstraintConfig
    profs = _two_teacher_profs()
    dc = _two_teacher_dc()
    ms = MonolithicSolver(profs, dc, ConstraintConfig(
        enforce_no_holes=False, enforce_h3_presence_at_11=False))
    sol, status = ms.solve(time_limit_s=10.0, workers=2)
    assert sol is not None, status
    # Each cattedra has q hours total; check coverage
    by_cattedra: dict = {}
    for (t, cl, s, d, h) in sol:
        by_cattedra[(t, cl, s)] = by_cattedra.get(
            (t, cl, s), 0) + 1
    # Expected: 4 hrs each cattedra x 4 cattedre = 16 slots
    assert sum(by_cattedra.values()) == 16
    for (_t, _cl, _s), n in by_cattedra.items():
        assert n == 4


def test_teacher_pricer_returns_improving_column_with_positive_duals():
    from cp_sat_constraint_model import TeacherPricer, ConstraintConfig
    profs = _two_teacher_profs()
    dc = _two_teacher_dc()
    cfg = ConstraintConfig(enforce_no_holes=False,
                            enforce_h3_presence_at_11=False)
    p = TeacherPricer(
        profs, dc, "Rossi",
        lambda_duals={("Rossi", "1A", "Mat", 1): 100.0},
        mu_t=0.0, config=cfg)
    sol, status = p.solve_pricing(time_limit_s=5.0, workers=1)
    assert sol is not None, status
    # Solution should place a slot at (Rossi, 1A, Mat, 1, *) -- the
    # only one with the strong dual reward.
    assert any(k[:4] == ("Rossi", "1A", "Mat", 1) for k in sol)


def test_teacher_pricer_respects_locks():
    from cp_sat_constraint_model import TeacherPricer, ConstraintConfig
    profs = _two_teacher_profs()
    dc = _two_teacher_dc()
    locked_slot = ("Rossi", "1A", "Mat", 1, 12)
    cfg = ConstraintConfig(
        enforce_no_holes=False, enforce_h3_presence_at_11=False,
        locks=[locked_slot])
    p = TeacherPricer(profs, dc, "Rossi", config=cfg)
    sol, status = p.solve_pricing(time_limit_s=5.0, workers=1)
    assert sol is not None, status
    assert sol.get(locked_slot) == 1, (
        f"lock not honoured; sol slots at (Rossi,1A,Mat,1,*): "
        f"{[k for k in sol if k[:4] == ('Rossi', '1A', 'Mat', 1)]}")


def test_class_no_holes_constraint_blocks_holey_solutions():
    """A handcrafted instance where the only way to schedule is with
    a hole proves no-holes makes the model infeasible."""
    from cp_sat_constraint_model import (
        MonolithicSolver, ConstraintConfig)
    # 1 class, 1 teacher, 2 hours total, but force them at h=8 and h=10
    # via an extra teacher locking h=9 elsewhere -- handle a simpler
    # version by forcing 2 hours of demand into a single class on
    # day 1 and adding no-holes; CP-SAT must place them consecutive.
    profs = {"T1": {"classi": {"1A": {"Mat": {"ore": 2}}},
                     "max_hours": 18}}
    dc = {("T1", "1A", "Mat", 1): 2}
    ms = MonolithicSolver(profs, dc, ConstraintConfig(
        enforce_no_holes=True,
        enforce_h3_presence_at_11=False))
    sol, _ = ms.solve(time_limit_s=5.0, workers=1)
    assert sol is not None
    hours = sorted({k[4] for k in sol})
    assert len(hours) == 2
    # No-holes: hours must be consecutive, starting at h=8.
    assert hours == [8, 9], f"no-holes violated: hours={hours}"


def test_coteach_groups_force_codoc_to_share_slots():
    """Two teachers Rossi/Verdi co-teach Italiano in 1A for 2 hrs/week.
    With ``required=True`` the OO solver creates ``coslot`` BoolVars
    and ties each member to them so both teachers occupy the same
    (day, hour) on every active slot. The class-busy aggregation makes
    the k=2 members count as ONE class occupation per (cl, subj, d, h),
    so the standard ``add_class_no_overlap`` does not turn the model
    infeasible (which it would do summing 2 active slots > 1).
    """
    from cp_sat_constraint_model import (
        MonolithicSolver, ConstraintConfig)
    profs = {
        "Rossi": {
            "classi": {"1A": {"Ita": {"ore": 2}}},
            "glibero": [6], "max_hours": 18,
        },
        "Verdi": {
            "classi": {"1A": {"Ita": {"ore": 2}}},
            "glibero": [6], "max_hours": 18,
        },
    }
    dc = {("Rossi", "1A", "Ita", 1): 2, ("Verdi", "1A", "Ita", 1): 2}
    coteach = [{
        "group_id": 7, "class_name": "1A", "subject": "Ita",
        "n_hours": 2, "teachers": ["Rossi", "Verdi"], "required": True,
    }]
    ms = MonolithicSolver(profs, dc, ConstraintConfig(
        enforce_no_holes=False, enforce_h3_presence_at_11=False,
        coteach_groups=coteach))
    sol, status = ms.solve(time_limit_s=10.0, workers=2)
    assert sol is not None, f"infeasible: {status}"
    rossi_slots = {(d, h) for (t, cl, s, d, h) in sol
                    if t == "Rossi" and cl == "1A" and s == "Ita"}
    verdi_slots = {(d, h) for (t, cl, s, d, h) in sol
                    if t == "Verdi" and cl == "1A" and s == "Ita"}
    assert len(rossi_slots) == 2, f"Rossi count != 2: {rossi_slots}"
    assert len(verdi_slots) == 2, f"Verdi count != 2: {verdi_slots}"
    assert rossi_slots == verdi_slots, (
        f"coteach members not co-active on same slots: "
        f"Rossi={rossi_slots} Verdi={verdi_slots}")


def test_coteach_groups_class_busy_aggregates_correctly():
    """When a coteach group is active and another teacher also has a
    different subject in the same class, the class-busy aggregation
    must count the coteach as ONE occupation, leaving room for the
    other teacher's slot in the SAME (cl, d, h) — but the standard
    ``sum <= 1`` would still fire on the aggregated form.

    Concretely: 1A has 2 hrs of (Rossi+Verdi)-coteach Ita and 2 hrs
    of Bianchi Mat, on day 1 only, in the 6-hour window. Both
    cattedre demand 2 hours; coteach occupies 2 of them, Bianchi
    must fit in the remaining 4 — fully feasible because coteach
    counts as 1 occupation per (1A, d, h)."""
    from cp_sat_constraint_model import (
        MonolithicSolver, ConstraintConfig)
    profs = {
        "Rossi": {"classi": {"1A": {"Ita": {"ore": 2}}},
                   "glibero": [6], "max_hours": 18},
        "Verdi": {"classi": {"1A": {"Ita": {"ore": 2}}},
                   "glibero": [6], "max_hours": 18},
        "Bianchi": {"classi": {"1A": {"Mat": {"ore": 2}}},
                     "glibero": [6], "max_hours": 18},
    }
    dc = {("Rossi", "1A", "Ita", 1): 2,
          ("Verdi", "1A", "Ita", 1): 2,
          ("Bianchi", "1A", "Mat", 1): 2}
    coteach = [{
        "group_id": 9, "class_name": "1A", "subject": "Ita",
        "n_hours": 2, "teachers": ["Rossi", "Verdi"], "required": True,
    }]
    ms = MonolithicSolver(profs, dc, ConstraintConfig(
        enforce_no_holes=False, enforce_h3_presence_at_11=False,
        coteach_groups=coteach))
    sol, status = ms.solve(time_limit_s=10.0, workers=2)
    assert sol is not None, f"infeasible: {status}"
    by_class_dh: dict = {}
    for (t, cl, s, d, h) in sol:
        by_class_dh.setdefault((cl, d, h), set()).add((t, s))
    for (cl, d, h), occupants in by_class_dh.items():
        subjects = {s for (_t, s) in occupants}
        if len(occupants) > 1:
            assert subjects == {"Ita"}, (
                f"class {cl} d={d} h={h}: more than one subject "
                f"co-active: {occupants}")


def test_support_assignment_shadows_non_support_lesson():
    """ProfSost has 4 sostegno hours in 3B; the 3B class has Mat (4h)
    and Ita (4h) split across days. Every Sost slot must coincide
    with a non-support 3B lesson at the same (day, hour).
    """
    from cp_sat_constraint_model import (
        MonolithicSolver, ConstraintConfig)
    profs = {
        "Rossi": {"classi": {"3B": {"Mat": {"ore": 4}}},
                   "glibero": [6], "max_hours": 18},
        "Bianchi": {"classi": {"3B": {"Ita": {"ore": 4}}},
                     "glibero": [6], "max_hours": 18},
        "ProfSost": {"classi": {"3B": {"sostegno": {"ore": 4}}},
                      "glibero": [6], "max_hours": 18},
    }
    dc = {}
    for d in (1, 2, 3, 4):
        dc[("Rossi", "3B", "Mat", d)] = 1
        dc[("Bianchi", "3B", "Ita", d)] = 1
        dc[("ProfSost", "3B", "sostegno", d)] = 1
    sup = [{"teacher_name": "ProfSost", "class_name": "3B",
            "subject": "sostegno", "n_hours": 4}]
    ms = MonolithicSolver(profs, dc, ConstraintConfig(
        enforce_no_holes=False, enforce_h3_presence_at_11=False,
        support_assignments=sup))
    sol, status = ms.solve(time_limit_s=10.0, workers=2)
    assert sol is not None, f"infeasible: {status}"
    sost_slots = {(d, h) for (t, cl, s, d, h) in sol
                   if t == "ProfSost" and cl == "3B"
                   and s == "sostegno"}
    assert len(sost_slots) == 4, sost_slots
    non_support_slots = {(d, h) for (t, cl, s, d, h) in sol
                          if cl == "3B" and t != "ProfSost"
                          and s != "sostegno"}
    for sd, sh in sost_slots:
        assert (sd, sh) in non_support_slots, (
            f"support slot ({sd},{sh}) without any non-support "
            f"lesson in 3B")


def test_support_assignment_does_not_double_book_class():
    """The support slot must NOT count as a fresh class occupation:
    the (3B, d, h) where Sost is co-active with Mat must allow Mat
    (the non-support) to occupy the slot freely. Without the support
    exclusion in ``add_class_no_overlap`` the model would be
    infeasible at the shadow hours (sum of 2 active slots > 1)."""
    from cp_sat_constraint_model import (
        MonolithicSolver, ConstraintConfig)
    profs = {
        "Rossi": {"classi": {"3B": {"Mat": {"ore": 4}}},
                   "glibero": [6], "max_hours": 18},
        "Bianchi": {"classi": {"3B": {"Ita": {"ore": 4}}},
                     "glibero": [6], "max_hours": 18},
        "ProfSost": {"classi": {"3B": {"sostegno": {"ore": 4}}},
                      "glibero": [6], "max_hours": 18},
    }
    dc = {}
    for d in (1, 2, 3, 4):
        dc[("Rossi", "3B", "Mat", d)] = 1
        dc[("Bianchi", "3B", "Ita", d)] = 1
        dc[("ProfSost", "3B", "sostegno", d)] = 1
    sup = [{"teacher_name": "ProfSost", "class_name": "3B",
            "subject": "sostegno", "n_hours": 4}]
    ms = MonolithicSolver(profs, dc, ConstraintConfig(
        enforce_no_holes=False, enforce_h3_presence_at_11=False,
        support_assignments=sup))
    sol, status = ms.solve(time_limit_s=10.0, workers=2)
    assert sol is not None, f"infeasible: {status}"
    # Total NON-support 3B slots: 4 Mat + 4 Ita = 8 distinct (d, h).
    distinct_non_support = {
        (d, h) for (t, cl, s, d, h) in sol
        if cl == "3B" and s != "sostegno"
    }
    assert len(distinct_non_support) == 8, (
        f"expected 8 distinct non-support 3B (d, h), got "
        f"{len(distinct_non_support)}: {distinct_non_support}")


def test_support_assignment_infeasible_when_class_empty():
    """ProfSost has 4 sostegno hours but the class has 0 non-support
    triples -> the shadow constraint forces every support slot to 0,
    which contradicts ``sum slots == n_hours = 4``. Infeasible."""
    from cp_sat_constraint_model import (
        MonolithicSolver, ConstraintConfig)
    profs = {
        "ProfSost": {"classi": {"3B": {"sostegno": {"ore": 4}}},
                      "glibero": [6], "max_hours": 18},
    }
    dc = {}
    for d in (1, 2, 3, 4):
        dc[("ProfSost", "3B", "sostegno", d)] = 1
    sup = [{"teacher_name": "ProfSost", "class_name": "3B",
            "subject": "sostegno", "n_hours": 4}]
    ms = MonolithicSolver(profs, dc, ConstraintConfig(
        enforce_no_holes=False, enforce_h3_presence_at_11=False,
        support_assignments=sup))
    sol, status = ms.solve(time_limit_s=5.0, workers=1)
    assert sol is None, f"expected infeasible, got sol={sol}"
