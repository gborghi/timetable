"""Tests for /api/dashboard/graph (Network panel)."""
from __future__ import annotations


def test_graph_empty_db_classes(client):
    r = client.get("/api/dashboard/graph?mode=classes")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "classes"
    assert body["nodes"] == []
    assert body["edges"] == []
    assert body["n_nodes"] == 0
    assert body["n_edges"] == 0


def test_graph_empty_db_teachers(client):
    r = client.get("/api/dashboard/graph?mode=teachers")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "teachers"
    assert body["nodes"] == []
    assert body["edges"] == []


def test_graph_invalid_mode(client):
    r = client.get("/api/dashboard/graph?mode=garbage")
    # FastAPI Query regex enforces; expect 422.
    assert r.status_code == 422


def test_graph_with_data(client, app_with_temp_db):
    """Seed a tiny school: 2 classes, 1 teacher across both -> classes
    mode has 1 edge weight=1; teachers mode has 1 node 0 edges."""
    # Create classes via the API (clean path).
    common = {
        "year": 1, "section": "A", "n_students": 20,
        "hard_entry_at_8": True, "hard_exit_after_12": True,
        "hard_no_holes": True, "hard_dual_math": True,
        "hard_dual_italian": True, "hard_motorie_pairs": True,
        "hard_max_6_per_day": True, "soft_minimize_sixth_weight": 50,
        "subjects": [], "unavailability": [],
    }
    r = client.post("/api/classes", json={**common, "name": "TC1"})
    assert r.status_code in (200, 201), r.text
    c1 = r.json()["id"]
    r = client.post("/api/classes", json={**common, "name": "TC2",
                                          "section": "B"})
    c2 = r.json()["id"]

    # Create one teacher.
    r = client.post("/api/teachers", json={
        "name": "T One", "last_name": "One", "first_name": "T",
        "max_hours": 18,
    })
    t1 = r.json()["id"]

    # Wire Assignment rows directly via the test session (bypasses the
    # ManualAssignmentIn validator that wants pre-existing class_subjects).
    _, TestSession = app_with_temp_db
    from backend import models
    with TestSession() as db:
        db.add(models.Assignment(
            teacher_id=t1, class_id=c1, subject="Mate", hours=4,
            locked=True,
        ))
        db.add(models.Assignment(
            teacher_id=t1, class_id=c2, subject="Mate", hours=4,
            locked=True,
        ))
        db.commit()

    # Cache from previous calls would still be empty (we cleared in
    # the fixture); but force a fresh fetch by adding noise to the URL.
    r = client.get("/api/dashboard/graph?mode=classes")
    assert r.status_code == 200
    body = r.json()
    assert body["n_nodes"] == 2
    assert body["n_edges"] == 1
    edge = body["edges"][0]
    assert edge["weight"] == 1
    assert edge["shared"] == ["T One"]

    r = client.get("/api/dashboard/graph?mode=teachers")
    body = r.json()
    assert body["n_nodes"] == 1
    assert body["n_edges"] == 0
