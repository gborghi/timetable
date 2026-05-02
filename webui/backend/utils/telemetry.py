"""Run telemetry collector.

Solver / metaheuristic modules write samples here while a Run is
alive. Samples are buffered in-memory and flushed to the
`run_telemetry` table in batches to keep DB contention low.

Usage from inside an `optimization.run_*` thread:

    from .utils import telemetry as tel
    with tel.collector(run_id, phase="stage_lns") as t:
        ...
        t.sample(step=i, objective_value=cur_obj,
                  hard_violations_count=0,
                  placed_events_pct=100.0,
                  accepted_moves=accepted, rejected_moves=rejected)

The collector is a context manager: at exit it flushes any
buffered samples to the DB.
"""
from __future__ import annotations

import contextlib
import json
import threading
import time
from typing import Any, Iterator

from .. import models
from ..db import SessionLocal


_LOCK = threading.Lock()


class TelemetryCollector:
    """One collector per (run_id, phase) span."""

    __slots__ = ("run_id", "phase", "_t0", "_buffer", "_flush_every",
                  "_last_flush_at")

    def __init__(self, run_id: int, phase: str, flush_every: int = 50):
        self.run_id = int(run_id)
        self.phase = str(phase or "")
        self._t0 = time.time()
        self._buffer: list[dict[str, Any]] = []
        self._flush_every = flush_every
        self._last_flush_at = self._t0

    def sample(self, *, step: int = 0, **kwargs: Any) -> None:
        """Record one sample. `step` is a producer-side iteration
        counter; the rest of the kwargs go in `payload_json`.
        """
        ts = time.time() - self._t0
        # Keep only json-serialisable scalars (strings and numbers)
        payload = {
            k: v for k, v in kwargs.items()
            if isinstance(v, (int, float, bool, str)) or v is None
        }
        self._buffer.append({
            "step": int(step),
            "timestamp_s": float(ts),
            "phase": self.phase,
            "payload_json": json.dumps(payload, default=str),
        })
        if len(self._buffer) >= self._flush_every:
            self.flush()

    def flush(self) -> int:
        """Persist buffered samples and clear the buffer."""
        if not self._buffer:
            return 0
        rows = self._buffer
        self._buffer = []
        # Run the insert in its own session; the parent thread can
        # be holding another session.
        with _LOCK:
            try:
                with SessionLocal() as db:
                    for r in rows:
                        # Tolerate unique constraint violations (same
                        # step+phase emitted twice): just skip.
                        try:
                            db.add(models.RunTelemetry(
                                run_id=self.run_id,
                                step=r["step"],
                                timestamp_s=r["timestamp_s"],
                                phase=r["phase"],
                                payload_json=r["payload_json"],
                            ))
                            db.flush()
                        except Exception:
                            db.rollback()
                            continue
                    db.commit()
            except Exception as e:  # noqa: BLE001
                # Telemetry must NEVER crash the solver. Log silently.
                print(f"[telemetry] flush error: {e}")
        return len(rows)


@contextlib.contextmanager
def collector(run_id: int, *, phase: str = "",
              flush_every: int = 50) -> Iterator[TelemetryCollector]:
    """Context manager wrapping TelemetryCollector. Flushes on exit."""
    c = TelemetryCollector(run_id, phase, flush_every=flush_every)
    try:
        yield c
    finally:
        c.flush()


def fetch_telemetry(run_id: int, *, limit: int = 5000,
                    offset: int = 0,
                    phase: str | None = None) -> list[dict[str, Any]]:
    """Read back the telemetry of a run as a list of dicts.

    Each entry has keys: step, timestamp_s, phase, payload (parsed
    from payload_json).
    """
    with SessionLocal() as db:
        q = db.query(models.RunTelemetry).filter(
            models.RunTelemetry.run_id == run_id
        )
        if phase:
            q = q.filter(models.RunTelemetry.phase == phase)
        q = q.order_by(
            models.RunTelemetry.timestamp_s.asc(),
            models.RunTelemetry.step.asc(),
        )
        rows = q.offset(int(offset)).limit(int(limit)).all()
        out = []
        for r in rows:
            try:
                payload = json.loads(r.payload_json or "{}")
            except Exception:
                payload = {}
            out.append({
                "step": r.step,
                "timestamp_s": r.timestamp_s,
                "phase": r.phase,
                "payload": payload,
            })
        return out


def fetch_summary(run_id: int) -> dict[str, Any]:
    """Aggregate stats for a run's telemetry."""
    samples = fetch_telemetry(run_id, limit=100000)
    if not samples:
        return {"n_samples": 0, "phases": [], "duration_s": 0.0}
    phases: dict[str, dict[str, Any]] = {}
    obj_series = []
    for s in samples:
        ph = s["phase"] or ""
        node = phases.setdefault(ph, {
            "phase": ph, "n_samples": 0,
            "first_t": float("inf"), "last_t": 0.0,
            "best_obj": None,
        })
        node["n_samples"] += 1
        node["first_t"] = min(node["first_t"], float(s["timestamp_s"]))
        node["last_t"] = max(node["last_t"], float(s["timestamp_s"]))
        obj = (s["payload"] or {}).get("objective_value")
        if obj is not None:
            try:
                ov = float(obj)
                if node["best_obj"] is None or ov < node["best_obj"]:
                    node["best_obj"] = ov
                obj_series.append((float(s["timestamp_s"]), ov, ph))
            except (TypeError, ValueError):
                pass
    return {
        "n_samples": len(samples),
        "duration_s": (samples[-1]["timestamp_s"]
                        - samples[0]["timestamp_s"]
                        if samples else 0.0),
        "phases": [phases[k] for k in phases],
        "objective_series": [
            {"t": t, "obj": v, "phase": p}
            for t, v, p in obj_series
        ],
    }
