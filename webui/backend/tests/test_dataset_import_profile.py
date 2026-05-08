"""Regression tests for the Dashboard "Importa un profilo gia` calcolato"
flow (POST /api/dataset/import-profile).

The dropdown is populated by GET /api/dataset/available-profiles, which
walks engine/scripts/data/<profile>/ and engine/scripts/output/<profile>/
on disk. These tests pin two behaviours that broke in production:

1) The mega profile imports anagrafica AND lessons. Before the xlsx-
   fallback was added, mega had no solution_*.pkl checked in and the
   import only loaded classes / teachers / assignments — leaving
   /schedule (which reads from the Lesson table) blank.

2) An xlsx-only profile (no solution pickle) is still importable. The
   helper engine_io.solution_dict_from_class_xlsx parses the
   orario_classi xlsx exporter output back into a solution dict.
"""
from __future__ import annotations

import os
import threading
import time

import pytest

REPO_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
MEGA_SCHOOL = os.path.join(
    REPO_ROOT, "engine", "scripts", "data", "mega", "school_mega.pkl",
)
MEGA_XLSX = os.path.join(
    REPO_ROOT, "engine", "scripts", "output", "mega",
    "orario_classi_mega.xlsx",
)


def _bind_global_db_to_temp(monkeypatch, temp_db_url: str):
    """Point every module-level SessionLocal at a private engine on
    `temp_db_url`. This is what lets us call optimization.import_engine_profile
    (which uses background threads) against a tmp DB without touching
    the dev DB on disk.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from backend import db as db_mod
    from backend import models  # noqa: F401  -- registers tables

    engine = create_engine(
        temp_db_url,
        connect_args={"check_same_thread": False},
        future=True,
    )
    Local = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, future=True,
    )
    db_mod.Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_mod, "DB_URL", temp_db_url, raising=False)
    monkeypatch.setattr(db_mod, "engine", engine)
    monkeypatch.setattr(db_mod, "SessionLocal", Local)

    # Modules that bound `from .db import SessionLocal` at import time
    # hold their own reference; rebind them too.
    from backend import optimization, run_manager
    from backend.utils import telemetry
    monkeypatch.setattr(optimization, "SessionLocal", Local)
    monkeypatch.setattr(run_manager, "SessionLocal", Local)
    monkeypatch.setattr(telemetry, "SessionLocal", Local)

    return engine, Local


def _wait_for_run(run_id: int, timeout: float = 60.0):
    from backend import run_manager
    t = run_manager._THREADS.get(run_id)
    if t is not None:
        t.join(timeout=timeout)
        assert not t.is_alive(), f"run {run_id} did not finish in {timeout}s"


# ---------------------------------------------------------------------------
# Pure unit test: xlsx -> solution dict parser
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.path.exists(MEGA_XLSX),
    reason="orario_classi_mega.xlsx not checked in",
)
def test_solution_dict_from_class_xlsx_parses_mega():
    from backend import engine_io
    sol = engine_io.solution_dict_from_class_xlsx(MEGA_XLSX)
    # mega: 100 classi x ~30 ore/sett ~= 3000 cells
    assert len(sol) > 1000, f"expected >1000 cells, got {len(sol)}"
    # every key is a 5-tuple of (str, str, str, int, int) with day in
    # [1..6] and hour in a sane range
    days = {k[3] for k in sol}
    hours = {k[4] for k in sol}
    assert days <= {1, 2, 3, 4, 5, 6}
    assert all(1 <= h <= 12 for h in hours)


# ---------------------------------------------------------------------------
# End-to-end: POST /api/dataset/import-profile -> GET /api/lessons > 0
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not (os.path.exists(MEGA_SCHOOL) and os.path.exists(MEGA_XLSX)),
    reason="mega school pickle or xlsx missing on disk",
)
def test_import_mega_populates_lessons(tmp_path, monkeypatch):
    """End-to-end: a fresh DB + POST /api/dataset/import-profile{mega}
    leaves the Lesson table non-empty AND sets an active solution.

    Before the xlsx-fallback fix, this returned 0 lessons because the
    mega solution pickle is gitignored.
    """
    from fastapi.testclient import TestClient

    db_url = f"sqlite:///{tmp_path / 'import_mega.db'}"
    _, Local = _bind_global_db_to_temp(monkeypatch, db_url)

    from backend.main import app
    from backend import db as db_mod, run_manager, models

    # The TestClient dispatches /api/lessons through get_db; route it
    # to the temp engine alongside the SessionLocal monkeypatch.
    def _override_get_db():
        s = Local()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[db_mod.get_db] = _override_get_db
    try:
        client = TestClient(app)

        # Disable the pool-data side effects (curricula seeding,
        # classroom auto-gen, student faker) — they exercise modules
        # we're not testing here and slow the test down.
        r = client.post("/api/dataset/import-profile", json={
            "profile": "mega",
            "use_optimized": True,
            "import_curricula": False,
            "import_classrooms": False,
            "import_students": False,
        })
        assert r.status_code == 200, r.text
        run_id = r.json()["run_id"]
        _wait_for_run(run_id, timeout=120.0)

        # Run row marks success
        with Local() as db:
            run = db.get(models.Run, run_id)
            assert run is not None
            assert run.status == "done", f"run failed: {run.error}"

        # Active solution + lessons populated
        r = client.get("/api/lessons")
        assert r.status_code == 200, r.text
        body = r.json()
        lessons = body["lessons"]
        assert len(lessons) > 1000, (
            f"expected >1000 lessons after mega import, got {len(lessons)}"
        )

        # Sanity: dataset/state surfaces an active solution id
        r = client.get("/api/dataset/state")
        assert r.status_code == 200
        st = r.json()
        assert st.get("active_solution") is not None, (
            "active_solution should be set after import"
        )
    finally:
        app.dependency_overrides.pop(db_mod.get_db, None)
        # Drain the run-manager thread registry so subsequent tests
        # don't see a stale entry.
        run_manager._THREADS.pop(run_id, None) if "run_id" in dir() else None
