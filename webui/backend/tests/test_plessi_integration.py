"""Integration test for the PLESSI feature, end-to-end.

Exercises the full flow as the API + engine see it:
  1. Create plessi, classrooms (with plesso_id), commuting rules,
     and entity policies through the FastAPI TestClient.
  2. Run /api/plessi/validate and assert it is OK.
  3. Build a synthetic lesson set and call
     engine/classroom_assignment.solve_classroom_assignment with
     plessi_data loaded from the same TestSession the API wrote to.
  4. Assert the returned mapping respects the rules.

This complements test_plessi_api.py (CRUD only) and
test_plessi_classroom_assignment.py (engine only) by glueing the
two together through the live ORM models on the temp DB.
"""
from __future__ import annotations

import os
import sys

import pytest
from fastapi.testclient import TestClient

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(HERE)
WEBUI_DIR = os.path.dirname(BACKEND_DIR)
REPO_ROOT = os.path.dirname(WEBUI_DIR)
ENGINE_DIR = os.path.join(REPO_ROOT, "engine")
for p in (WEBUI_DIR, ENGINE_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture
def client_and_session(app_with_temp_db):
    """Returns (TestClient, TestSession) bound to the same temp DB
    so engine-side code can read what the API just wrote."""
    from backend.utils import ttl_cache
    ttl_cache.clear()
    app, TestSession = app_with_temp_db
    return TestClient(app), TestSession


def _make_rooms_with_plessi(client) -> dict[str, int]:
    """Create two plessi (A, B) and four classrooms (A1, A2, B1,
    B2) with the right plesso_id. Returns {plesso_code -> id}."""
    pa = client.post("/api/plessi", json={
        "name": "Centrale", "code": "A"}).json()
    pb = client.post("/api/plessi", json={
        "name": "Garibaldi", "code": "B"}).json()
    for n, pid in [("A1", pa["id"]), ("A2", pa["id"]),
                    ("B1", pb["id"]), ("B2", pb["id"])]:
        r = client.post("/api/classrooms", json={
            "name": n, "kind": "standard", "capacity": 30,
            "multi_class": False, "multi_class_max": 1,
            "multi_class_pref": 1, "multi_class_pref_weight": 10.0,
            "plesso_id": pid, "tags": [],
            "subject_prefs": [], "class_prefs": [],
            "unavailability": [],
        })
        assert r.status_code == 200, r.text
    return {"A": pa["id"], "B": pb["id"]}


def test_validate_ok_with_complete_setup(client_and_session):
    """Full setup: 2 plessi + 4 rooms + 1 commuting rule. Validation
    must report ok."""
    client, _ = client_and_session
    p_ids = _make_rooms_with_plessi(client)
    client.post("/api/plessi/commuting-rules", json={
        "from_plesso_id": p_ids["A"],
        "to_plesso_id": p_ids["B"],
        "entity_kind": "teacher", "entity_id": None,
        "min_gap_hours": 1, "symmetric": True, "priority": 0,
    })
    r = client.get("/api/plessi/validate")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True, body["violations"]


def test_load_plessi_data_after_api_setup(client_and_session):
    """After populating plessi + classrooms via the API, the engine
    loader produces a PlessiData snapshot that exposes the correct
    classroom_to_plesso map."""
    client, TestSession = client_and_session
    p_ids = _make_rooms_with_plessi(client)
    import plessi_constraints as pc

    with TestSession() as db:
        snap = pc.load_plessi_data(db)
    assert snap.classroom_to_plesso["A1"] == p_ids["A"]
    assert snap.classroom_to_plesso["A2"] == p_ids["A"]
    assert snap.classroom_to_plesso["B1"] == p_ids["B"]
    assert snap.classroom_to_plesso["B2"] == p_ids["B"]


def test_classroom_solver_respects_db_commuting_rule(
    client_and_session,
):
    """Round-trip: persist a commuting rule via API, load it through
    load_plessi_data, run solve_classroom_assignment, verify the rule
    is honoured."""
    client, TestSession = client_and_session
    from classroom_assignment import solve_classroom_assignment
    import plessi_constraints as pc

    p_ids = _make_rooms_with_plessi(client)
    tr = client.post("/api/teachers", json={
        "name": "ProfRossi", "max_hours_per_week": 18,
        "max_hours_per_day": 6, "free_day": None,
    })
    assert tr.status_code in (200, 201), tr.text

    client.post("/api/plessi/commuting-rules", json={
        "from_plesso_id": p_ids["A"],
        "to_plesso_id": p_ids["B"],
        "entity_kind": "teacher", "entity_id": None,
        "min_gap_hours": 1, "symmetric": True, "priority": 0,
    })

    lessons = [
        {"teacher": "ProfRossi", "co_teachers": [],
         "class": "1A", "subject": "Mate", "day": 1, "hour": 8},
        {"teacher": "ProfRossi", "co_teachers": [],
         "class": "1B", "subject": "Mate", "day": 1, "hour": 9},
    ]
    rooms_dicts = [
        {"name": n, "kind": "standard", "capacity": 30,
         "multi_class": False, "multi_class_max": 1,
         "unavailability": set(), "subject_required": set(),
         "subject_pref_weight": {}, "class_pref_weight": {},
         "is_home_for": set()}
        for n in ("A1", "A2", "B1", "B2")
    ]
    with TestSession() as db:
        snap = pc.load_plessi_data(db)
    out, status = solve_classroom_assignment(
        lessons, rooms_dicts, time_limit_s=5.0, workers=1,
        plessi_data=snap)
    assert out is not None, status
    pl_a = snap.classroom_to_plesso[out[("1A", "Mate", 1, 8)]]
    pl_b = snap.classroom_to_plesso[out[("1B", "Mate", 1, 9)]]
    assert pl_a == pl_b, (
        f"adjacent crossing not blocked: {pl_a} -> {pl_b}")


def test_check_active_solution_no_active_returns_ok(client_and_session):
    """When no solution is active the endpoint returns ok=True with
    empty violations -- the UI does not need a special-case path."""
    client, _ = client_and_session
    r = client.get("/api/plessi/check-active-solution")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["violations"] == []


def test_check_active_solution_clean_returns_no_violations(
    client_and_session,
):
    """A solution that respects every plessi rule produces an empty
    violations list."""
    from backend import models
    client, TestSession = client_and_session
    p_ids = _make_rooms_with_plessi(client)
    # Persist a tiny "active solution" with two lessons in the same
    # plesso so no rule fires.
    with TestSession() as db:
        sol = models.Solution(name="t", kind="phase_b",
                               is_active=True)
        db.add(sol)
        db.flush()
        for (cl, subj, d, h, room) in [
            ("1A", "Mate", 1, 8, "A1"),
            ("1A", "Mate", 1, 9, "A2"),
        ]:
            db.add(models.Lesson(
                solution_id=sol.id,
                teacher_name="Rossi", class_name=cl, subject=subj,
                day=d, hour=h, classroom_name=room))
        db.commit()
    # Add a kind-wide commuting rule that WOULD fire on a cross.
    client.post("/api/plessi/commuting-rules", json={
        "from_plesso_id": p_ids["A"],
        "to_plesso_id": p_ids["B"],
        "entity_kind": "teacher", "entity_id": None,
        "min_gap_hours": 1, "symmetric": True, "priority": 0,
    })
    r = client.get("/api/plessi/check-active-solution")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["violations"] == []
    assert body["n_lessons_audited"] == 2


def test_check_active_solution_flags_commuting_violation(
    client_and_session,
):
    """A solution that violates a teacher commuting rule is flagged
    by the endpoint."""
    from backend import models
    client, TestSession = client_and_session
    p_ids = _make_rooms_with_plessi(client)
    client.post("/api/plessi/commuting-rules", json={
        "from_plesso_id": p_ids["A"],
        "to_plesso_id": p_ids["B"],
        "entity_kind": "teacher", "entity_id": None,
        "min_gap_hours": 1, "symmetric": True, "priority": 0,
    })
    with TestSession() as db:
        sol = models.Solution(name="t", kind="phase_b",
                               is_active=True)
        db.add(sol)
        db.flush()
        # Same teacher, adjacent hours, different plessi -- violation.
        for (cl, subj, d, h, room) in [
            ("1A", "Mate", 1, 8, "A1"),
            ("1B", "Mate", 1, 9, "B1"),
        ]:
            db.add(models.Lesson(
                solution_id=sol.id,
                teacher_name="Rossi", class_name=cl, subject=subj,
                day=d, hour=h, classroom_name=room))
        db.commit()
    r = client.get("/api/plessi/check-active-solution")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False
    assert any(v["kind"] == "commuting"
               and v["entity_kind"] == "teacher"
               and v["entity_name"] == "Rossi"
               for v in body["violations"])


def test_classroom_solver_respects_db_single_plesso_total_policy(
    client_and_session,
):
    """Persist a single_plesso_total policy via API; assert every
    room assigned to the teacher belongs to the target plesso."""
    client, TestSession = client_and_session
    from classroom_assignment import solve_classroom_assignment
    import plessi_constraints as pc

    p_ids = _make_rooms_with_plessi(client)
    tr = client.post("/api/teachers", json={
        "name": "ProfBianchi", "max_hours_per_week": 18,
        "max_hours_per_day": 6, "free_day": None,
    })
    assert tr.status_code in (200, 201), tr.text
    teacher_id = tr.json()["id"]

    client.post("/api/plessi/entity-policies", json={
        "entity_kind": "teacher", "entity_id": teacher_id,
        "policy": "single_plesso_total",
        "plesso_id": p_ids["B"], "priority": 0,
    })

    lessons = [
        {"teacher": "ProfBianchi", "co_teachers": [],
         "class": "1A", "subject": "Sto", "day": 2, "hour": 8},
        {"teacher": "ProfBianchi", "co_teachers": [],
         "class": "1B", "subject": "Sto", "day": 4, "hour": 11},
    ]
    rooms_dicts = [
        {"name": n, "kind": "standard", "capacity": 30,
         "multi_class": False, "multi_class_max": 1,
         "unavailability": set(), "subject_required": set(),
         "subject_pref_weight": {}, "class_pref_weight": {},
         "is_home_for": set()}
        for n in ("A1", "A2", "B1", "B2")
    ]
    with TestSession() as db:
        snap = pc.load_plessi_data(db)
    out, status = solve_classroom_assignment(
        lessons, rooms_dicts, time_limit_s=5.0, workers=1,
        plessi_data=snap)
    assert out is not None, status
    for k, v in out.items():
        assert snap.classroom_to_plesso[v] == p_ids["B"], (
            f"{k} -> {v} not in target plesso")
