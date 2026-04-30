"""Smoke tests for the Phase-A criterion endpoints."""
from __future__ import annotations


def test_phase_a_presets_endpoint(client):
    r = client.get("/api/optimize/phase-a/presets")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    keys = {p["key"] for p in body}
    # Exactly 3 shipped presets per Giovanni's spec; Custom is UI-only.
    assert keys == {"balance_weight", "max_clustering", "seniority"}
    for p in body:
        assert "label" in p and "summary" in p and "expression" in p


def test_phase_a_validate_ok(client):
    r = client.post(
        "/api/optimize/phase-a/validate-expression",
        json={"expression": "minimize 5 * total_unused_capacity"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["direction"] == "minimize"
    assert body["errors"] == []


def test_phase_a_validate_missing_direction(client):
    r = client.post(
        "/api/optimize/phase-a/validate-expression",
        json={"expression": "5 + total_unused_capacity"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert len(body["errors"]) >= 1


def test_phase_a_validate_unknown_var(client):
    r = client.post(
        "/api/optimize/phase-a/validate-expression",
        json={"expression": "minimize foo_bar"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
