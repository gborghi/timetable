"""Smoke tests for /api/bulk/events/{dry-run,apply}.

Covers the three actions exposed by BulkEventsModal:
  - set_classroom    with HARD conflict (room busy in same slot)
                     and capacity WARN (capacity < n_students)
  - clear_classroom  no-conflict path
  - set_lock         placeholder rows ARE valid targets

We build a tiny scenario in the temp DB, then exercise dry-run and apply
through the FastAPI TestClient.
"""
from __future__ import annotations


def _seed(SessionLocal):
    """Build a minimal scenario with two lessons sharing a slot.

    Layout:
      slot d=1 h=8
        L1: TeaA / 1A / Mat / room=R1
        L2: TeaB / 1B / Eng / room=R1   <-- collides with L1's room
        L3: TeaA / 1A / Mat / room=None (placeholder == None lesson_id
            in the monitor view; here we still need a real Lesson to
            test set_classroom mutating an empty room slot)
    Plus an Assignment with no Lessons -> placeholder row.
    """
    from backend import models

    s = SessionLocal()
    try:
        teaA = models.Teacher(name="TeaA")
        teaB = models.Teacher(name="TeaB")
        cls1A = models.SchoolClass(name="1A", n_students=30)
        cls1B = models.SchoolClass(name="1B", n_students=20)
        s.add_all([teaA, teaB, cls1A, cls1B])
        s.flush()

        # Two classrooms: R1 has small capacity; R2 has plenty.
        roomR1 = models.Classroom(name="R1", kind="standard",
                                   capacity=22, multi_class=False)
        roomR2 = models.Classroom(name="R2", kind="standard",
                                   capacity=40, multi_class=False)
        s.add_all([roomR1, roomR2])
        s.flush()

        a1 = models.Assignment(class_id=cls1A.id, teacher_id=teaA.id,
                                subject="Mat", hours=2, locked=False)
        a2 = models.Assignment(class_id=cls1B.id, teacher_id=teaB.id,
                                subject="Eng", hours=1, locked=False)
        # Third assignment with NO lessons -> drives the placeholder
        # path of /monitor/event-rows.
        a3 = models.Assignment(class_id=cls1A.id, teacher_id=teaA.id,
                                subject="Sto", hours=1, locked=False)
        s.add_all([a1, a2, a3])
        s.flush()

        sol = models.Solution(name="t", kind="manual", is_active=True)
        s.add(sol)
        s.flush()

        # Two lessons in the SAME (day, hour) so set_classroom on L1 to
        # R1 collides with L2 (already in R1).
        l1 = models.Lesson(solution_id=sol.id, teacher_name="TeaA",
                            class_name="1A", subject="Mat",
                            day=1, hour=8, classroom_name=None)
        l2 = models.Lesson(solution_id=sol.id, teacher_name="TeaB",
                            class_name="1B", subject="Eng",
                            day=1, hour=8, classroom_name="R1")
        s.add_all([l1, l2])
        s.flush()
        s.commit()
        return {
            "lesson_free_id": l1.id, "asg_free_id": a1.id,
            "lesson_busy_id": l2.id, "asg_busy_id": a2.id,
            "asg_placeholder_id": a3.id,
        }
    finally:
        s.close()


