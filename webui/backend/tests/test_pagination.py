"""Tests for opt-in pagination on list endpoints (Section 2.3 P1)."""
from __future__ import annotations


def _seed_students(client, n: int = 5):
    for i in range(n):
        client.post("/api/students", json={
            "last_name": f"Rossi{i:02d}",
            "first_name": f"Mario{i:02d}",
        })


def test_students_no_pagination_returns_bare_list(client):
    _seed_students(client, 5)
    r = client.get("/api/students")
    assert r.status_code == 200
    body = r.json()
    # Legacy shape: bare list.
    assert isinstance(body, list)
    assert len(body) == 5


def test_students_with_limit_returns_envelope(client):
    _seed_students(client, 5)
    r = client.get("/api/students?limit=2")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, dict)
    assert "items" in body and "total" in body
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["limit"] == 2
    assert body["offset"] == 0


def test_students_with_offset_returns_envelope(client):
    _seed_students(client, 5)
    r = client.get("/api/students?offset=2")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, dict)
    assert body["total"] == 5
    assert len(body["items"]) == 3
    assert body["offset"] == 2
    assert body["limit"] is None


def test_students_pagination_offset_past_end(client):
    _seed_students(client, 3)
    r = client.get("/api/students?limit=10&offset=100")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert body["items"] == []


def test_monitor_events_pagination_envelope(client):
    """The events endpoint accepts the same opt-in pagination. Without
    a solution there are 0 events but the envelope still works."""
    r = client.get("/api/monitor/events?limit=10")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, dict)
    assert "items" in body
    assert body["limit"] == 10
