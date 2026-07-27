"""Coverage gate: refuse to report a partial timetable as success (P0).

Decomposition/monolithic Phase B can leave lessons unplaced when a day
or cluster doesn't solve in time. Previously the partial solution was
saved and the run marked 'done' -- a big school's most dangerous failure
mode (looks successful, silently incomplete). The gate computes
placed/required coverage from the Phase-A day-counts and, when strict
(default), fails the run instead.

The unit tests exercise the pure helpers (no solver -> fast suite). The
integration test runs the real pipeline and asserts a solvable instance
passes the gate at 100% coverage (slow).
"""
from __future__ import annotations

import pytest

from backend import optimization as opt


# --- pure helpers (fast) --------------------------------------------------

_DC = {("p1", "1A", "Mate", 1): 3, ("p1", "1A", "Mate", 2): 2}  # required 5
_FULL = {
    ("p1", "1A", "Mate", 1, 8): 1, ("p1", "1A", "Mate", 1, 9): 1,
    ("p1", "1A", "Mate", 1, 10): 1, ("p1", "1A", "Mate", 2, 8): 1,
    ("p1", "1A", "Mate", 2, 9): 1,
}
_PARTIAL = {k: 1 for k in list(_FULL)[:3]}  # placed 3 / 5 = 60%


def test_coverage_ratio():
    assert opt._coverage_ratio(_FULL, _DC) == 1.0
    assert opt._coverage_ratio(_PARTIAL, _DC) == pytest.approx(0.6)
    assert opt._coverage_ratio(_FULL, None) is None
    assert opt._coverage_ratio(_FULL, {}) is None


def test_gate_passes_at_full_coverage(monkeypatch):
    monkeypatch.delenv("PITANTUM_COVERAGE_STRICT", raising=False)
    m: dict = {}
    opt._gate_coverage(_FULL, _DC, stage="t", metrics=m)  # must not raise
    assert m["coverage"] == 1.0


def test_gate_raises_on_partial_when_strict(monkeypatch):
    monkeypatch.delenv("PITANTUM_COVERAGE_STRICT", raising=False)
    m: dict = {}
    with pytest.raises(RuntimeError):
        opt._gate_coverage(_PARTIAL, _DC, stage="t", metrics=m)
    assert m["coverage"] == pytest.approx(0.6)  # recorded even on failure


def test_gate_lenient_keeps_partial(monkeypatch):
    monkeypatch.setenv("PITANTUM_COVERAGE_STRICT", "0")
    m: dict = {}
    opt._gate_coverage(_PARTIAL, _DC, stage="t", metrics=m)  # no raise
    assert m["coverage"] == pytest.approx(0.6)


# --- end-to-end (slow) ----------------------------------------------------

@pytest.mark.slow
def test_run_phase_b_reaches_full_coverage():
    """A solvable small school runs phase_a -> phase_b through the real
    orchestration entry point and passes the gate: coverage is recorded
    in the run metrics and the run ends 'done' (not spuriously failed)."""
    import json
    import time
    from backend import models, optimization
    from backend.tests.scenarios.builder import (
        _import_base_school, _run_phase_a_in_proc,
    )

    # Populate the (test) DB and produce Phase-A assignments in-proc.
    with optimization.SessionLocal() as db:
        _import_base_school(db, "small", margin=0.2)
        n_assign = _run_phase_a_in_proc(db, time_limit=20)
    assert n_assign > 0

    rid = optimization.run_phase_b(
        k=4, time_a=15, time_bridges=15, time_cluster=15,
        time_ricucitura=20, time_mono=40, workers=4, log=False,
        use_decomposition=False,
    )
    status, metrics_json = None, "{}"
    for _ in range(300):
        with optimization.SessionLocal() as s:
            r = s.get(models.Run, rid)
            if r and r.status in ("done", "failed", "cancelled"):
                status, metrics_json = r.status, r.metrics_json
                break
        time.sleep(1)
    else:
        pytest.fail("run did not finish in time")

    metrics = json.loads(metrics_json or "{}")
    assert status == "done", f"run failed: {metrics}"
    assert metrics.get("coverage", 0) >= 0.999, metrics
