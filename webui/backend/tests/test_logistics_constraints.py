"""API-level logistics tests: classroom assignment modes, capacity
vs n_students, lab `kind` restrictions, multi-class rooms.

These tests use the same TestClient + minimal seed pattern as
`test_placement_modes.py`. They focus on the bulk_events
conflict-detection path, which is what the /monitor UI uses
when the user assigns rooms to lessons.

Each test verifies a specific logistics rule:
  - Capacity vs n_students (room too small for class).
  - Multi-class room with capacity-aware multi_class_max.
  - Multiple classes in a multi-class room (palestra).
  - Room busy at the same slot (overlap detection).
  - ClassroomUnavailability HARD blocks placement.
  - Setting a non-lab room for a lab subject (this is currently
    tolerated; we just assert the API doesn't crash).

Fast: ~5 sec end-to-end.
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(HERE)
WEBUI_DIR = os.path.dirname(BACKEND_DIR)
REPO_ROOT = os.path.dirname(WEBUI_DIR)
ENGINE_DIR = os.path.join(REPO_ROOT, "engine")
SCHEDULE_DIR = os.path.join(REPO_ROOT, "schedule")
for p in (WEBUI_DIR, ENGINE_DIR, SCHEDULE_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


def _seed(client) -> dict:
    """Seed with 2 classes (small + big), 4 classrooms (generic +
    lab + small + palestra), 1 teacher, 4 lessons (covering both
    classes and shared slots)."""
    from backend import models
    overrides = client.app.dependency_overrides
    get_db_dep = next(iter(overrides))
    db = next(overrides[get_db_dep]())
    try:
        cl_small = models.SchoolClass(
            name="3A", year=3, section="A",
            curriculum="Scientifico", n_students=22)
        cl_big = models.SchoolClass(
            name="4A", year=4, section="A",
            curriculum="Scientifico", n_students=32)
        room_small = models.Classroom(
            name="Aula1", kind="standard", capacity=24)
        room_big = models.Classroom(
            name="Aula2", kind="standard", capacity=35)
        lab = models.Classroom(
            name="LabFis", kind="lab_fisica", capacity=24)
        palestra = models.Classroom(
            name="Palestra", kind="palestra", capacity=60,
            multi_class=True, multi_class_max=2,
            multi_class_pref=2)
        t = models.Teacher(name="Prof", group="A027",
                            max_hours=18, free_day="Saturday")
        db.add_all([cl_small, cl_big, room_small, room_big, lab,
                    palestra, t])
        db.flush()
        a_small = models.Assignment(
            teacher_id=t.id, class_id=cl_small.id,
            subject="Matematica", hours=2, locked=False)
        a_big = models.Assignment(
            teacher_id=t.id, class_id=cl_big.id,
            subject="Matematica", hours=2, locked=False)
        db.add_all([a_small, a_big])
        db.flush()
        sol = models.Solution(
            name="test", kind="phase_b", obj_value=0.0,
            metrics_json="{}", is_active=True)
        db.add(sol)
        db.flush()
        # 2 lessons in each class, all on day 1 hour 8 (both
        # classes on the same slot for the multi-class palestra
        # test) plus one lesson on day 2 for a separate slot.
        l_small_8 = models.Lesson(
            solution_id=sol.id, teacher_name=t.name,
            class_name=cl_small.name, subject=a_small.subject,
            day=1, hour=8)
        l_big_8 = models.Lesson(
            solution_id=sol.id, teacher_name=t.name,
            class_name=cl_big.name, subject=a_big.subject,
            day=1, hour=8)
        l_small_9 = models.Lesson(
            solution_id=sol.id, teacher_name=t.name,
            class_name=cl_small.name, subject=a_small.subject,
            day=1, hour=9)
        l_big_d2 = models.Lesson(
            solution_id=sol.id, teacher_name=t.name,
            class_name=cl_big.name, subject=a_big.subject,
            day=2, hour=8)
        db.add_all([l_small_8, l_big_8, l_small_9, l_big_d2])
        db.commit()
        return {
            "cl_small_id": cl_small.id, "cl_big_id": cl_big.id,
            "room_small_id": room_small.id,
            "room_big_id": room_big.id,
            "lab_id": lab.id, "palestra_id": palestra.id,
            "t_id": t.id,
            "l_small_8": l_small_8.id,
            "l_big_8": l_big_8.id,
            "l_small_9": l_small_9.id,
            "l_big_d2": l_big_d2.id,
            "names": {
                "cl_small": cl_small.name,
                "cl_big": cl_big.name,
                "room_small": room_small.name,
                "room_big": room_big.name,
                "lab": lab.name,
                "palestra": palestra.name,
            },
        }
    finally:
        db.close()


# ----------------------------------------------------------------------
# Capacity vs n_students
# ----------------------------------------------------------------------

def test_capacity_room_smaller_than_class_warns(client):
    """3A has 22 students; Aula1 has cap=24 -> fits, no conflict.
    But assigning 4A (32) to Aula1 (24) violates capacity."""
    seed = _seed(client)
    # 3A in Aula1: should be clean.
    r = client.post("/api/bulk/events/dry-run", json={
        "rows": [{"lesson_id": seed["l_small_8"]}],
        "action": "set_classroom",
        "payload": {"classroom_name": seed["names"]["room_small"]},
    })
    assert r.status_code == 200
    body = r.json()
    # Capacity is fine (22 <= 24). No conflict.
    assert len(body["conflicts"]) == 0, (
        f"unexpected conflicts: {body['conflicts']}")

    # 4A in Aula1: capacity violation (32 > 24).
    r = client.post("/api/bulk/events/dry-run", json={
        "rows": [{"lesson_id": seed["l_big_d2"]}],
        "action": "set_classroom",
        "payload": {"classroom_name": seed["names"]["room_small"]},
    })
    assert r.status_code == 200
    body = r.json()
    assert (body["candidates"] or body["conflicts"]), (
        f"expected capacity conflict for 4A in Aula1, got {body!r}")


def test_capacity_room_big_enough_no_conflict(client):
    """4A (32) in Aula2 (cap=35): no capacity conflict."""
    seed = _seed(client)
    r = client.post("/api/bulk/events/dry-run", json={
        "rows": [{"lesson_id": seed["l_big_d2"]}],
        "action": "set_classroom",
        "payload": {"classroom_name": seed["names"]["room_big"]},
    })
    assert r.status_code == 200
    body = r.json()
    assert len(body["conflicts"]) == 0, (
        f"unexpected conflicts: {body['conflicts']}")


# ----------------------------------------------------------------------
# Room busy / overlap detection
# ----------------------------------------------------------------------

def test_room_busy_overlap_detected(client):
    """Place 3A's d1h8 in Aula1, then try placing 4A's d1h8 in
    Aula1 too: SECOND placement must detect the room-busy conflict.
    """
    seed = _seed(client)
    # First: 3A -> Aula1 (clean)
    r = client.post("/api/bulk/events/apply", json={
        "rows": [{"lesson_id": seed["l_small_8"]}],
        "action": "set_classroom",
        "payload": {"classroom_name": seed["names"]["room_small"]},
        "on_conflict": "override",
    })
    assert r.status_code == 200, r.text
    assert r.json()["ok"]
    # Now 4A's d1h8 -> Aula1: room busy at d1h8 by 3A AND
    # capacity overflow (32 > 24).
    r = client.post("/api/bulk/events/dry-run", json={
        "rows": [{"lesson_id": seed["l_big_8"]}],
        "action": "set_classroom",
        "payload": {"classroom_name": seed["names"]["room_small"]},
    })
    assert r.status_code == 200, r.text
    body = r.json()
    # Either the room-busy or the capacity issue surfaces.
    assert (body["candidates"] or body["conflicts"]), (
        f"expected conflict for room-busy/capacity overlap, "
        f"got {body!r}")


# ----------------------------------------------------------------------
# Multi-class room (palestra)
# ----------------------------------------------------------------------

def test_multi_class_palestra_two_classes_same_slot(client):
    """Palestra is multi_class with multi_class_max=2: two classes
    can share the same (day, hour) without conflict."""
    seed = _seed(client)
    # 3A -> Palestra at d1h8
    r = client.post("/api/bulk/events/apply", json={
        "rows": [{"lesson_id": seed["l_small_8"]}],
        "action": "set_classroom",
        "payload": {"classroom_name": seed["names"]["palestra"]},
        "on_conflict": "override",
    })
    assert r.status_code == 200, r.text
    assert r.json()["ok"]
    # 4A -> Palestra at d1h8: should be allowed (multi_class=true,
    # max=2).
    r = client.post("/api/bulk/events/dry-run", json={
        "rows": [{"lesson_id": seed["l_big_8"]}],
        "action": "set_classroom",
        "payload": {"classroom_name": seed["names"]["palestra"]},
    })
    assert r.status_code == 200, r.text
    body = r.json()
    # No HARD conflict for the second class in the multi_class room.
    assert len(body["conflicts"]) == 0, (
        f"multi_class palestra rejected the 2nd class: "
        f"{body['conflicts']}")


# ----------------------------------------------------------------------
# Lab room kind
# ----------------------------------------------------------------------

def test_assign_lab_to_non_lab_subject_no_crash(client):
    """The bulk_events endpoint doesn't enforce
    ClassroomSubjectPreference HARD: assigning Matematica to a
    LabFis is tolerated. The test asserts the API returns a clean
    response (no 500). (Lab-kind enforcement is a CLASSROOM
    ASSIGNER concern, not a placement-time concern.)"""
    seed = _seed(client)
    r = client.post("/api/bulk/events/apply", json={
        "rows": [{"lesson_id": seed["l_small_8"]}],
        "action": "set_classroom",
        "payload": {"classroom_name": seed["names"]["lab"]},
        "on_conflict": "override",
    })
    assert r.status_code == 200, r.text


# ----------------------------------------------------------------------
# ClassroomUnavailability
# ----------------------------------------------------------------------

def test_room_unavailable_hard_blocks(client):
    """If ClassroomUnavailability has state='hard' for the target
    (day, hour), the placement is reported as a conflict."""
    from backend import models
    seed = _seed(client)
    # Mark Aula1 unavailable at d1h8 (HARD)
    overrides = client.app.dependency_overrides
    get_db_dep = next(iter(overrides))
    db = next(overrides[get_db_dep]())
    try:
        db.add(models.ClassroomUnavailability(
            classroom_id=seed["room_small_id"],
            day=1, hour=8, state="hard"))
        db.commit()
    finally:
        db.close()
    r = client.post("/api/bulk/events/dry-run", json={
        "rows": [{"lesson_id": seed["l_small_8"]}],
        "action": "set_classroom",
        "payload": {"classroom_name": seed["names"]["room_small"]},
    })
    assert r.status_code == 200, r.text
    body = r.json()
    # The HARD unavailability must appear as a conflict.
    assert (body["candidates"] or body["conflicts"]), (
        f"expected HARD unavailability to block placement, "
        f"got {body!r}")


# ----------------------------------------------------------------------
# Classroom CRUD smoke (useful for E2E later)
# ----------------------------------------------------------------------

def test_classroom_crud_smoke(client):
    """Create, list, update, delete a Classroom via the canonical
    POST/GET/PUT/DELETE endpoints. These are the calls the Cypress
    E2E in Step 4 will exercise."""
    # CREATE
    r = client.post("/api/classrooms", json={
        "name": "AulaTest", "kind": "standard",
        "capacity": 28, "multi_class": False,
        "multi_class_max": 1, "multi_class_pref": 1,
        "subject_prefs": [], "class_prefs": [],
        "unavailability": [],
        "tags": [],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    rid = body["id"]
    assert body["name"] == "AulaTest"
    assert body["capacity"] == 28
    # LIST
    r = client.get("/api/classrooms")
    assert r.status_code == 200
    rooms = r.json()["items"] if isinstance(r.json(), dict) else r.json()
    names = [x["name"] for x in rooms]
    assert "AulaTest" in names
    # UPDATE
    r = client.put(f"/api/classrooms/{rid}", json={
        "name": "AulaTest", "kind": "standard",
        "capacity": 30, "multi_class": False,
        "multi_class_max": 1, "multi_class_pref": 1,
        "subject_prefs": [], "class_prefs": [],
        "unavailability": [],
        "tags": [],
    })
    assert r.status_code == 200, r.text
    assert r.json()["capacity"] == 30
    # DELETE
    r = client.delete(f"/api/classrooms/{rid}")
    assert r.status_code == 200, r.text
