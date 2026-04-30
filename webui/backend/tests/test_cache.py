"""Tests for the TTL cache + mutation invalidation (Section 2.4 P1)."""
from __future__ import annotations


def test_cache_invalidated_on_create(client):
    """Calling /api/dataset/state must reflect a subsequent POST. The
    cache is mutation-aware so the second GET sees the new count."""
    r1 = client.get("/api/dataset/state")
    assert r1.status_code == 200
    n_subjects_before = r1.json()["subjects"]

    r2 = client.post("/api/subjects", json={"name": "X"})
    assert r2.status_code in (200, 201)

    r3 = client.get("/api/dataset/state")
    assert r3.status_code == 200
    assert r3.json()["subjects"] == n_subjects_before + 1


def test_cache_returns_same_object_within_ttl(client):
    """Two GETs in quick succession with no mutation in between get
    served from the cache (we can't observe the cache directly through
    the API, but this confirms there's no error path)."""
    r1 = client.get("/api/dataset/state")
    r2 = client.get("/api/dataset/state")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json() == r2.json()


def test_monitor_summary_cached(client):
    """summary endpoint with the cache wrapper still returns valid
    data on an empty DB."""
    r = client.get("/api/monitor/summary")
    assert r.status_code == 200
    body = r.json()
    for k in ("n_events", "n_incomplete", "n_missing_hours",
              "n_missing_room", "n_missing_group"):
        assert k in body
        assert body[k] == 0
