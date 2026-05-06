"""Tests for engine/dsl_translator.py — converts special-purpose
constraint tables (TeacherUnavailability, ClassUnavailability,
ClassroomUnavailability, TeacherMandatoryFreeDay, CoteachGroup,
LogicalUnavailability, CurriculumLogicalConstraint) into generic DSL
expressions consumed uniformly by ``DSLConstraintCompiler``.

The tests verify:
  - each translator produces a DSL string the parser can read
  - the parsed AST compiles to CP-SAT constraints that enforce the
    original semantics on a tiny instance
  - load_all_dsl_constraints aggregates DB rows from every supported
    table without choking on missing optional models
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


def _basic_profs():
    return {"Rossi": {"classi": {"1A": {"Mat": {"ore": 4}}},
                       "max_hours": 18}}


def _basic_dc():
    return {("Rossi", "1A", "Mat", d): 1 for d in (1, 2, 3, 4)}


# ----- per-translator round-trip tests -----


def test_teacher_unavail_to_dsl_parses_and_enforces():
    """Translator output must be valid DSL the compiler accepts."""
    import dsl_translator as dt
    from cp_sat_constraint_model import (
        MonolithicSolver, ConstraintConfig)
    from webui.backend.utils import general_dsl as gd
    expr = dt.teacher_unavailability_to_dsl("Rossi", 2, 9)
    # Parses without error
    tree = gd.parse(expr)
    assert tree is not None
    # Compile + check enforcement
    profs = _basic_profs()
    dc = _basic_dc()
    ms = MonolithicSolver(profs, dc, ConstraintConfig(
        enforce_no_holes=False, enforce_h3_presence_at_11=False))
    ms.add_dsl_constraint(expr)
    sol, status = ms.solve(time_limit_s=5.0, workers=1)
    assert sol is not None, status
    # No slot at (Rossi, _, _, 2, 9) should remain.
    assert all(not (k[0] == "Rossi" and k[3] == 2 and k[4] == 9)
                for k in sol)


def test_class_unavail_to_dsl_enforces():
    import dsl_translator as dt
    from cp_sat_constraint_model import (
        MonolithicSolver, ConstraintConfig)
    expr = dt.class_unavailability_to_dsl("1A", 1, 8)
    profs = _basic_profs()
    dc = {("Rossi", "1A", "Mat", 1): 1}
    ms = MonolithicSolver(profs, dc, ConstraintConfig(
        enforce_no_holes=False, enforce_h3_presence_at_11=False))
    ms.add_dsl_constraint(expr)
    sol, status = ms.solve(time_limit_s=5.0, workers=1)
    assert sol is not None, status
    assert (("Rossi", "1A", "Mat", 1, 8)) not in sol
    # The 1 hour got placed somewhere else (h != 8 on day 1).
    assert sum(1 for k in sol if k[3] == 1) == 1


def test_teacher_mandatory_free_day_to_dsl_zeroes_the_day():
    import dsl_translator as dt
    from cp_sat_constraint_model import (
        MonolithicSolver, ConstraintConfig)
    expr = dt.teacher_mandatory_free_day_to_dsl("Rossi", 3)
    profs = _basic_profs()
    # 1 hr on day 3 only -> infeasible if day 3 is forbidden
    dc = {("Rossi", "1A", "Mat", 3): 1}
    ms = MonolithicSolver(profs, dc, ConstraintConfig(
        enforce_no_holes=False, enforce_h3_presence_at_11=False))
    ms.add_dsl_constraint(expr)
    sol, status = ms.solve(time_limit_s=5.0, workers=1)
    assert sol is None and status == "INFEASIBLE"


def test_teacher_mandatory_free_day_with_alternative_days():
    """When the demand can be placed elsewhere, the rule just
    forbids the named day."""
    import dsl_translator as dt
    from cp_sat_constraint_model import (
        MonolithicSolver, ConstraintConfig)
    expr = dt.teacher_mandatory_free_day_to_dsl("Rossi", 3)
    profs = _basic_profs()
    dc = {("Rossi", "1A", "Mat", 1): 1, ("Rossi", "1A", "Mat", 2): 1}
    ms = MonolithicSolver(profs, dc, ConstraintConfig(
        enforce_no_holes=False, enforce_h3_presence_at_11=False))
    ms.add_dsl_constraint(expr)
    sol, status = ms.solve(time_limit_s=5.0, workers=1)
    assert sol is not None, status
    days = {k[3] for k in sol}
    assert 3 not in days


# ----- Coteach pair-clause translator -----


def test_coteach_group_to_dsl_produces_per_teacher_count_clauses():
    """Coteach is a multi-clause translation: count == n_hours per
    teacher + slot-equality between principal and each codoc."""
    import dsl_translator as dt
    from webui.backend.utils import general_dsl as gd
    clauses = dt.coteach_group_to_dsl(
        "1A", "Mat", ["Rossi", "Bianchi"], 2, required=True)
    assert len(clauses) == 3, (
        f"expected 1 count-per-teacher (2) + 1 pair (1) = 3 clauses; "
        f"got {clauses}")
    for c in clauses:
        # Every clause parses cleanly.
        gd.parse(c)


def test_coteach_group_skip_when_fewer_than_two_teachers():
    import dsl_translator as dt
    assert dt.coteach_group_to_dsl(
        "1A", "Mat", ["Rossi"], 2, required=True) == []
    assert dt.coteach_group_to_dsl(
        "1A", "Mat", [], 2, required=True) == []


# ----- DB loader -----


def test_load_all_dsl_constraints_aggregates_clean_db(client_and_session):
    """Empty DB returns no rules without errors (defensive shape:
    the loader skips tables that have no rows)."""
    import dsl_translator as dt
    client, TestSession = client_and_session
    with TestSession() as db:
        rules = dt.load_all_dsl_constraints(db)
    assert rules == []


def test_load_all_dsl_constraints_includes_teacher_unavail(
    client_and_session,
):
    """A TeacherUnavailability row appears as a 'teacher_unavailability'
    source in the loader output, with parseable DSL."""
    from webui.backend import models
    from webui.backend.utils import general_dsl as gd
    import dsl_translator as dt
    client, TestSession = client_and_session
    # Persist a teacher + an unavailability cell.
    with TestSession() as db:
        t = models.Teacher(name="Rossi", max_hours=18)
        db.add(t)
        db.flush()
        db.add(models.TeacherUnavailability(
            teacher_id=t.id, day=2, hour=10, state="hard"))
        db.commit()
    with TestSession() as db:
        rules = dt.load_all_dsl_constraints(db)
    assert any(r["source"] == "teacher_unavailability"
                for r in rules), rules
    # DSL parses.
    tu = next(r for r in rules
              if r["source"] == "teacher_unavailability")
    gd.parse(tu["expression"])
    assert tu["is_hard"] is True


@pytest.fixture
def client_and_session(app_with_temp_db):
    """Returns (TestClient, TestSession) bound to the same temp DB
    so engine-side code can read what the API just wrote."""
    from fastapi.testclient import TestClient
    app, TestSession = app_with_temp_db
    return TestClient(app), TestSession
