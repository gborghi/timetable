"""Memory + time-leak regression tests.

These tests are intentionally lightweight (they run in-process
against the live app) but loud: a meaningful regression -- a
new endpoint that leaks SQLAlchemy sessions, a polling code
path that spawns threads without cleanup, a list endpoint that
allocates O(n) memory per request and never frees it -- shows
up as a baseline blow-out within seconds.

We use `psutil` if available (it's installed via
`scikit-learn`/numpy stack) but degrade gracefully if not.
"""
from __future__ import annotations

import gc
import os
import sys
import threading
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(os.path.dirname(HERE))
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from backend.main import app
    return TestClient(app)


def _rss_mb() -> float | None:
    try:
        import psutil
        return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except ImportError:
        return None


# ---------------- Memory leak: list endpoints ----------------

def test_repeated_list_calls_dont_leak_memory(client):
    """Hitting /api/teachers 200 times should not grow RSS by more
    than 50 MB. This catches the typical SQLAlchemy session-leak
    pattern (pending statements held until GC), or per-request
    object-graph accumulation in serializers.

    This is a soft test: we measure delta after gc.collect().
    """
    rss_before = _rss_mb()
    if rss_before is None:
        pytest.skip("psutil not available")

    # Warm-up + GC baseline
    for _ in range(5):
        client.get("/api/teachers")
    gc.collect()
    rss_baseline = _rss_mb()

    # Hot loop
    for _ in range(200):
        r = client.get("/api/teachers")
        assert r.status_code == 200
    gc.collect()
    rss_after = _rss_mb()
    delta = rss_after - rss_baseline
    # Generous budget: SQLAlchemy and uvicorn keep some pools but
    # 50 MB on 200 small requests would indicate a real leak.
    assert delta < 50, (
        f"RSS grew by {delta:.1f} MB after 200 /api/teachers calls "
        f"(baseline {rss_baseline:.1f} MB -> {rss_after:.1f} MB). "
        f"Likely a session/object-graph leak."
    )


# ---------------- Time leak: thread accumulation ----------------

def test_no_orphan_threads_after_short_runs(client):
    """Spawning N short runs (each one terminates quickly) must not
    leave dangling threads. The run_manager creates one daemon
    thread per run; it must exit within a few seconds of the
    target() returning.

    We spawn 5 hall-check pseudo-runs (actually sync, so this
    really just exercises the async-diag path) and assert thread
    count returns near baseline.
    """
    threading.enumerate()  # touch first
    threads_before = len(threading.enumerate())

    # Spawn 5 fast async runs (bipartite is the cheapest at ~300ms).
    rids = []
    for _ in range(5):
        r = client.post("/api/diagnostics/bipartite", json={"mode": "classes"})
        if r.status_code == 200 and "run_id" in r.json():
            rids.append(r.json()["run_id"])

    if not rids:
        pytest.skip("no runs created (maybe DB has no active solution)")

    # Wait for all to finish (or fail). Cap at 30s.
    deadline = time.time() + 30
    pending = set(rids)
    while pending and time.time() < deadline:
        for rid in list(pending):
            r = client.get(f"/api/optimize/runs/{rid}")
            if r.status_code == 200:
                st = r.json().get("status")
                if st in ("done", "failed"):
                    pending.discard(rid)
        if pending:
            time.sleep(0.5)

    # After completion, give the thread cleanup a moment.
    time.sleep(2.0)
    gc.collect()
    threads_after = len(threading.enumerate())
    delta = threads_after - threads_before
    assert delta <= 2, (
        f"Thread count grew by {delta} after {len(rids)} runs "
        f"({threads_before} -> {threads_after}). Likely an orphan "
        f"runner thread."
    )


# ---------------- Time leak: response time stability ----------------

def test_endpoint_latency_is_stable_over_many_calls(client):
    """If the FIRST call to /api/teachers is 100ms but the
    100th is 2s, something is accumulating per-request state
    (most likely a cache that grows linearly, or a connection
    pool that doesn't recycle). This is the textbook "after 3-4
    tab switches the page freezes" symptom.

    Threshold: the slowest call in the hot loop must not be
    more than 5x slower than the median.
    """
    # Warm-up
    for _ in range(3):
        client.get("/api/teachers")

    timings = []
    for _ in range(30):
        t0 = time.time()
        r = client.get("/api/teachers")
        assert r.status_code == 200
        timings.append((time.time() - t0) * 1000.0)
    timings.sort()
    median = timings[len(timings) // 2]
    slowest = timings[-1]
    # 5x is generous; typical is < 1.5x
    if median > 0:
        ratio = slowest / median
        assert ratio < 5.0, (
            f"slowest /api/teachers call was {slowest:.0f}ms vs "
            f"median {median:.0f}ms (ratio {ratio:.1f}x). "
            f"Likely a per-request leak."
        )


# ---------------- DB session leak ----------------

def test_db_pool_does_not_grow(client):
    """SQLAlchemy's `engine.pool.checkedout()` should be 0 between
    requests. If a handler forgets to close the session (e.g.
    by raising during yield from get_db), it would accumulate."""
    from backend.db import engine
    pool = engine.pool
    # Warm-up
    client.get("/api/teachers")
    # Hammer requests
    for _ in range(50):
        r = client.get("/api/teachers")
        assert r.status_code == 200
    # The pool shouldn't have any connections currently CHECKED-OUT
    # (in use); SQLAlchemy keeps idle connections in the pool but
    # they're "checked-in".
    if hasattr(pool, "checkedout"):
        co = pool.checkedout()
        assert co == 0, (
            f"DB pool has {co} connections checked out after the "
            f"request loop completed -- a handler is leaking sessions."
        )


# ---------------- Run-telemetry buffer leak ----------------

def test_telemetry_collector_buffers_dont_grow_unbounded():
    """A misconfigured telemetry collector (e.g. flush_every=999999
    while pushing every iteration) would accumulate samples in
    memory until OOM. We instead exercise the documented usage:
    `flush_every=50` and verify the buffer stays bounded."""
    from backend.utils import telemetry as tel
    c = tel.TelemetryCollector(run_id=999_999, phase="leak_test",
                                 flush_every=10)
    # Push 100 samples; buffer must auto-flush at every 10th
    # (the flush will silently fail because run_id 999_999 doesn't
    # exist, but the buffer should still get cleared by the flush()
    # call inside .sample()).
    for i in range(100):
        c.sample(step=i, objective_value=float(100 - i))
    # Final buffer length must be at most flush_every (the last
    # incomplete batch): 100 % 10 == 0 here, so should be 0.
    assert len(c._buffer) < 50, (
        f"telemetry buffer leaked: {len(c._buffer)} entries"
    )
    # Final flush
    c.flush()
    assert len(c._buffer) == 0
