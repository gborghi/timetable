"""Smoke tests for /api/lessons/{id}/{move,unschedule,delete} +
/api/lessons/unscheduled/{id}/reschedule.

These id-based endpoints back the new calendar-style /schedule UI.
We seed a tiny scenario (1 active solution + 2 lessons) and:
  - move a lesson to an empty slot
  - unschedule a lesson -> appears in pool, gone from lessons
  - reschedule from pool -> back to lessons, gone from pool
  - delete a lesson by id
  - delete an unscheduled pool entry
  - 404 paths
"""
from __future__ import annotations


def _seed(SessionLocal):
    """Build active Solution + 2 Lessons (mon 8, mon 9)."""
    from backend import models

    s = SessionLocal()
    try:
        teaA = models.Teacher(name="TeaA", max_hours=18)
        cls1A = models.SchoolClass(name="1A", n_students=20)
        s.add_all([teaA, cls1A])
        s.flush()
        s.add(models.TeacherSubject(teacher_id=teaA.id, subject="Mat"))
        s.flush()
        a1 = models.Assignment(class_id=cls1A.id, teacher_id=teaA.id,
                                subject="Mat", hours=4)
        s.add(a1)
        s.flush()
        sol = models.Solution(name="t", kind="manual", is_active=True)
        s.add(sol)
        s.flush()
        l1 = models.Lesson(solution_id=sol.id, teacher_name="TeaA",
                            class_name="1A", subject="Mat",
                            day=1, hour=8)
        l2 = models.Lesson(solution_id=sol.id, teacher_name="TeaA",
                            class_name="1A", subject="Mat",
                            day=1, hour=9)
        s.add_all([l1, l2])
        s.commit()
        return sol.id, l1.id, l2.id
    finally:
        s.close()


def test_move_lesson_by_id_404_on_unknown(app_with_temp_db):
    from fastapi.testclient import TestClient

    app, SessionLocal = app_with_temp_db
    _seed(SessionLocal)
    client = TestClient(app)
    r = client.post("/api/lessons/99999/move",
                    json={"day": 2, "hour": 10})
    assert r.status_code == 404


def test_move_lesson_by_id_same_slot_rejected(app_with_temp_db):
    from fastapi.testclient import TestClient

    app, SessionLocal = app_with_temp_db
    _, l1, _ = _seed(SessionLocal)
    client = TestClient(app)
    r = client.post(f"/api/lessons/{l1}/move",
                    json={"day": 1, "hour": 8})
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] is False
    assert "identico" in body["reason"]


def test_unschedule_moves_to_pool_and_deletes_lesson(app_with_temp_db):
    from fastapi.testclient import TestClient
    from backend import models

    app, SessionLocal = app_with_temp_db
    _, l1, l2 = _seed(SessionLocal)
    client = TestClient(app)
    r = client.post(f"/api/lessons/{l1}/unschedule")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["lesson"]["original_day"] == 1
    assert body["lesson"]["original_hour"] == 8

    # Lesson row gone, pool row exists.
    s = SessionLocal()
    try:
        assert s.get(models.Lesson, l1) is None
        assert s.get(models.Lesson, l2) is not None
        pool = s.query(models.UnscheduledLesson).all()
        assert len(pool) == 1
        assert pool[0].teacher_name == "TeaA"
        assert pool[0].original_day == 1
        assert pool[0].original_hour == 8
    finally:
        s.close()


def test_unschedule_404_on_unknown_lesson(app_with_temp_db):
    from fastapi.testclient import TestClient

    app, SessionLocal = app_with_temp_db
    _seed(SessionLocal)
    client = TestClient(app)
    r = client.post("/api/lessons/99999/unschedule")
    assert r.status_code == 404


def test_list_unscheduled_returns_pool_for_active_solution(
        app_with_temp_db):
    from fastapi.testclient import TestClient

    app, SessionLocal = app_with_temp_db
    _, l1, _ = _seed(SessionLocal)
    client = TestClient(app)
    # Pool starts empty.
    r = client.get("/api/lessons/unscheduled")
    assert r.status_code == 200
    assert r.json() == {"lessons": []}

    # Unschedule one lesson.
    client.post(f"/api/lessons/{l1}/unschedule")

    r = client.get("/api/lessons/unscheduled")
    body = r.json()
    assert len(body["lessons"]) == 1
    assert body["lessons"][0]["teacher_name"] == "TeaA"


