"""End-to-end API tests for the /api/plessi router (P4 backend).

Exercises the FastAPI TestClient against the temp-db fixture:
  - CRUD on /api/plessi
  - CRUD on /api/plessi/commuting-rules
  - CRUD on /api/plessi/entity-policies
  - GET /api/plessi/validate
"""
from __future__ import annotations


def test_plessi_crud_round_trip(client):
    # Empty list to start.
    r = client.get("/api/plessi")
    assert r.status_code == 200, r.text
    assert r.json() == []

    # POST creates.
    r = client.post("/api/plessi", json={
        "name": "Sede Centrale", "code": "C",
        "address": "Via Centrale 1", "notes": "main",
    })
    assert r.status_code == 200, r.text
    pid = r.json()["id"]

    # GET single.
    r = client.get(f"/api/plessi/{pid}")
    assert r.status_code == 200
    assert r.json()["name"] == "Sede Centrale"

    # PUT updates.
    r = client.put(f"/api/plessi/{pid}", json={
        "name": "Sede Principale", "code": "C",
        "address": None, "notes": None,
    })
    assert r.status_code == 200
    assert r.json()["name"] == "Sede Principale"

    # LIST shows it.
    r = client.get("/api/plessi")
    assert any(p["id"] == pid for p in r.json())

    # DELETE removes.
    r = client.delete(f"/api/plessi/{pid}")
    assert r.status_code == 204
    r = client.get(f"/api/plessi/{pid}")
    assert r.status_code == 404


def test_commuting_rule_crud_round_trip(client):
    # Create two plessi to reference.
    r1 = client.post("/api/plessi", json={"name": "A", "code": "A"})
    r2 = client.post("/api/plessi", json={"name": "B", "code": "B"})
    p1 = r1.json()["id"]
    p2 = r2.json()["id"]

    # Initially no rules.
    assert client.get("/api/plessi/commuting-rules").json() == []

    # Create.
    r = client.post("/api/plessi/commuting-rules", json={
        "from_plesso_id": p1, "to_plesso_id": p2,
        "entity_kind": "teacher", "entity_id": None,
        "min_gap_hours": 1, "symmetric": True, "priority": 0,
    })
    assert r.status_code == 200, r.text
    rid = r.json()["id"]

    # Filter by entity_kind.
    rl = client.get(
        "/api/plessi/commuting-rules?entity_kind=teacher")
    assert any(rr["id"] == rid for rr in rl.json())
    rl_other = client.get(
        "/api/plessi/commuting-rules?entity_kind=class")
    assert all(rr["entity_kind"] == "class" for rr in rl_other.json())

    # Update.
    r = client.put(f"/api/plessi/commuting-rules/{rid}", json={
        "from_plesso_id": p1, "to_plesso_id": p2,
        "entity_kind": "teacher", "entity_id": None,
        "min_gap_hours": 2, "symmetric": True, "priority": 5,
    })
    assert r.status_code == 200, r.text
    assert r.json()["min_gap_hours"] == 2

    # Delete.
    r = client.delete(f"/api/plessi/commuting-rules/{rid}")
    assert r.status_code == 204


def test_entity_policy_crud_round_trip(client):
    r1 = client.post("/api/plessi", json={"name": "A", "code": "A"})
    p1 = r1.json()["id"]

    # Create kind-wide.
    r = client.post("/api/plessi/entity-policies", json={
        "entity_kind": "teacher", "entity_id": None,
        "policy": "single_plesso_per_day",
        "plesso_id": None, "priority": 0,
    })
    assert r.status_code == 200, r.text
    pid = r.json()["id"]

    # Create per-class with single_total.
    r = client.post("/api/plessi/entity-policies", json={
        "entity_kind": "class", "entity_id": None,
        "policy": "single_plesso_total",
        "plesso_id": p1, "priority": 10,
    })
    assert r.status_code == 200, r.text

    # List, filter.
    rl = client.get("/api/plessi/entity-policies")
    assert len(rl.json()) == 2

    rl_t = client.get(
        "/api/plessi/entity-policies?entity_kind=teacher")
    assert len(rl_t.json()) == 1
    assert rl_t.json()[0]["policy"] == "single_plesso_per_day"

    # Update.
    r = client.put(f"/api/plessi/entity-policies/{pid}", json={
        "entity_kind": "teacher", "entity_id": None,
        "policy": "any", "plesso_id": None, "priority": 1,
    })
    assert r.status_code == 200, r.text
    assert r.json()["policy"] == "any"

    # Delete.
    r = client.delete(f"/api/plessi/entity-policies/{pid}")
    assert r.status_code == 204


def test_validate_endpoint_returns_ok_when_clean(client):
    """Empty configuration -> /api/plessi/validate returns ok=True."""
    r = client.get("/api/plessi/validate")
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    assert r.json()["violations"] == []


def test_validate_endpoint_reports_violations(client):
    """A bad rule surfaces in the validation endpoint."""
    r1 = client.post("/api/plessi", json={"name": "A", "code": "A"})
    p1 = r1.json()["id"]
    # Create a rule with negative gap (invalid).
    client.post("/api/plessi/commuting-rules", json={
        "from_plesso_id": p1, "to_plesso_id": p1,  # same OK
        "entity_kind": "teacher", "entity_id": None,
        "min_gap_hours": -1,
    })
    r = client.get("/api/plessi/validate")
    assert r.json()["ok"] is False
    assert any("min_gap_hours" in m for m in r.json()["violations"])


def test_classroom_payload_accepts_plesso_id(client):
    """The classroom endpoint must accept plesso_id in payload
    (P4 extension on /api/classrooms)."""
    r1 = client.post("/api/plessi", json={"name": "C", "code": "C"})
    p1 = r1.json()["id"]
    # Create a classroom with plesso_id.
    r = client.post("/api/classrooms", json={
        "name": "Aula 1",
        "kind": "standard",
        "capacity": 30,
        "multi_class": False,
        "multi_class_max": 1,
        "multi_class_pref": 1,
        "multi_class_pref_weight": 10.0,
        "plesso_id": p1,
        "tags": [],
        "subject_prefs": [],
        "class_prefs": [],
        "unavailability": [],
    })
    assert r.status_code == 200, r.text
    cl_id = r.json()["id"]

    # GET back: plesso_id must be there.
    r = client.get(f"/api/classrooms/{cl_id}")
    if r.status_code != 200:
        # Some classroom routers expose only the list endpoint.
        r = client.get("/api/classrooms")
        assert r.status_code == 200
        match = next((c for c in r.json() if c["id"] == cl_id), None)
        assert match is not None
        assert match["plesso_id"] == p1
    else:
        assert r.json()["plesso_id"] == p1
