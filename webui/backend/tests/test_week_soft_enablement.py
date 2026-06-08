"""SOFT general_dsl rules must reach the week-mono objective.

The week solver (``_solve_phase_b_week`` -> ``MonolithicSolver``) loads
its constraint stream through ``load_all_dsl_constraints``. Historically
it passed ``include_soft=False`` AND compiled every rule with the
default ``is_hard=True``, so SOFT table rows were either dropped or
silently promoted to HARD.

``MonolithicSolver.build`` already folds ``dsl_soft_cost_terms`` into its
objective and its ``compute_soft_cost_expr`` carries no free-day /
unavailability soft of its own, so wiring SOFT through here is
double-count-safe. These tests pin the contract via the extracted
helper ``optimization._apply_dsl_rules_to_week_solver``.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(HERE)
WEBUI_DIR = os.path.dirname(BACKEND_DIR)
REPO_ROOT = os.path.dirname(WEBUI_DIR)
ENGINE_DIR = os.path.join(REPO_ROOT, "engine")
for p in (WEBUI_DIR, ENGINE_DIR, REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)


def _solver(profs, dc, **cfg):
    from cp_sat_constraint_model import MonolithicSolver, ConstraintConfig
    return MonolithicSolver(profs, dc, ConstraintConfig(**cfg))


def _mem_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from backend.db import Base
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _one_hour_setup():
    profs = {"T1": {"classi": {"1A": {"Mat": {"ore": 1}}}, "max_hours": 18}}
    dc = {("T1", "1A", "Mat", 1): 1}
    return profs, dc


def test_week_soft_rule_steers_solution_away_from_penalized_slot():
    """A SOFT teacher-unavailability on (day1, h8) with a high weight
    makes the solver place the single hour somewhere else (the slot is
    avoidable, so it pays nothing)."""
    from backend import models
    from backend.optimization import _apply_dsl_rules_to_week_solver

    db = _mem_db()
    t = models.Teacher(name="T1", min_free_days=0, max_consecutive=6)
    db.add(t)
    db.commit()
    db.add(models.TeacherUnavailability(
        teacher_id=t.id, day=1, hour=8, state="soft", soft_penalty=1000))
    db.commit()

    profs, dc = _one_hour_setup()
    ms = _solver(profs, dc, enforce_no_holes=False)
    _apply_dsl_rules_to_week_solver(ms, db)
    sol, status = ms.solve(time_limit_s=5.0, workers=1)
    assert sol is not None, status
    placed = [(k[3], k[4]) for k in sol]
    assert (1, 8) not in placed, (
        f"soft-penalized slot (d1,h8) should be avoided: {placed}")


def test_week_soft_rule_on_only_slot_stays_feasible():
    """When a SOFT rule lands on the ONLY feasible slot, the model must
    stay FEASIBLE (pay the penalty) -- a SOFT rule must never be
    promoted to HARD."""
    from backend import models
    from backend.optimization import _apply_dsl_rules_to_week_solver

    db = _mem_db()
    t = models.Teacher(name="T1", min_free_days=0, max_consecutive=6)
    db.add(t)
    db.commit()
    for h in (9, 10, 11, 12, 13):
        db.add(models.TeacherUnavailability(
            teacher_id=t.id, day=1, hour=h, state="hard"))
    db.add(models.TeacherUnavailability(
        teacher_id=t.id, day=1, hour=8, state="soft", soft_penalty=1000))
    db.commit()

    profs, dc = _one_hour_setup()
    ms = _solver(profs, dc, enforce_no_holes=False)
    _apply_dsl_rules_to_week_solver(ms, db)
    sol, status = ms.solve(time_limit_s=5.0, workers=1)
    assert sol is not None, (
        f"a SOFT rule must not be promoted to HARD; got {status}")
    placed = [(k[3], k[4]) for k in sol]
    assert (1, 8) in placed, (
        f"the only feasible slot (d1,h8) must be used despite the soft "
        f"penalty: {placed}")
