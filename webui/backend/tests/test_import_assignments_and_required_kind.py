"""Finding 02 (cattedre importer) and finding 29 (Subject.required_kind
reachable via schema + import)."""
from fastapi.testclient import TestClient

from backend import models
from backend.routers import imports as imp


def _seed_class_and_teacher(db):
    cl = models.SchoolClass(name="1A")
    db.add(cl)
    db.flush()
    db.add(models.ClassSubject(class_id=cl.id, subject="Matematica",
                               hours_per_week=5))
    t = models.Teacher(name="Mario Rossi", max_hours=18)
    db.add(t)
    db.flush()
    db.add(models.TeacherSubject(teacher_id=t.id, subject="Matematica"))
    db.commit()


def test_assignments_importer_creates_cattedra(app_with_temp_db):
    _app, Session = app_with_temp_db
    with Session() as db:
        _seed_class_and_teacher(db)
        rep = imp._import_assignments(db, [
            {"teacher": "Mario Rossi", "class": "1A", "subject": "Matematica"},
        ], "upsert")
        assert rep.n_inserted == 1 and not rep.errors
        a = db.query(models.Assignment).one()
        assert a.subject == "Matematica"
        assert a.hours == 5   # taken from the curriculum, not the row


def test_assignments_importer_reports_merit_errors(app_with_temp_db):
    _app, Session = app_with_temp_db
    with Session() as db:
        _seed_class_and_teacher(db)
        rep = imp._import_assignments(db, [
            {"teacher": "Mario Rossi", "class": "1A", "subject": "Storia"},
        ], "upsert")
        assert rep.n_inserted == 0
        assert rep.errors and "materia Storia" in rep.errors[0]


def test_assignments_registered_and_templated(app_with_temp_db):
    app, _Session = app_with_temp_db
    client = TestClient(app)
    assert "assignments" in imp._IMPORTERS
    r = client.get("/api/import/assignments/template")
    assert r.status_code == 200


def test_required_kind_via_api_and_import(app_with_temp_db):
    app, Session = app_with_temp_db
    client = TestClient(app)
    # API round-trip
    client.post("/api/subjects", json={
        "name": "Scienze motorie", "required_kind": "palestra"}).raise_for_status()
    got = client.get("/api/subjects").json()
    row = next(s for s in (got["items"] if isinstance(got, dict) else got)
               if s["name"] == "Scienze motorie")
    assert row["required_kind"] == "palestra"
    # Import round-trip
    with Session() as db:
        imp._import_subjects(db, [
            {"name": "Fisica", "required_kind": "lab_fisica"}], "upsert")
        s = db.query(models.Subject).filter(
            models.Subject.name == "Fisica").one()
        assert s.required_kind == "lab_fisica"
