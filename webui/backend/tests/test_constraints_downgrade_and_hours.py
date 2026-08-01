"""Finding 11: POST /api/constraints must not silently weaken a HARD cell
to soft. Finding 12: /api/assignments/manual must not silently ignore a
conflicting `hours` for a class target."""
from fastapi.testclient import TestClient

from backend import models, optimization


def test_hard_cell_not_silently_downgraded(app_with_temp_db):
    app, Session = app_with_temp_db
    client = TestClient(app)
    with Session() as db:
        t = models.Teacher(name="Damico Elena")
        db.add(t)
        db.commit()
        tid = t.id

    base = {"scope": "teacher", "kind": "matrix_slot", "owner_id": tid,
            "day": 6, "hour": 8}
    # Create the HARD cell.
    r = client.post("/api/constraints", json={**base, "level": "hard"})
    assert r.status_code == 200
    # Trying to overwrite it with soft is refused (409), not silent.
    r = client.post("/api/constraints", json={**base, "level": "soft"})
    assert r.status_code == 409 and "rigido" in r.json()["detail"]
    with Session() as db:
        cell = db.query(models.TeacherUnavailability).filter(
            models.TeacherUnavailability.teacher_id == tid).one()
        assert cell.state == "hard"   # untouched
    # With explicit force it goes through.
    r = client.post("/api/constraints",
                    json={**base, "level": "soft", "force": True})
    assert r.status_code == 200
    with Session() as db:
        cell = db.query(models.TeacherUnavailability).filter(
            models.TeacherUnavailability.teacher_id == tid).one()
        assert cell.state == "soft"


def test_manual_assignment_rejects_conflicting_hours(app_with_temp_db):
    _app, Session = app_with_temp_db
    with Session() as db:
        cl = models.SchoolClass(name="1A")
        db.add(cl)
        db.flush()
        db.add(models.ClassSubject(class_id=cl.id, subject="Matematica",
                                   hours_per_week=5))
        t = models.Teacher(name="Rossi", max_hours=18)
        db.add(t)
        db.flush()
        db.add(models.TeacherSubject(teacher_id=t.id, subject="Matematica"))
        db.commit()

        # Conflicting hours -> rejected, not silently ignored.
        ok, reason, _ = optimization.manual_assignment(
            db, class_name="1A", subject="Matematica",
            teacher_name="Rossi", hours=3)
        assert ok is False and "curricolo" in reason

        # Matching (or omitted) hours -> accepted, uses curriculum's 5.
        ok, _reason, obj = optimization.manual_assignment(
            db, class_name="1A", subject="Matematica",
            teacher_name="Rossi", hours=5)
        assert ok is True and obj.hours == 5
