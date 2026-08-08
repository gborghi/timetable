"""90-class school scenario tests (liceo90 + liceo90doc).

Uses the pre-seeded SQLite databases from engine/scripts/data/ and
runs Phase B via the FastAPI test client with proven parameters.

SLOW tests (~20 min each); tagged accordingly.
Requires: `pytest -m slow`
"""
from __future__ import annotations

import os
import shutil
import sys
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
ENGINE = os.path.join(REPO, "engine")
SCHEDULE = os.path.join(REPO, "schedule")
WEBUI = os.path.join(REPO, "webui")
for p in (WEBUI, ENGINE, SCHEDULE):
    if p not in sys.path:
        sys.path.insert(0, p)

DATA = os.path.join(ENGINE, "scripts", "data")

# Proven parameters — same used in the successful runs of 2026-08-06.
PHASE_B_PAYLOAD = {
    "k": 6,
    "time_a": 150,
    "time_mono": 300,
    "time_bridges": 20,
    "time_cluster": 20,
    "time_ricucitura": 20,
    "workers": 8,
    "use_decomposition": True,
    "cp_sat_scope": "day",
    "phase_a_mode": "always",
    "respect_room_capacity": True,
    "rooms_prefer_home": True,
}

POLL_SEC = 20
TIMEOUT_S = 1200  # 20 min per test


def _setup_and_launch(tmp_path, src_name: str):
    """Copy a pre-seeded DB, create plesso if missing, launch Phase B, poll."""
    from backend.main import app
    from backend.database import SessionLocal, engine as _global_engine
    from backend import models  # noqa: F401
    from backend.db import Base
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.orm import sessionmaker
    from fastapi.testclient import TestClient

    # 1. Copy seed DB to temp path
    src = os.path.join(DATA, src_name, f"{src_name}.sqlite")
    assert os.path.isfile(src), f"Seed DB not found: {src}"
    dst = tmp_path / f"{src_name}.db"
    shutil.copy2(src, dst)
    db_url = f"sqlite:///{dst}"

    # 2. Create engine + ensure plesso
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    plessi_count = session.query(models.Plesso).count()
    if plessi_count == 0:
        plesso = models.Plesso(name="SEDE", code="SEDE")
        session.add(plesso)
        session.commit()
    session.close()

    # 3. Monkey-patch the global SessionLocal to use our test DB.
    #    The TestClient uses the app's dependency overrides or the
    #    global DB; we override get_db via app.dependency_overrides.
    def _override_get_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides.clear()
    # Find the get_db dependency — it's typically in db.py
    from backend.db import get_db

    app.dependency_overrides[get_db] = _override_get_db

    client = TestClient(app)

    # 4. Clear any existing solutions so we start fresh
    client.post("/api/dataset/clear?scope=solutions")

    # 5. Launch Phase B
    resp = client.post("/api/optimize/phase-b", json=PHASE_B_PAYLOAD)
    assert resp.status_code == 200, f"Launch failed: {resp.text}"
    run_id = resp.json()["run_id"]

    # 6. Poll until done
    t0 = time.time()
    while (time.time() - t0) < TIMEOUT_S:
        r = client.get(f"/api/optimize/runs/{run_id}")
        assert r.status_code == 200, f"Poll failed: {r.text}"
        data = r.json()
        status = data["status"]
        if status in ("done", "failed"):
            metrics = data.get("metrics", {})
            return {
                "run_id": run_id,
                "status": status,
                "feasible": metrics.get("feasible", False),
                "coverage": metrics.get("coverage", 0.0),
                "obj": data.get("obj_value"),
                "elapsed_s": time.time() - t0,
            }
        time.sleep(POLL_SEC)

    pytest.fail(f"Run {run_id} timed out after {TIMEOUT_S}s")


@pytest.mark.slow
class TestLiceo90Turnazione:
    """liceo90 — room-of-class with biennio free-day rotation.
    90 classes, 87 rooms (< 90 thanks to turnazione), 187 teachers."""

    @pytest.fixture(scope="class")
    def result(self, tmp_path_factory):
        tmp = tmp_path_factory.mktemp("liceo90")
        return _setup_and_launch(tmp, "liceo90")

    def test_feasible(self, result):
        assert result["feasible"], f"not feasible: {result}"

    def test_full_coverage(self, result):
        assert result["coverage"] >= 0.99, f"coverage {result['coverage']:.1%} < 99%: {result}"

    def test_has_objective(self, result):
        assert result["obj"] is not None


@pytest.mark.slow
class TestLiceo90Doc:
    """liceo90doc — room-of-teacher (aule per materia).
    90 classes, 111 rooms partitioned by subject area, 187 teachers."""

    @pytest.fixture(scope="class")
    def result(self, tmp_path_factory):
        tmp = tmp_path_factory.mktemp("liceo90doc")
        return _setup_and_launch(tmp, "liceo90doc")

    def test_feasible(self, result):
        assert result["feasible"], f"not feasible: {result}"

    def test_full_coverage(self, result):
        assert result["coverage"] >= 0.99, f"coverage {result['coverage']:.1%} < 99%: {result}"

    def test_has_objective(self, result):
        assert result["obj"] is not None
