"""Integration: POST /api/dashboard/constraints/import-vincoli creates
constraints from a Vincoli record set, and the template endpoint serves xlsx.
"""
from __future__ import annotations

import json


def _bind(monkeypatch, tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from backend import db as db_mod
    from backend import models  # noqa: F401

    engine = create_engine(
        f"sqlite:///{tmp_path / 'v.db'}",
        connect_args={"check_same_thread": False}, future=True)
    Local = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, future=True)
    db_mod.Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(db_mod, "engine", engine)
    monkeypatch.setattr(db_mod, "SessionLocal", Local)
    return Local


def _client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    Local = _bind(monkeypatch, tmp_path)
    from backend.main import app
    from backend import db as db_mod

    def _ov():
        s = Local()
        try:
            yield s
        finally:
            s.close()
    app.dependency_overrides[db_mod.get_db] = _ov
    return TestClient(app), Local


def test_import_vincoli_creates_general_constraints(monkeypatch, tmp_path):
    from backend import models
    client, Local = _client(monkeypatch, tmp_path)
    try:
        recs = [
            {"tipo_vincolo": "max_ore_giorno", "nome": "Rossi Mario",
             "valore": 5},
            {"tipo_vincolo": "no_giorni_consecutivi", "nome": "3B"},
            {"tipo_vincolo": "raw_dsl", "entita": "globale",
             "dsl": "forall t in teachers: teacher_max_consecutive(t.name, 4)"},
            {"tipo_vincolo": "bogus", "nome": "x"},   # parse error
        ]
        blob = json.dumps(recs).encode("utf-8")
        r = client.post(
            "/api/dashboard/constraints/import-vincoli",
            files={"file": ("v.json", blob, "application/json")})
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["n_created"] == 3, j
        assert len(j["parse_errors"]) == 1, j
        with Local() as db:
            assert db.query(models.GeneralConstraint).count() == 3
    finally:
        client.app.dependency_overrides.clear()


def test_template_vincoli_is_xlsx(monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path)
    try:
        r = client.get("/api/dashboard/constraints/template-vincoli")
        assert r.status_code == 200, r.text
        assert "spreadsheetml.sheet" in r.headers.get("content-type", "")
        assert r.content[:2] == b"PK"   # xlsx is a zip
    finally:
        client.app.dependency_overrides.clear()
