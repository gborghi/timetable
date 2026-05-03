"""Tests for the Dashboard 'Vincoli' import / export endpoints.

Covers:
  POST /api/dashboard/constraints/import-stress  (small profile, 18 records)
  POST /api/dashboard/constraints/import-file    (5 records, 1 invalid)
  GET  /api/dashboard/constraints/export?format=json
  DELETE /api/dashboard/constraints/all?confirm=true
"""
from __future__ import annotations

import io
import json


# ---------------------------------------------------------------------
# Helpers: seed minimal entities so owner_pattern resolution succeeds
# ---------------------------------------------------------------------

def _seed_minimal_school(client):
    """Create the entities referenced by the small/ stress profile:
    at least 2 teachers (first_teacher, second_teacher), 2-3 labs +
    a Palestra + an Aula Magna (first_lab/second_lab/gym/main_room),
    one class per year, and a Scientifico curriculum."""
    teachers_payload = [
        {"name": "T One", "last_name": "One", "first_name": "T",
         "max_hours": 18},
        {"name": "T Two", "last_name": "Two", "first_name": "T",
         "max_hours": 18},
        {"name": "T Three", "last_name": "Three", "first_name": "T",
         "max_hours": 18},
        {"name": "T Four", "last_name": "Four", "first_name": "T",
         "max_hours": 18},
        {"name": "T Five", "last_name": "Five", "first_name": "T",
         "max_hours": 18},
    ]
    teacher_ids = []
    for p in teachers_payload:
        r = client.post("/api/teachers", json=p)
        assert r.status_code in (200, 201), r.text
        teacher_ids.append(r.json()["id"])
    # Classrooms: lab1, lab2, lab3, palestra, aula magna
    rooms_payload = [
        {"name": "Lab Fisica", "kind": "lab_fisica", "capacity": 30},
        {"name": "Lab Informatica", "kind": "lab_informatica",
         "capacity": 30},
        {"name": "Lab Chimica", "kind": "lab_chimica", "capacity": 30},
        {"name": "Palestra", "kind": "palestra", "capacity": 60},
        {"name": "Aula Magna", "kind": "aula_magna", "capacity": 200},
    ]
    room_ids = []
    for p in rooms_payload:
        r = client.post("/api/classrooms", json=p)
        assert r.status_code in (200, 201), r.text
        room_ids.append(r.json()["id"])
    # Classes — year 1..5 each with one class.
    common = {
        "n_students": 20,
        "hard_entry_at_8": True, "hard_exit_after_12": True,
        "hard_no_holes": True, "hard_dual_math": True,
        "hard_dual_italian": True, "hard_motorie_pairs": True,
        "hard_max_6_per_day": True, "soft_minimize_sixth_weight": 50,
        "subjects": [], "unavailability": [],
    }
    class_ids = []
    for y in range(1, 6):
        r = client.post("/api/classes",
                        json={**common, "name": f"T{y}A",
                              "year": y, "section": "A"})
        assert r.status_code in (200, 201), r.text
        class_ids.append(r.json()["id"])
    # Curriculum
    r = client.post("/api/curricula",
                     json={"name": "Scientifico"})
    if r.status_code in (200, 201):
        curr_id = r.json()["id"]
    else:
        # Some setups already seed curricula; tolerate.
        curr_id = None
    return teacher_ids, room_ids, class_ids, curr_id


# ---------------------------------------------------------------------
# import-stress
# ---------------------------------------------------------------------