def test_reschedule_from_pool_creates_lesson(app_with_temp_db):
    from fastapi.testclient import TestClient
    from backend import models

    app, SessionLocal = app_with_temp_db
    _, l1, _ = _seed(SessionLocal)
    client = TestClient(app)
    # Unschedule then reschedule to a different slot.
    r = client.post(f"/api/lessons/{l1}/unschedule")
    pool_id = r.json()["unscheduled_id"]

    r2 = client.post(
        f"/api/lessons/unscheduled/{pool_id}/reschedule",
        json={"day": 2, "hour": 10},
    )
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["ok"] is True
    new_id = body["lesson_id"]

    s = SessionLocal()
    try:
        # Pool empty, new Lesson at (2, 10) exists.
        assert s.query(models.UnscheduledLesson).count() == 0
        new_l = s.get(models.Lesson, new_id)
        assert new_l is not None
        assert new_l.day == 2 and new_l.hour == 10
        assert new_l.teacher_name == "TeaA"
    finally:
        s.close()


def test_reschedule_unknown_pool_id_404(app_with_temp_db):
    from fastapi.testclient import TestClient

    app, SessionLocal = app_with_temp_db
    _seed(SessionLocal)
    client = TestClient(app)
    r = client.post("/api/lessons/unscheduled/99999/reschedule",
                    json={"day": 2, "hour": 10})
    assert r.status_code == 404


def test_delete_lesson_by_id(app_with_temp_db):
    from fastapi.testclient import TestClient
    from backend import models

    app, SessionLocal = app_with_temp_db
    _, l1, l2 = _seed(SessionLocal)
    client = TestClient(app)
    r = client.delete(f"/api/lessons/{l1}")
    assert r.status_code == 200
    s = SessionLocal()
    try:
        assert s.get(models.Lesson, l1) is None
        assert s.get(models.Lesson, l2) is not None
    finally:
        s.close()


def test_bulk_delete_removes_many_and_ignores_unknown(app_with_temp_db):
    """The conflict-resolver bulk endpoint deletes every known id in one
    call and silently skips ids that don't exist."""
    from fastapi.testclient import TestClient
    from backend import models

    app, SessionLocal = app_with_temp_db
    _, l1, l2 = _seed(SessionLocal)
    client = TestClient(app)
    r = client.post("/api/lessons/bulk-delete",
                    json={"ids": [l1, l2, 99999]})
    assert r.status_code == 200
    body = r.json()
    assert body["deleted"] == 2
    assert sorted(body["deleted_ids"]) == sorted([l1, l2])
    s = SessionLocal()
    try:
        assert s.get(models.Lesson, l1) is None
        assert s.get(models.Lesson, l2) is None
    finally:
        s.close()


def test_bulk_delete_empty_is_noop(app_with_temp_db):
    from fastapi.testclient import TestClient

    app, SessionLocal = app_with_temp_db
    _seed(SessionLocal)
    client = TestClient(app)
    r = client.post("/api/lessons/bulk-delete", json={"ids": []})
    assert r.status_code == 200
    assert r.json()["deleted"] == 0


def test_delete_lesson_by_id_404_on_unknown(app_with_temp_db):
    from fastapi.testclient import TestClient

    app, SessionLocal = app_with_temp_db
    _seed(SessionLocal)
    client = TestClient(app)
    r = client.delete("/api/lessons/99999")
    assert r.status_code == 404


def test_delete_unscheduled_drops_pool_row(app_with_temp_db):
    from fastapi.testclient import TestClient
    from backend import models

    app, SessionLocal = app_with_temp_db
    _, l1, _ = _seed(SessionLocal)
    client = TestClient(app)
    r = client.post(f"/api/lessons/{l1}/unschedule")
    pool_id = r.json()["unscheduled_id"]
    r2 = client.delete(f"/api/lessons/unscheduled/{pool_id}")
    assert r2.status_code == 200
    s = SessionLocal()
    try:
        assert s.query(models.UnscheduledLesson).count() == 0
    finally:
        s.close()
