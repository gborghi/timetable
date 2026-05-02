"""Tests for the run telemetry collector + readback."""
from __future__ import annotations

from backend.utils import telemetry as tel


def test_collector_module_imports():
    assert callable(tel.collector)
    assert callable(tel.fetch_telemetry)
    assert callable(tel.fetch_summary)


def test_collector_buffers_samples_in_memory():
    """Without a real run row, the collector still buffers samples
    in memory and the flush failure is silent (telemetry must not
    crash the solver)."""
    c = tel.TelemetryCollector(run_id=999_999, phase="test_phase",
                                 flush_every=10_000)
    for i in range(5):
        c.sample(step=i, objective_value=float(100 - i),
                  hard_violations_count=0,
                  placed_lessons_count=42)
    assert len(c._buffer) == 5
    # Flush will silently fail because run_id 999999 has no parent
    # row; the call must NOT raise.
    c.flush()


def test_summary_on_empty_run_returns_zero_samples():
    res = tel.fetch_summary(run_id=999_998)
    assert res["n_samples"] == 0
    assert res["phases"] == []


def test_collector_round_trip_with_real_run(tmp_path, monkeypatch):
    """Persist samples in an isolated DB and read them back."""
    # Build a fresh isolated DB
    db_url = f"sqlite:///{tmp_path / 'tel_test.db'}"
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from backend.db import Base
    from backend import models, db as db_mod

    monkeypatch.setattr(db_mod, "DB_URL", db_url)
    engine = create_engine(
        db_url, connect_args={"check_same_thread": False}, future=True,
    )
    Local = sessionmaker(bind=engine, autoflush=False,
                          autocommit=False, future=True)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(db_mod, "engine", engine)
    monkeypatch.setattr(db_mod, "SessionLocal", Local)
    monkeypatch.setattr(tel, "SessionLocal", Local)

    # Create a parent run row
    with Local() as db:
        r = models.Run(
            kind="test", name="t",
            params_json="{}",
            status="running",
            started_at=__import__("datetime").datetime.now(),
        )
        db.add(r)
        db.commit()
        db.refresh(r)
        run_id = r.id

    # Push 3 samples through the collector
    with tel.collector(run_id, phase="stage_lns",
                        flush_every=2) as c:
        c.sample(step=0, objective_value=100.0)
        c.sample(step=1, objective_value=95.0)
        c.sample(step=2, objective_value=90.0)

    # Read back
    samples = tel.fetch_telemetry(run_id)
    assert len(samples) == 3
    assert samples[0]["payload"]["objective_value"] == 100.0
    assert samples[2]["payload"]["objective_value"] == 90.0

    summary = tel.fetch_summary(run_id)
    assert summary["n_samples"] == 3
    assert summary["phases"][0]["best_obj"] == 90.0