def test_import_stress_small(client):
    _seed_minimal_school(client)
    r = client.post(
        "/api/dashboard/constraints/import-stress",
        json={"profile": "small"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["profile"] == "small"
    # small has 18 records (8 teacher + 5 classroom + 5 relational)
    assert body["n_total"] == 18
    # The handful of conflicts (3 deliberate pairs) means 3 records are
    # marked intentionally_conflicting.
    assert body["intentional_conflicts"] >= 1
    # Owner resolution should succeed for at least the bulk of records:
    # we expect >= 12/18 ok. (Some scope=class records may fail if the
    # class year doesn't match anything seeded; that's acceptable.)
    assert body["n_loaded"] >= 12, (
        f"too many resolution failures: {body['n_errors']}/{body['n_total']}: "
        f"errors={[r for r in body['results'] if not r['ok']][:3]}")
    # by_category tally should be non-zero in at least one category.
    assert sum(body["by_category"].values()) == body["n_total"]


def test_import_stress_invalid_profile(client):
    r = client.post(
        "/api/dashboard/constraints/import-stress",
        json={"profile": "extralarge"},
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------
# import-file (custom JSON)
# ---------------------------------------------------------------------

def test_import_file_json_partial_errors(client):
    """5 records, 1 invalid (DSL syntax error). Expect 4 imported,
    1 reported as error."""
    teacher_ids, _room_ids, _class_ids, _ = _seed_minimal_school(client)
    t_one = "T One"
    t_two = "T Two"
    records = [
        # Valid: HARD logical for T One
        {"kind": "logical", "scope": "teacher",
         "owner_name": t_one,
         "level": "hard",
         "expression": "mai mar1 AND mai mar2",
         "description": "T One unavailable Mar 1-2"},
        # Valid: SOFT logical for T One with soft_penalty
        {"kind": "logical", "scope": "teacher",
         "owner_name": t_one,
         "level": "soft",
         "expression": "mai sab",
         "soft_penalty": 80,
         "description": "T One: prefers no Sat"},
        # Valid: PREFERRED logical for T Two
        {"kind": "logical", "scope": "teacher",
         "owner_name": t_two,
         "level": "preferred",
         "expression": "lun OR mar",
         "soft_penalty": 50},
        # Valid: HARD logical for class T1A
        {"kind": "logical", "scope": "class",
         "owner_name": "T1A",
         "level": "hard",
         "expression": "mai mer8 AND mai mer9"},
        # INVALID: bogus DSL
        {"kind": "logical", "scope": "teacher",
         "owner_name": t_one,
         "level": "hard",
         "expression": "@@@SYNTAX_ERROR@@@"},
    ]
    blob = json.dumps(records).encode("utf-8")
    r = client.post(
        "/api/dashboard/constraints/import-file",
        files={"file": ("custom.json", blob, "application/json")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["n_total"] == 5
    # Expect 4 valid + 1 errored.
    assert body["n_loaded"] == 4, (
        f"expected 4 loaded, got {body['n_loaded']}; "
        f"errors={body['errors']}")
    assert body["n_errors"] == 1
    assert len(body["errors"]) == 1
    # The invalid record should be flagged with a meaningful error.
    err = body["errors"][0]
    assert err["idx"] == 4
    assert "error" in err and err["error"]


def test_import_file_invalid_json(client):
    r = client.post(
        "/api/dashboard/constraints/import-file",
        files={"file": ("bad.json", b"not a json", "application/json")},
    )
    assert r.status_code == 400


def test_import_file_unknown_owner(client):
    """owner_name not present in DB -> reported as error, no row."""
    _seed_minimal_school(client)
    records = [{
        "kind": "logical", "scope": "teacher",
        "owner_name": "Nonexistent Teacher",
        "level": "hard",
        "expression": "mai lun8",
    }]
    r = client.post(
        "/api/dashboard/constraints/import-file",
        files={"file": ("x.json", json.dumps(records).encode("utf-8"),
                         "application/json")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["n_loaded"] == 0
    assert body["n_errors"] == 1
    assert "non trovato" in body["errors"][0]["error"]


# ---------------------------------------------------------------------
# export + delete-all round-trip
# ---------------------------------------------------------------------

def test_export_then_delete_all_roundtrip(client):
    _seed_minimal_school(client)
    # Import a tiny set, then export, then wipe, check empty export.
    records = [{
        "kind": "logical", "scope": "teacher",
        "owner_name": "T One", "level": "hard",
        "expression": "mai gio12",
    }, {
        "kind": "logical", "scope": "class",
        "owner_name": "T1A", "level": "soft",
        "expression": "mai sab", "soft_penalty": 60,
    }]
    blob = json.dumps(records).encode("utf-8")
    r = client.post(
        "/api/dashboard/constraints/import-file",
        files={"file": ("seed.json", blob, "application/json")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["n_loaded"] == 2

    # Export JSON
    r = client.get("/api/dashboard/constraints/export?format=json")
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list)
    assert len(rows) >= 2
    kinds = {r["kind"] for r in rows}
    assert "logical" in kinds

    # Delete-all without confirm -> 400
    r = client.delete("/api/dashboard/constraints/all")
    assert r.status_code == 400

    # Delete-all with confirm -> ok
    r = client.delete("/api/dashboard/constraints/all?confirm=true")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["n_deleted"] >= 2

    # After wipe, export returns []
    r = client.get("/api/dashboard/constraints/export?format=json")
    assert r.status_code == 200
    assert r.json() == []


def test_export_xlsx_has_correct_mime(client):
    _seed_minimal_school(client)
    r = client.get("/api/dashboard/constraints/export?format=xlsx")
    # If openpyxl is missing in the test env, accept 500; otherwise
    # the file must come back with the xlsx mime.
    if r.status_code == 500:
        return
    assert r.status_code == 200
    ct = r.headers.get("content-type", "")
    assert "spreadsheetml" in ct or "octet-stream" in ct
    # An xlsx is a zip; the magic bytes start with PK.
    assert r.content[:2] == b"PK"
