"""Tests for /api/working-hours/* (Tab Ore).

Cover the happy paths:
  - default seed materialises 6 days x 6 slots
  - get config returns the canonical lun-sab + 8-14 layout
  - replace-slots roundtrip preserves the input
  - reset endpoint restores the default after a destructive edit
  - validation errors raise 422 (overlapping slots, malformed HH:MM)
"""
from __future__ import annotations


def test_default_seed_returns_lun_sab_eight_to_fourteen(client):
    r = client.get("/api/working-hours/config")
    assert r.status_code == 200, r.text
    body = r.json()
    days = body["days"]
    assert [d["code"] for d in days] == [
        "MON", "TUE", "WED", "THU", "FRI", "SAT"
    ]
    assert all(d["is_active"] for d in days)
    assert body["max_slots_per_day"] == 6
    assert body["uniform_slot_count"] is True
    mon = days[0]
    assert [s["slot_index"] for s in mon["slots"]] == [0, 1, 2, 3, 4, 5]
    assert mon["slots"][0]["start_time"] == "08:00"
    assert mon["slots"][0]["end_time"] == "09:00"
    assert mon["slots"][5]["end_time"] == "14:00"
    assert mon["slots"][0]["legacy_hour_number"] == 8
    assert mon["slots"][5]["legacy_hour_number"] == 13


def test_replace_day_slots_roundtrip(client):
    r = client.get("/api/working-hours/days")
    days = r.json()
    sat_id = next(d["id"] for d in days if d["code"] == "SAT")
    new = {
        "slots": [
            {
                "slot_index": 0, "start_time": "14:00", "end_time": "15:00",
                "label": "1° pomeriggio", "legacy_hour_number": 14,
            },
            {
                "slot_index": 1, "start_time": "15:00", "end_time": "16:00",
                "label": "2° pomeriggio", "legacy_hour_number": 15,
            },
            {
                "slot_index": 2, "start_time": "16:00", "end_time": "17:00",
                "label": "3° pomeriggio", "legacy_hour_number": 16,
            },
        ]
    }
    r = client.put(f"/api/working-hours/days/{sat_id}/slots", json=new)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["slots"]) == 3
    assert body["slots"][0]["start_time"] == "14:00"
    assert body["slots"][2]["end_time"] == "17:00"

    # And the aggregated config picks up the new variable count
    r = client.get("/api/working-hours/config")
    cfg = r.json()
    assert cfg["max_slots_per_day"] == 6  # mon..fri still have 6
    assert cfg["uniform_slot_count"] is False
    sat = next(d for d in cfg["days"] if d["code"] == "SAT")
    assert len(sat["slots"]) == 3


def test_replace_slots_rejects_overlap(client):
    r = client.get("/api/working-hours/days")
    mon_id = next(d["id"] for d in r.json() if d["code"] == "MON")
    bad = {
        "slots": [
            {"slot_index": 0, "start_time": "08:00", "end_time": "09:30",
             "legacy_hour_number": 8},
            {"slot_index": 1, "start_time": "09:00", "end_time": "10:00",
             "legacy_hour_number": 9},
        ]
    }
    r = client.put(f"/api/working-hours/days/{mon_id}/slots", json=bad)
    assert r.status_code == 422, r.text


def test_replace_slots_rejects_malformed_time(client):
    r = client.get("/api/working-hours/days")
    mon_id = next(d["id"] for d in r.json() if d["code"] == "MON")
    bad = {
        "slots": [
            {"slot_index": 0, "start_time": "8:00am",
             "end_time": "09:00",  "legacy_hour_number": 8},
        ]
    }
    r = client.put(f"/api/working-hours/days/{mon_id}/slots", json=bad)
    assert r.status_code == 422, r.text


def test_update_day_label_and_active(client):
    days = client.get("/api/working-hours/days").json()
    sat_id = next(d["id"] for d in days if d["code"] == "SAT")
    r = client.put(f"/api/working-hours/days/{sat_id}",
                   json={"is_active": False, "label": "Sabato chiuso"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_active"] is False
    assert body["label"] == "Sabato chiuso"

    cfg = client.get("/api/working-hours/config").json()
    sat = next(d for d in cfg["days"] if d["code"] == "SAT")
    assert sat["is_active"] is False


def test_reset_to_default(client):
    days = client.get("/api/working-hours/days").json()
    mon_id = next(d["id"] for d in days if d["code"] == "MON")
    # Garble the config
    r = client.put(f"/api/working-hours/days/{mon_id}/slots", json={
        "slots": [
            {"slot_index": 0, "start_time": "10:00", "end_time": "11:00",
             "legacy_hour_number": 10},
        ]
    })
    assert r.status_code == 200
    # Reset
    r = client.post("/api/working-hours/reset")
    assert r.status_code == 200, r.text
    cfg = client.get("/api/working-hours/config").json()
    assert cfg["max_slots_per_day"] == 6
    assert cfg["uniform_slot_count"] is True
    mon = next(d for d in cfg["days"] if d["code"] == "MON")
    assert len(mon["slots"]) == 6
    assert mon["slots"][0]["start_time"] == "08:00"
    assert mon["slots"][5]["end_time"] == "14:00"


def test_engine_config_loader_defaults():
    """The engine helper falls back to legacy defaults when the DB
    fall-through path can't find a populated working_days table.
    Calling reload() forces the fallback when we point at a non-DB
    location."""
    import os
    from backend import engine_paths  # noqa: F401  -- inject engine/ on sys.path
    import working_hours_config as whc  # type: ignore

    old = os.environ.get("PITANTUM_DB_URL")
    os.environ["PITANTUM_DB_URL"] = "sqlite:///does-not-exist-xyz.db"
    try:
        whc.reload()
        assert whc.get_days() == [1, 2, 3, 4, 5, 6]
        assert whc.get_hours() == [8, 9, 10, 11, 12, 13]
        assert whc.get_max_slots_per_day() == 6
        assert whc.is_uniform_slot_count() is True
        assert whc.get_slot_label(1, 0) == "08:00-09:00"
        assert whc.get_slot_label(6, 5) == "13:00-14:00"
    finally:
        if old is None:
            os.environ.pop("PITANTUM_DB_URL", None)
        else:
            os.environ["PITANTUM_DB_URL"] = old
        whc.reload()
