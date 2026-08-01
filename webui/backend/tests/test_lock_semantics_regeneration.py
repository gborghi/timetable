"""Finding 26: `Assignment.locked` ('confirmed cattedra') must NOT freeze
the timetable's hours; only a pinned `Lesson.locked` ('immovable hour') is
fed to the solver as a fixed slot. A school that confirms all its cattedre
must still be able to regenerate.
"""
import datetime as dt

from fastapi.testclient import TestClient

from backend import models, optimization


def _seed_active_solution_with_locked_cattedra(Session):
    with Session() as db:
        t = models.Teacher(name="Longo Paolo")
        c = models.SchoolClass(name="1B")
        db.add_all([t, c])
        db.flush()
        # A CONFIRMED cattedra (locked) -- the school says "don't reassign".
        db.add(models.Assignment(teacher_id=t.id, class_id=c.id,
                                 subject="Matematica", hours=3, locked=True))
        sol = models.Solution(name="s", kind="phase_b", is_active=True,
                              created_at=dt.datetime.utcnow())
        db.add(sol)
        db.flush()
        for h in (8, 9, 10):
            db.add(models.Lesson(solution_id=sol.id, teacher_name="Longo Paolo",
                                 class_name="1B", subject="Matematica",
                                 day=1, hour=h))
        db.commit()
        return sol.id


def test_locked_cattedra_does_not_freeze_hours(app_with_temp_db):
    _app, Session = app_with_temp_db
    _seed_active_solution_with_locked_cattedra(Session)
    with Session() as db:
        # Regeneration reads NO immovable slots: the confirmed cattedra
        # leaves the hours free to be re-placed (was: all 3 hours frozen).
        assert optimization._read_locked_lessons(db) == []


def test_pinned_lesson_is_the_only_immovable_slot(app_with_temp_db):
    app, Session = app_with_temp_db
    _seed_active_solution_with_locked_cattedra(Session)
    with Session() as db:
        lesson = db.query(models.Lesson).filter(
            models.Lesson.hour == 9).one()
        lesson_id = lesson.id

    # Pin one lesson via the schedule endpoint.
    client = TestClient(app)
    r = client.post(f"/api/schedule/lessons/{lesson_id}/pin",
                    params={"locked": True})
    assert r.status_code == 200 and r.json()["locked"] is True

    with Session() as db:
        snap = optimization._read_locked_lessons(db)
        assert len(snap) == 1
        assert (snap[0]["day"], snap[0]["hour"]) == (1, 9)

    # Unpin -> back to fully free.
    client.post(f"/api/schedule/lessons/{lesson_id}/pin",
                params={"locked": False})
    with Session() as db:
        assert optimization._read_locked_lessons(db) == []
