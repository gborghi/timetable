"""Finding 03: a plain GET-then-PUT of a teacher must not turn the
API-derived free-day autofill cells into real persisted HARD constraints.
"""
from fastapi.testclient import TestClient

from backend import models


def _client(app_with_temp_db):
    app, Session = app_with_temp_db
    return TestClient(app), Session


def _persisted_unavail(Session, tid):
    with Session() as db:
        return db.query(models.TeacherUnavailability).filter(
            models.TeacherUnavailability.teacher_id == tid).all()


def test_get_then_put_does_not_persist_autofilled_free_day(app_with_temp_db):
    client, Session = _client(app_with_temp_db)
    # A teacher with a legacy free_day but ZERO real unavailability rows.
    with Session() as db:
        t = models.Teacher(name="Rossi Maria", free_day="Sabato")
        db.add(t)
        db.commit()
        tid = t.id

    # GET surfaces 6 synthetic HARD cells for Saturday (display only).
    got = client.get(f"/api/teachers/{tid}").json()
    syn = [c for c in got["unavailability"] if c.get("synthetic")]
    assert len(syn) == 6, "GET should surface the 6 autofilled free-day cells"
    assert all(c["day"] == 6 for c in syn)

    # A plain save round-trips exactly what GET returned.
    client.put(f"/api/teachers/{tid}", json=got).raise_for_status()

    # None of the synthetic cells may have been persisted.
    rows = _persisted_unavail(Session, tid)
    assert rows == [], (
        "autofilled free-day cells leaked into the DB as real constraints")


def test_real_unavailability_is_still_persisted(app_with_temp_db):
    client, Session = _client(app_with_temp_db)
    with Session() as db:
        t = models.Teacher(name="Bianchi Ugo", free_day="Sabato")
        db.add(t)
        db.commit()
        tid = t.id
    got = client.get(f"/api/teachers/{tid}").json()
    # Add a genuine, user-entered cell (not synthetic).
    got["unavailability"].append({
        "day": 2, "hour": 9, "state": "hard",
        "soft_penalty": 100, "reason": "impegno personale",
    })
    client.put(f"/api/teachers/{tid}", json=got).raise_for_status()
    rows = _persisted_unavail(Session, tid)
    assert len(rows) == 1
    assert (rows[0].day, rows[0].hour) == (2, 9)
    assert "(auto" not in (rows[0].reason or "")
