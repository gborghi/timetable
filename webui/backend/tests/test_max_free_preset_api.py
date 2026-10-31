"""Preset «giorni liberi»: default dal dato del motore, limiti nello schema."""
from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_preset_endpoint_returns_engine_data(client):
    import max_free_days as mfd
    r = client.get("/api/optimize/presets/max-free-days")
    assert r.status_code == 200
    body = r.json()
    assert body["max_free"] == mfd.PRESET["max_free"]
    assert body["threshold"] == mfd.PRESET["threshold"]


def test_schema_defaults_come_from_preset_and_bounds():
    from backend import schemas
    import max_free_days as mfd
    p = schemas.PhaseBRunIn()
    assert p.max_free_days == mfd.PRESET["max_free"]
    assert p.full_time_hours == mfd.PRESET["threshold"]
    for bad in ({"max_free_days": -3}, {"full_time_hours": -1},
                {"max_free_days": 99}):
        with pytest.raises(ValidationError):
            schemas.PhaseBRunIn(**bad)
