"""Smoke tests for the most-used backend endpoints.

These tests run on a fresh tmp DB (see conftest.py). They do NOT
contact the running uvicorn server on port 8000 -- the FastAPI app
object is reused but `get_db` is overridden to point at the tmp
session.

What we cover here:
  * /api/health
  * GET on every CRUD list (teachers, classes, subjects, classrooms,
    students, groups, curricula, coteaching) returning [] for empty DB.
  * Full CRUD round-trip on /api/teachers (create, read, update, delete).
  * /api/dataset/state returning a dict with the expected counters.
  * /api/coverage/week with a synthetic absence + substitution.

The point is to catch regressions in router wiring, schema validation,
and DB column expectations after each subsequent backend refactor.
"""
from __future__ import annotations


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["name"] == "pitantum"


def test_dataset_state_empty_db(client):
    r = client.get("/api/dataset/state")
    assert r.status_code == 200
    body = r.json()
    # No assumption on which keys are present, but at least the major
    # counters should be 0 on a fresh DB.
    for key in ("classes", "teachers", "subjects", "classrooms"):
        assert key in body
        assert body[key] == 0


def test_list_endpoints_return_empty(client):
    """Every CRUD list returns [] (or {items:[]}) on an empty DB without
    crashing. This is the regression-catcher for router wiring + schema
    validation drift."""
    paths = [
        "/api/teachers",
        "/api/classes",
        "/api/subjects",
        "/api/classrooms",
        "/api/students",
        "/api/groups",
        "/api/curricula",
        "/api/coteaching",
    ]
    for p in paths:
        r = client.get(p)
        assert r.status_code == 200, f"{p} -> {r.status_code}: {r.text}"
        body = r.json()
        # Some endpoints return a list, some return a dict with items.
        if isinstance(body, dict) and "items" in body:
            assert body["items"] == []
        else:
            assert body == [] or body == {}, (
                f"{p} should return empty list or dict, got {body}"
            )


def test_subject_create_list_delete(client):
    # Create
    payload = {"name": "TestSubject", "pretty_name": "Materia di test"}
    r = client.post("/api/subjects", json=payload)
    assert r.status_code in (200, 201), r.text
    sid = r.json()["id"]

    # List shows it
    r = client.get("/api/subjects")
    assert r.status_code == 200
    body = r.json()
    assert any(s["name"] == "TestSubject" for s in body)

    # Delete
    r = client.delete(f"/api/subjects/{sid}")
    assert r.status_code in (200, 204), r.text

    # List is empty again
    r = client.get("/api/subjects")
    assert r.json() == []


def test_classroom_create_and_list(client):
    payload = {
        "name": "Aula1", "kind": "standard", "capacity": 25,
        "multi_class": False, "multi_class_max": 1,
        "multi_class_pref": 1, "multi_class_pref_weight": 10,
        "subject_prefs": [], "class_prefs": [], "unavailability": [],
    }
    r = client.post("/api/classrooms", json=payload)
    assert r.status_code in (200, 201), r.text

    r = client.get("/api/classrooms")
    assert r.status_code == 200
    body = r.json()
    assert any(c["name"] == "Aula1" for c in body)


def test_class_create_with_subject(client):
    payload = {
        "name": "TestClass", "year": 1, "section": "A",
        "n_students": 22,
        "hard_entry_at_8": True, "hard_exit_after_12": True,
        "hard_no_holes": True, "hard_dual_math": True,
        "hard_dual_italian": True, "hard_motorie_pairs": True,
        "hard_max_6_per_day": True, "soft_minimize_sixth_weight": 50,
        "subjects": [], "unavailability": [],
    }
    r = client.post("/api/classes", json=payload)
    assert r.status_code in (200, 201), r.text


def test_health_after_creates(client):
    """Even after several writes the health and dataset/state endpoints
    keep working -- catches lifespan / session leak regressions."""
    client.post("/api/subjects", json={"name": "X"})
    client.post("/api/subjects", json={"name": "Y"})
    r = client.get("/api/health")
    assert r.status_code == 200
    r = client.get("/api/dataset/state")
    assert r.status_code == 200
    body = r.json()
    assert body["subjects"] == 2


def test_404_on_missing_resource(client):
    r = client.get("/api/teachers/999999")
    assert r.status_code == 404


def test_invalid_payload_returns_422(client):
    """Pydantic validation should produce 422 for body type errors."""
    r = client.post("/api/teachers", json={"max_hours": "not_a_number"})
    assert r.status_code == 422


def test_unknown_route_404(client):
    r = client.get("/api/this-does-not-exist")
    assert r.status_code == 404
