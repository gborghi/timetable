"""Smoke tests for the new Phase-A class/curriculum preference
endpoints on /api/teachers."""
from __future__ import annotations


def _create_teacher(client, last_name: str = "Foo") -> int:
    r = client.post("/api/teachers", json={
        "name": f"T {last_name}",
        "last_name": last_name,
        "first_name": "F",
        "max_hours": 18,
    })
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def test_class_prefs_round_trip(client):
    tid = _create_teacher(client)

    # Initially empty
    r = client.get(f"/api/teachers/{tid}/class-preferences")
    assert r.status_code == 200
    assert r.json() == []

    # Set 2 prefs (one HARD, one SOFT with weight)
    payload = [
        {"class_name": "1A", "state": "forbidden", "soft_penalty": 0},
        {"class_name": "2B", "state": "soft", "soft_penalty": 50},
    ]
    r = client.put(
        f"/api/teachers/{tid}/class-preferences", json=payload,
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    assert {p["class_name"] for p in body} == {"1A", "2B"}

    # Replace: drop 1A, keep 2B
    r = client.put(
        f"/api/teachers/{tid}/class-preferences",
        json=[{"class_name": "2B", "state": "preferred",
               "soft_penalty": -100}],
    )
    body = r.json()
    assert len(body) == 1
    assert body[0]["class_name"] == "2B"
    assert body[0]["state"] == "preferred"


def test_curriculum_prefs_round_trip(client):
    tid = _create_teacher(client, "Bar")
    r = client.put(
        f"/api/teachers/{tid}/curriculum-preferences",
        json=[
            {"curriculum_code": "Scientifico", "state": "preferred",
             "soft_penalty": -100},
            {"curriculum_code": "Linguistico", "state": "forbidden",
             "soft_penalty": 0},
        ],
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2

    r = client.get(f"/api/teachers/{tid}/curriculum-preferences")
    assert {p["curriculum_code"] for p in r.json()} == {
        "Scientifico", "Linguistico"
    }


def test_prefs_404_on_missing_teacher(client):
    r = client.get("/api/teachers/9999999/class-preferences")
    assert r.status_code == 404
    r = client.put(
        "/api/teachers/9999999/curriculum-preferences",
        json=[{"curriculum_code": "X", "state": "soft",
               "soft_penalty": 100}],
    )
    assert r.status_code == 404


def test_default_allowed_rows_dropped(client):
    """`allowed` with penalty 0 is the default state -- no row should
    be persisted for it (saves space and avoids confusing a 'reset'
    with a 'no-op set')."""
    tid = _create_teacher(client, "Baz")
    client.put(
        f"/api/teachers/{tid}/class-preferences",
        json=[
            {"class_name": "1A", "state": "allowed",
             "soft_penalty": 0},
            {"class_name": "2B", "state": "soft",
             "soft_penalty": 100},
        ],
    )
    r = client.get(f"/api/teachers/{tid}/class-preferences")
    body = r.json()
    assert len(body) == 1
    assert body[0]["class_name"] == "2B"
