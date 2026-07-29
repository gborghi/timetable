"""Tests for GET /api/lessons server-side scoping + pagination.

The calendar's "Orario globale" view fetches the whole active solution
(no params -> original contract). Single class/teacher/room views can
scope the fetch server-side so a big school does not ship thousands of
rows per view. The scoped predicate must mirror the client-side filter
in WeeklyCalendarView (class_name / teacher_name / classroom_name exact
match) so a scoped fetch equals "fetch all, then filter on the client".
"""
from __future__ import annotations


def _seed(SessionLocal):
    """Active Solution with a spread of lessons across 2 classes,
    2 teachers and 2 rooms so every scope has a non-trivial subset."""
    from backend import models

    s = SessionLocal()
    try:
        sol = models.Solution(name="t", kind="manual", is_active=True)
        s.add(sol)
        s.flush()
        rows = [
            # (teacher, class, subject, day, hour, room)
            ("TeaA", "1A", "Mat", 1, 8, "R1"),
            ("TeaA", "1A", "Mat", 1, 9, "R1"),
            ("TeaB", "1A", "Ita", 2, 8, "R2"),
            ("TeaA", "2B", "Mat", 1, 8, "R2"),
            ("TeaB", "2B", "Ita", 3, 8, "R1"),
        ]
        for tea, cls, sub, d, h, room in rows:
            s.add(models.Lesson(
                solution_id=sol.id, teacher_name=tea, class_name=cls,
                subject=sub, day=d, hour=h, classroom_name=room))
        s.commit()
        return sol.id
    finally:
        s.close()


def test_list_no_params_returns_all(app_with_temp_db):
    from fastapi.testclient import TestClient

    app, SessionLocal = app_with_temp_db
    _seed(SessionLocal)
    client = TestClient(app)
    body = client.get("/api/lessons").json()
    assert len(body["lessons"]) == 5
    assert body["total"] == 5


def test_scope_by_class(app_with_temp_db):
    from fastapi.testclient import TestClient

    app, SessionLocal = app_with_temp_db
    _seed(SessionLocal)
    client = TestClient(app)
    body = client.get("/api/lessons", params={"class_name": "1A"}).json()
    assert body["total"] == 3
    assert {l["class_name"] for l in body["lessons"]} == {"1A"}


def test_scope_by_teacher(app_with_temp_db):
    from fastapi.testclient import TestClient

    app, SessionLocal = app_with_temp_db
    _seed(SessionLocal)
    client = TestClient(app)
    body = client.get("/api/lessons", params={"teacher_name": "TeaA"}).json()
    assert body["total"] == 3
    assert {l["teacher_name"] for l in body["lessons"]} == {"TeaA"}


def test_scope_by_room(app_with_temp_db):
    from fastapi.testclient import TestClient

    app, SessionLocal = app_with_temp_db
    _seed(SessionLocal)
    client = TestClient(app)
    body = client.get("/api/lessons", params={"room_name": "R1"}).json()
    assert body["total"] == 3
    assert {l["classroom_name"] for l in body["lessons"]} == {"R1"}


def test_scope_matches_client_filter(app_with_temp_db):
    """A scoped fetch must equal fetch-all-then-filter-on-client for the
    same predicate -- the whole point of moving the filter server-side."""
    from fastapi.testclient import TestClient

    app, SessionLocal = app_with_temp_db
    _seed(SessionLocal)
    client = TestClient(app)
    all_rows = client.get("/api/lessons").json()["lessons"]
    for field, param, value in [
        ("class_name", "class_name", "1A"),
        ("teacher_name", "teacher_name", "TeaB"),
        ("classroom_name", "room_name", "R2"),
    ]:
        client_side = sorted(
            l["id"] for l in all_rows if l[field] == value)
        server_side = sorted(
            l["id"] for l in
            client.get("/api/lessons", params={param: value}).json()["lessons"])
        assert client_side == server_side, (field, value)


def test_limit_offset_pagination(app_with_temp_db):
    from fastapi.testclient import TestClient

    app, SessionLocal = app_with_temp_db
    _seed(SessionLocal)
    client = TestClient(app)
    body = client.get("/api/lessons", params={"limit": 2, "offset": 1}).json()
    # total is the unpaged count; the page itself is capped at 2.
    assert body["total"] == 5
    assert len(body["lessons"]) == 2
    # ordered by id, so offset=1 skips the first row.
    all_ids = [l["id"] for l in client.get("/api/lessons").json()["lessons"]]
    assert [l["id"] for l in body["lessons"]] == all_ids[1:3]
