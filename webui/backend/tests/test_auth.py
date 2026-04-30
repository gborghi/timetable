"""Tests for the optional API-key middleware (Section 2.6 P1)."""
from __future__ import annotations

import os


def test_no_key_set_means_open(client):
    """When PITANTUM_API_KEY is unset, every endpoint is reachable
    without auth (default localhost dev behaviour)."""
    # In the test fixture the env var is not set.
    os.environ.pop("PITANTUM_API_KEY", None)
    r = client.get("/api/health")
    assert r.status_code == 200
    r = client.get("/api/teachers")
    assert r.status_code == 200


def test_key_required_when_env_set(client, monkeypatch):
    monkeypatch.setenv("PITANTUM_API_KEY", "s3cret-test-key")
    # Missing header -> 401
    r = client.get("/api/teachers")
    assert r.status_code == 401
    body = r.json()
    assert body.get("code") == "unauthorized"

    # Wrong key -> 401
    r = client.get("/api/teachers", headers={"X-API-Key": "wrong"})
    assert r.status_code == 401

    # Correct key -> 200
    r = client.get(
        "/api/teachers",
        headers={"X-API-Key": "s3cret-test-key"},
    )
    assert r.status_code == 200

    # Bearer form -> 200 too
    r = client.get(
        "/api/teachers",
        headers={"Authorization": "Bearer s3cret-test-key"},
    )
    assert r.status_code == 200


def test_health_always_open_even_with_key(client, monkeypatch):
    monkeypatch.setenv("PITANTUM_API_KEY", "s3cret-test-key")
    r = client.get("/api/health")
    assert r.status_code == 200
