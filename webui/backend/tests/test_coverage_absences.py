"""Tests for the absences and substitutions endpoints (audit T5).

These endpoints previously had zero dedicated test coverage.
"""
import pytest
from fastapi.testclient import TestClient


def test_list_absences_empty(client: TestClient):
    """GET /api/absences returns empty list on fresh DB."""
    r = client.get("/api/absences")
    assert r.status_code == 200
    assert r.json() == []


def test_list_substitutions_is_post_only(client: TestClient):
    """GET /api/substitutions returns 405; the endpoint is POST-only."""
    r = client.get("/api/substitutions")
    # POST-only: GET not supported
    assert r.status_code == 405


def test_cannot_create_absence_without_teacher(client: TestClient):
    """POST /api/absences requires an existing teacher."""
    r = client.post("/api/absences", json={
        "teacher_name": "NonExistent",
        "date": "2026-09-14",
        "reason": "malattia",
    })
    assert r.status_code >= 400


def test_coverage_week_empty(client: TestClient):
    """GET /api/coverage/week with week_start param."""
    r = client.get("/api/coverage/week?week_start=2026-09-14")
    assert r.status_code == 200
    assert isinstance(r.json(), dict)


def test_coverage_cell_empty(client: TestClient):
    """GET /api/coverage/cell with date, day, and hour params."""
    r = client.get("/api/coverage/cell?date=2026-09-14&day=1&hour=8")
    assert r.status_code == 200
    assert isinstance(r.json(), dict)


def test_cannot_create_substitution_without_absence(client: TestClient):
    """POST /api/substitutions requires an existing absence."""
    r = client.post("/api/substitutions", json={
        "absence_id": 99999,
        "substitute_name": "Someone",
        "day": 1,
        "hour": 8,
    })
    assert r.status_code >= 400
