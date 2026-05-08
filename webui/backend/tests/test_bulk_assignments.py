"""Smoke tests for /api/assignments/bulk/{delete,lock,change-teacher,
set-flag}.

Covers the four bulk actions surfaced on /assignments. Builds a tiny
scenario in a tmp DB (3 cattedre across 2 classes + 2 teachers), then
exercises each endpoint through the FastAPI TestClient and asserts
the bulk result + the resulting DB state.
"""
from __future__ import annotations


def _seed(SessionLocal):
    """Two teachers, two classes, three Assignment rows.
    TeaA qualified for Mat + Sto; TeaB qualified for Eng only."""
    from backend import models

    s = SessionLocal()
    try:
        teaA = models.Teacher(name="TeaA", max_hours=18)
        teaB = models.Teacher(name="TeaB", max_hours=18)
        cls1A = models.SchoolClass(name="1A", n_students=20)
        cls1B = models.SchoolClass(name="1B", n_students=22)
        s.add_all([teaA, teaB, cls1A, cls1B])
        s.flush()

        # TeacherSubject qualifications
        s.add_all([
            models.TeacherSubject(teacher_id=teaA.id, subject="Mat"),
            models.TeacherSubject(teacher_id=teaA.id, subject="Sto"),
            models.TeacherSubject(teacher_id=teaB.id, subject="Eng"),
        ])
        s.flush()

        a1 = models.Assignment(class_id=cls1A.id, teacher_id=teaA.id,
                                subject="Mat", hours=4, locked=False)
        a2 = models.Assignment(class_id=cls1B.id, teacher_id=teaA.id,
                                subject="Sto", hours=2, locked=False)
        a3 = models.Assignment(class_id=cls1A.id, teacher_id=teaB.id,
                                subject="Eng", hours=3, locked=False)
        s.add_all([a1, a2, a3])
        s.commit()
        return [a1.id, a2.id, a3.id], teaA.id, teaB.id
    finally:
        s.close()


def test_bulk_delete_removes_only_listed_ids(app_with_temp_db):
    from fastapi.testclient import TestClient
    from backend import models

    app, SessionLocal = app_with_temp_db
    [a1, a2, a3], _, _ = _seed(SessionLocal)
    client = TestClient(app)

    r = client.post("/api/assignments/bulk/delete",
                    json={"ids": [a1, a3]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["n_applied"] == 2
    assert body["n_skipped"] == 0

    # Only a2 survives.
    s = SessionLocal()
    try:
        rows = s.query(models.Assignment).all()
        assert len(rows) == 1
        assert rows[0].id == a2
    finally:
        s.close()


def test_bulk_delete_unknown_id_reported_as_skipped(app_with_temp_db):
    from fastapi.testclient import TestClient

    app, SessionLocal = app_with_temp_db
    [a1, _, _], _, _ = _seed(SessionLocal)
    client = TestClient(app)
    r = client.post("/api/assignments/bulk/delete",
                    json={"ids": [a1, 99999]})
    body = r.json()
    assert body["n_applied"] == 1
    assert body["n_skipped"] == 1
    assert any("99999" in e for e in body["errors"])


def test_bulk_lock_sets_locked_on_every_id(app_with_temp_db):
    from fastapi.testclient import TestClient
    from backend import models

    app, SessionLocal = app_with_temp_db
    ids, _, _ = _seed(SessionLocal)
    client = TestClient(app)
    r = client.post("/api/assignments/bulk/lock",
                    json={"ids": ids, "locked": True})
    assert r.status_code == 200
    body = r.json()
    assert body["n_applied"] == 3
    s = SessionLocal()
    try:
        for a in s.query(models.Assignment).all():
            assert a.locked is True
    finally:
        s.close()


def test_bulk_lock_can_unlock(app_with_temp_db):
    from fastapi.testclient import TestClient
    from backend import models

    app, SessionLocal = app_with_temp_db
    ids, _, _ = _seed(SessionLocal)
    client = TestClient(app)
    # Lock first.
    client.post("/api/assignments/bulk/lock",
                json={"ids": ids, "locked": True})
    # Now unlock.
    client.post("/api/assignments/bulk/lock",
                json={"ids": ids, "locked": False})
    s = SessionLocal()
    try:
        for a in s.query(models.Assignment).all():
            assert a.locked is False
    finally:
        s.close()


def test_bulk_change_teacher_skips_unqualified_subjects(app_with_temp_db):
    """TeaB only teaches Eng; trying to assign every cattedra to TeaB
    succeeds for the Eng row (a3) and skips Mat/Sto with errors."""
    from fastapi.testclient import TestClient
    from backend import models

    app, SessionLocal = app_with_temp_db
    [a1, a2, a3], _, teaB_id = _seed(SessionLocal)
    client = TestClient(app)
    r = client.post("/api/assignments/bulk/change-teacher",
                    json={"ids": [a1, a2, a3], "teacher_name": "TeaB"})
    body = r.json()
    # a3 (Eng) is changeable; a1 (Mat) + a2 (Sto) are not.
    assert body["n_applied"] == 1
    assert body["n_skipped"] == 2
    assert len(body["errors"]) == 2
    assert all("non e' qualificato" in e for e in body["errors"])

    s = SessionLocal()
    try:
        # a3 was changed; a1, a2 unchanged.
        a3_db = s.get(models.Assignment, a3)
        assert a3_db.teacher_id == teaB_id
    finally:
        s.close()


def test_bulk_change_teacher_unknown_teacher_404(app_with_temp_db):
    from fastapi.testclient import TestClient

    app, SessionLocal = app_with_temp_db
    ids, _, _ = _seed(SessionLocal)
    client = TestClient(app)
    r = client.post("/api/assignments/bulk/change-teacher",
                    json={"ids": ids, "teacher_name": "NonEsiste"})
    assert r.status_code == 404


def test_bulk_set_flag_potenziamento(app_with_temp_db):
    from fastapi.testclient import TestClient
    from backend import models

    app, SessionLocal = app_with_temp_db
    ids, _, _ = _seed(SessionLocal)
    client = TestClient(app)
    r = client.post("/api/assignments/bulk/set-flag",
                    json={"ids": ids, "flag": "is_potenziamento",
                          "value": True})
    assert r.status_code == 200
    body = r.json()
    assert body["n_applied"] == 3
    s = SessionLocal()
    try:
        for a in s.query(models.Assignment).all():
            assert a.is_potenziamento is True
    finally:
        s.close()


def test_bulk_set_flag_invalid_flag_400(app_with_temp_db):
    from fastapi.testclient import TestClient

    app, SessionLocal = app_with_temp_db
    ids, _, _ = _seed(SessionLocal)
    client = TestClient(app)
    r = client.post("/api/assignments/bulk/set-flag",
                    json={"ids": ids, "flag": "locked", "value": True})
    # 'locked' is a column but not in the safe-list, so 400.
    assert r.status_code == 400


def test_bulk_delete_empty_ids_returns_ok(app_with_temp_db):
    from fastapi.testclient import TestClient

    app, SessionLocal = app_with_temp_db
    _seed(SessionLocal)
    client = TestClient(app)
    r = client.post("/api/assignments/bulk/delete", json={"ids": []})
    body = r.json()
    assert body["ok"] is True
    assert body["n_applied"] == 0