def test_set_classroom_dry_run_flags_room_conflict(client,
                                                    app_with_temp_db):
    _, SessionLocal = app_with_temp_db
    ids = _seed(SessionLocal)

    # Try to put L1 into R1 -- L2 already occupies R1 in same slot.
    body = {
        "rows": [{"lesson_id": ids["lesson_free_id"],
                  "assignment_id": ids["asg_free_id"]}],
        "action": "set_classroom",
        "payload": {"classroom_name": "R1"},
        "on_conflict": "dry_run",
    }
    r = client.post("/api/bulk/events/dry-run", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["n_targets"] == 1
    assert len(out["candidates"]) == 0
    assert len(out["conflicts"]) == 1
    assert "occupata" in out["conflicts"][0]["reason"].lower()


def test_set_classroom_dry_run_capacity_warn(client, app_with_temp_db):
    _, SessionLocal = app_with_temp_db
    ids = _seed(SessionLocal)

    # 1A has 30 students; R1 has capacity 22 (WARN). Use a slot where
    # R1 is free for L1 to isolate the capacity check from room-busy.
    # We move L1 to R1 -- but L2 is in R1 same slot, so we'd hit the
    # room-busy check first. Instead test capacity by changing L1 to
    # a slot where R1 is free, BUT we don't have such a lesson handy.
    # Cheat: delete L2 so R1 is free, then dry-run reports capacity.
    from backend import models
    s = SessionLocal()
    try:
        s.query(models.Lesson).filter(
            models.Lesson.id == ids["lesson_busy_id"]).delete()
        s.commit()
    finally:
        s.close()

    body = {
        "rows": [{"lesson_id": ids["lesson_free_id"],
                  "assignment_id": ids["asg_free_id"]}],
        "action": "set_classroom",
        "payload": {"classroom_name": "R1"},
        "on_conflict": "dry_run",
    }
    r = client.post("/api/bulk/events/dry-run", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert len(out["conflicts"]) == 1
    assert "capienza" in out["conflicts"][0]["reason"].lower()


def test_apply_skip_keeps_conflicting_lesson_unchanged(client,
                                                        app_with_temp_db):
    _, SessionLocal = app_with_temp_db
    ids = _seed(SessionLocal)

    body = {
        "rows": [{"lesson_id": ids["lesson_free_id"],
                  "assignment_id": ids["asg_free_id"]}],
        "action": "set_classroom",
        "payload": {"classroom_name": "R1"},
        "on_conflict": "skip",
    }
    r = client.post("/api/bulk/events/apply", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["n_applied"] == 0
    assert out["n_skipped"] == 1

    from backend import models
    s = SessionLocal()
    try:
        l1 = s.get(models.Lesson, ids["lesson_free_id"])
        assert l1.classroom_name in (None, "")  # unchanged
    finally:
        s.close()


def test_apply_override_forces_room_assignment(client, app_with_temp_db):
    _, SessionLocal = app_with_temp_db
    ids = _seed(SessionLocal)

    body = {
        "rows": [{"lesson_id": ids["lesson_free_id"],
                  "assignment_id": ids["asg_free_id"]}],
        "action": "set_classroom",
        "payload": {"classroom_name": "R1"},
        "on_conflict": "override",
    }
    r = client.post("/api/bulk/events/apply", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["n_overridden"] == 1
    assert out["n_applied"] == 0

    from backend import models
    s = SessionLocal()
    try:
        l1 = s.get(models.Lesson, ids["lesson_free_id"])
        assert l1.classroom_name == "R1"
    finally:
        s.close()


def test_placeholder_row_skipped_for_set_classroom(client,
                                                    app_with_temp_db):
    _, SessionLocal = app_with_temp_db
    ids = _seed(SessionLocal)

    # Placeholder row: lesson_id=None, assignment_id refers to a3 (no
    # Lessons). Should ALWAYS skip with the "non schedulato" message
    # regardless of on_conflict.
    body = {
        "rows": [{"lesson_id": None,
                  "assignment_id": ids["asg_placeholder_id"]}],
        "action": "set_classroom",
        "payload": {"classroom_name": "R2"},
        "on_conflict": "override",
    }
    r = client.post("/api/bulk/events/apply", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["n_skipped"] == 1
    assert out["n_applied"] == 0
    assert out["n_overridden"] == 0
    assert any("non schedulato" in m for m in out["messages"])


def test_clear_classroom_apply(client, app_with_temp_db):
    _, SessionLocal = app_with_temp_db
    ids = _seed(SessionLocal)

    body = {
        "rows": [{"lesson_id": ids["lesson_busy_id"],
                  "assignment_id": ids["asg_busy_id"]}],
        "action": "clear_classroom",
        "on_conflict": "skip",
    }
    r = client.post("/api/bulk/events/apply", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["n_applied"] == 1

    from backend import models
    s = SessionLocal()
    try:
        l2 = s.get(models.Lesson, ids["lesson_busy_id"])
        assert l2.classroom_name is None
    finally:
        s.close()


def test_set_lock_works_on_placeholders_too(client, app_with_temp_db):
    _, SessionLocal = app_with_temp_db
    ids = _seed(SessionLocal)

    body = {
        "rows": [
            {"lesson_id": ids["lesson_free_id"],
             "assignment_id": ids["asg_free_id"]},
            {"lesson_id": None,
             "assignment_id": ids["asg_placeholder_id"]},
        ],
        "action": "set_lock",
        "payload": {"locked": True},
        "on_conflict": "skip",
    }
    r = client.post("/api/bulk/events/apply", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    # Both rows should apply: placeholder is fine for set_lock.
    assert out["n_applied"] + out["n_overridden"] == 2
    assert out["n_skipped"] == 0

    from backend import models
    s = SessionLocal()
    try:
        a1 = s.get(models.Assignment, ids["asg_free_id"])
        a3 = s.get(models.Assignment, ids["asg_placeholder_id"])
        assert a1.locked is True
        assert a3.locked is True
    finally:
        s.close()


def test_set_lock_dedups_repeated_assignment_rows(client,
                                                   app_with_temp_db):
    _, SessionLocal = app_with_temp_db
    ids = _seed(SessionLocal)

    # Same assignment_id appears twice (e.g. two lessons of the same
    # cattedra were selected). Only one apply should be reported.
    body = {
        "rows": [
            {"lesson_id": ids["lesson_free_id"],
             "assignment_id": ids["asg_free_id"]},
            {"lesson_id": None,
             "assignment_id": ids["asg_free_id"]},
        ],
        "action": "set_lock",
        "payload": {"locked": True},
        "on_conflict": "skip",
    }
    r = client.post("/api/bulk/events/apply", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["n_applied"] + out["n_overridden"] == 1


def test_unknown_action_is_400(client, app_with_temp_db):
    body = {"rows": [], "action": "set_group", "on_conflict": "dry_run"}
    r = client.post("/api/bulk/events/dry-run", json=body)
    assert r.status_code == 400
    assert "set_group" in r.text or "sconosciuta" in r.text
