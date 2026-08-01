"""Findings 05 (imported free_day reaches the solver), 06 (classroom
plesso column), 07 (teacher unavailability import)."""
from backend import models
from backend.routers import imports as imp


def test_imported_free_day_becomes_mandatory_free_day(app_with_temp_db):
    _app, Session = app_with_temp_db
    with Session() as db:
        imp._import_teachers(db, [
            {"name": "Rossi Maria", "free_day": "Sabato",
             "subjects": "Matematica"},
        ], "upsert")
        t = db.query(models.Teacher).filter(
            models.Teacher.name == "Rossi Maria").one()
        mfd = db.query(models.TeacherMandatoryFreeDay).filter(
            models.TeacherMandatoryFreeDay.teacher_id == t.id).all()
        assert [m.day for m in mfd] == [6]   # Saturday, HARD, solver-visible

    # Re-import must not duplicate the mandatory free day.
    with Session() as db:
        imp._import_teachers(db, [
            {"name": "Rossi Maria", "free_day": "Sabato"}], "upsert")
        t = db.query(models.Teacher).filter(
            models.Teacher.name == "Rossi Maria").one()
        assert db.query(models.TeacherMandatoryFreeDay).filter(
            models.TeacherMandatoryFreeDay.teacher_id == t.id).count() == 1


def test_classroom_import_resolves_plesso(app_with_temp_db):
    _app, Session = app_with_temp_db
    with Session() as db:
        imp._import_classrooms(db, [
            {"name": "Aula A-2B", "kind": "standard", "plesso": "Succursale"},
            {"name": "Aula A-1A", "kind": "standard", "plesso": "Succursale"},
        ], "upsert")
        plessi = db.query(models.Plesso).all()
        assert len(plessi) == 1 and plessi[0].name == "Succursale"
        assert plessi[0].code   # a non-empty derived code
        rooms = db.query(models.Classroom).all()
        assert all(r.plesso_id == plessi[0].id for r in rooms)


def test_teacher_unavailability_import(app_with_temp_db):
    _app, Session = app_with_temp_db
    with Session() as db:
        db.add(models.Teacher(name="Bianchi Ugo"))
        db.commit()
        rep = imp._import_teacher_unavailability(db, [
            {"teacher": "Bianchi Ugo", "day": "Lunedi", "hour": 8,
             "state": "hard"},
            {"teacher": "Bianchi Ugo", "day": 1, "hour": 9, "state": "soft",
             "soft_penalty": 50},
            {"teacher": "Ignoto", "day": 1, "hour": 8},   # -> error row
        ], "upsert")
        assert rep.n_inserted == 2 and len(rep.errors) == 1
        rows = db.query(models.TeacherUnavailability).all()
        assert {(r.day, r.hour, r.state) for r in rows} == {
            (1, 8, "hard"), (1, 9, "soft")}
