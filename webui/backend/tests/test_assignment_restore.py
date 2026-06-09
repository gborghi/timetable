"""POST /api/assignments/bulk/restore recreates assignments from snapshots
(the backend half of the assignment bulk-delete UNDO)."""
from __future__ import annotations


def _client(monkeypatch, tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from fastapi.testclient import TestClient
    from backend import db as db_mod
    from backend import models  # noqa: F401

    engine = create_engine(
        f"sqlite:///{tmp_path / 'a.db'}",
        connect_args={"check_same_thread": False}, future=True)
    Local = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, future=True)
    db_mod.Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(db_mod, "engine", engine)
    monkeypatch.setattr(db_mod, "SessionLocal", Local)
    from backend.main import app

    def _ov():
        s = Local()
        try:
            yield s
        finally:
            s.close()
    app.dependency_overrides[db_mod.get_db] = _ov
    return TestClient(app), Local


def test_bulk_delete_then_restore_roundtrip(monkeypatch, tmp_path):
    from backend import models
    client, Local = _client(monkeypatch, tmp_path)
    try:
        with Local() as db:
            t = models.Teacher(name="Rossi")
            c = models.SchoolClass(name="1A")
            db.add(t)
            db.add(c)
            db.commit()
            a = models.Assignment(teacher_id=t.id, class_id=c.id,
                                  subject="Mat", hours=3)
            db.add(a)
            db.commit()
            aid, tid, cid = a.id, t.id, c.id

        # delete it
        r = client.post("/api/assignments/bulk/delete", json={"ids": [aid]})
        assert r.status_code == 200 and r.json()["n_applied"] == 1
        with Local() as db:
            assert db.query(models.Assignment).count() == 0

        # restore from snapshot
        r = client.post("/api/assignments/bulk/restore", json={"items": [{
            "teacher_id": tid, "class_id": cid, "subject": "Mat",
            "hours": 3, "locked": False}]})
        assert r.status_code == 200, r.text
        assert r.json()["n_applied"] == 1
        with Local() as db:
            rows = db.query(models.Assignment).all()
            assert len(rows) == 1
            assert rows[0].teacher_id == tid and rows[0].subject == "Mat"
    finally:
        client.app.dependency_overrides.clear()


def test_restore_skips_unknown_teacher(monkeypatch, tmp_path):
    from backend import models
    client, Local = _client(monkeypatch, tmp_path)
    try:
        r = client.post("/api/assignments/bulk/restore", json={"items": [
            {"teacher_id": 99999, "subject": "X", "hours": 1}]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["n_applied"] == 0 and body["n_skipped"] == 1
        with Local() as db:
            assert db.query(models.Assignment).count() == 0
    finally:
        client.app.dependency_overrides.clear()
