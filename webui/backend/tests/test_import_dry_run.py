"""POST /api/import/{entity}?dry=true is a non-persisting PREVIEW.

The importers commit internally; the endpoint transiently rebinds
``db.commit`` to ``db.flush`` and rolls back at the end, so a dry-run returns
accurate counts WITHOUT writing any row (and without wiping the table in
``replace`` mode).
"""
from __future__ import annotations


def _bind_global_db_to_temp(monkeypatch, temp_db_url: str):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from backend import db as db_mod
    from backend import models  # noqa: F401  -- registers tables

    engine = create_engine(
        temp_db_url, connect_args={"check_same_thread": False}, future=True)
    Local = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, future=True)
    db_mod.Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(db_mod, "DB_URL", temp_db_url, raising=False)
    monkeypatch.setattr(db_mod, "engine", engine)
    monkeypatch.setattr(db_mod, "SessionLocal", Local)
    return engine, Local


def _client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    _, Local = _bind_global_db_to_temp(
        monkeypatch, f"sqlite:///{tmp_path / 'imp.db'}")
    from backend.main import app
    from backend import db as db_mod

    def _override_get_db():
        s = Local()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[db_mod.get_db] = _override_get_db
    return TestClient(app), Local


_CSV = b"name\nMario Rossi\nAnna Bianchi\n"


def test_import_dry_run_reports_but_does_not_persist(monkeypatch, tmp_path):
    from backend import models
    client, Local = _client(monkeypatch, tmp_path)
    try:
        r = client.post(
            "/api/import/teachers",
            files={"file": ("t.csv", _CSV, "text/csv")},
            data={"mode": "upsert", "dry": "true"},
        )
        assert r.status_code == 200, r.text
        rep = r.json()
        assert rep["n_inserted"] == 2, rep          # accurate count
        # ...but nothing was written.
        with Local() as db:
            assert db.query(models.Teacher).count() == 0
    finally:
        client.app.dependency_overrides.clear()


def test_import_without_dry_persists(monkeypatch, tmp_path):
    from backend import models
    client, Local = _client(monkeypatch, tmp_path)
    try:
        r = client.post(
            "/api/import/teachers",
            files={"file": ("t.csv", _CSV, "text/csv")},
            data={"mode": "upsert"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["n_inserted"] == 2
        with Local() as db:
            assert db.query(models.Teacher).count() == 2
    finally:
        client.app.dependency_overrides.clear()
