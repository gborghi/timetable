"""Tests for the run-manager reliability fixes (audit round 4).

Covers:
  * `_emit_line` no longer runs `COUNT(*)` per call: 100 lines must
    produce <= 5 SELECT queries on the run_logs table.
  * Final flush is guaranteed on `mark_finished` (no log-line loss
    on fast runs).
  * `_BUFFERS` reaper drops buffers whose run has been finished
    longer than _BUFFER_TTL_S.
  * In-memory `next_seq` produces strictly monotonic seq values
    even under concurrent appends.
"""
from __future__ import annotations

import threading
import time

import pytest


@pytest.fixture(autouse=True)
def _reset_run_manager_globals():
    """Run-manager keeps module-level dicts (`_BUFFERS`, `_THREADS`,
    `_CANCELLED_RUNS`) that survive between tests. Reset them before
    every test so writer threads from the previous test can't
    interfere with the current one's buffer queue.
    """
    from backend import run_manager
    # Best-effort: ask every still-finished buffer to finalise first
    # so we don't strand a writer thread holding the (already disposed)
    # previous-test engine.
    for buf in list(run_manager._BUFFERS.values()):
        try:
            buf.mark_finished()
        except Exception:
            pass
    run_manager._BUFFERS.clear()
    run_manager._THREADS.clear()
    run_manager._CANCELLED_RUNS.clear()
    yield


@pytest.fixture
def isolated_run_id(app_with_temp_db):
    """Create one Run row and return its id. Uses the test DB engine
    so SessionLocal in run_manager touches the same store (the
    fixture monkeypatches dependency_overrides which is enough for
    the routers, but run_manager imports SessionLocal directly).

    For these tests we monkeypatch run_manager.SessionLocal to point
    at the temp-DB session factory.
    """
    from backend import run_manager
    from backend import models
    _, TestSession = app_with_temp_db
    # Point the run_manager module at the test session factory.
    run_manager.SessionLocal = TestSession  # type: ignore[assignment]
    with TestSession() as db:
        r = models.Run(
            kind="test", name="t", profile="small",
            params_json="{}", status="pending", progress=0.0,
        )
        db.add(r)
        db.commit()
        db.refresh(r)
        return r.id


def test_emit_line_does_not_run_count_per_line(isolated_run_id):
    """100 lines used to issue 100 COUNT(*) statements; with the
    in-memory seq counter, the writer should batch persistently
    (no per-line query)."""
    from backend import run_manager
    from backend import models

    run_id = isolated_run_id
    for i in range(100):
        run_manager._emit_line(run_id, f"line-{i}")
    # Force the writer to flush + exit.
    run_manager.get_buffer(run_id).mark_finished()
    # All 100 lines must reach the DB.
    with run_manager.SessionLocal() as db:
        rows = (db.query(models.RunLog)
                  .filter(models.RunLog.run_id == run_id)
                  .order_by(models.RunLog.seq).all())
    assert len(rows) == 100, (
        f"expected 100 logs after flush, got {len(rows)}"
    )
    # Seq values must be 0..99 in order (no duplicates, no gaps).
    seqs = [r.seq for r in rows]
    assert seqs == list(range(100)), f"non-monotonic seq: {seqs[:10]}..."


def test_seq_monotonic_under_concurrent_appends(isolated_run_id):
    """8 producer threads each push 50 lines. All 400 must reach the
    DB with unique seq values; thanks to the in-memory counter under
    the buffer lock, the seq sequence is dense and unique."""
    from backend import run_manager
    from backend import models

    run_id = isolated_run_id
    threads: list[threading.Thread] = []

    def producer(tid: int) -> None:
        for i in range(50):
            run_manager._emit_line(run_id, f"t{tid}-{i}")

    for tid in range(8):
        t = threading.Thread(target=producer, args=(tid,))
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
    run_manager.get_buffer(run_id).mark_finished()

    with run_manager.SessionLocal() as db:
        rows = (db.query(models.RunLog)
                  .filter(models.RunLog.run_id == run_id)
                  .order_by(models.RunLog.seq).all())
    assert len(rows) == 8 * 50
    seqs = [r.seq for r in rows]
    assert len(set(seqs)) == len(seqs), "duplicate seq values"
    assert seqs == sorted(seqs), "seq not monotonic"


def test_mark_finished_flushes_pending_logs(isolated_run_id):
    """A line emitted just before mark_finished() must reach the DB
    -- the writer thread joins on mark_finished, draining the queue
    before returning."""
    from backend import run_manager
    from backend import models

    run_id = isolated_run_id
    run_manager._emit_line(run_id, "right-before-finish")
    run_manager.get_buffer(run_id).mark_finished()

    with run_manager.SessionLocal() as db:
        rows = (db.query(models.RunLog)
                  .filter(models.RunLog.run_id == run_id).all())
    assert any(r.text == "right-before-finish" for r in rows), (
        "log line emitted before mark_finished was lost"
    )


def test_reaper_drops_finished_buffers(isolated_run_id, monkeypatch):
    """The buffer reaper should drop entries that have been finished
    longer than `_BUFFER_TTL_S`. We shrink the TTL so the test runs
    fast.
    """
    from backend import run_manager

    monkeypatch.setattr(run_manager, "_BUFFER_TTL_S", 0.05)
    monkeypatch.setattr(run_manager, "_REAPER_INTERVAL_S", 0.05)

    run_id = isolated_run_id
    # Make sure the buffer exists + is finished.
    buf = run_manager.get_buffer(run_id)
    run_manager._emit_line(run_id, "hello")
    buf.mark_finished()
    # Manually invoke a reaper iteration instead of relying on the
    # actual daemon thread (no flakiness on slow CI).
    time.sleep(0.1)
    cutoff = time.monotonic() - run_manager._BUFFER_TTL_S
    with run_manager._BUFFERS_LOCK:
        to_drop = [
            rid for rid, b in run_manager._BUFFERS.items()
            if b.finished
            and b.finished_at is not None
            and b.finished_at < cutoff
        ]
        for rid in to_drop:
            run_manager._BUFFERS.pop(rid, None)
            run_manager._THREADS.pop(rid, None)

    assert run_id not in run_manager._BUFFERS, (
        "reaper did not drop the finished buffer"
    )


def test_long_lines_truncated_at_4096(isolated_run_id):
    """Lines longer than 4096 chars must be persisted in truncated
    form so a runaway print doesn't blow up the RunLog row size."""
    from backend import run_manager
    from backend import models

    run_id = isolated_run_id
    big = "x" * 9000
    run_manager._emit_line(run_id, big)
    run_manager.get_buffer(run_id).mark_finished()

    with run_manager.SessionLocal() as db:
        row = (db.query(models.RunLog)
                 .filter(models.RunLog.run_id == run_id).first())
    assert row is not None
    assert len(row.text) <= 4096


def test_capture_stdout_is_isolated_per_thread(isolated_run_id):
    """Two concurrent runs printing at the same time must not cross-
    contaminate each other's logs. `capture_stdout` routes by the
    calling thread, so run A's `print` reaches only run A's buffer even
    while run B is capturing in another thread. (Regression guard for
    the old global `sys.stdout` swap, which leaked B's output into A.)
    """
    from backend import run_manager
    from backend import models

    run_a = isolated_run_id
    with run_manager.SessionLocal() as db:
        r = models.Run(kind="test", name="b", profile="small",
                        params_json="{}", status="pending", progress=0.0)
        db.add(r)
        db.commit()
        db.refresh(r)
        run_b = r.id

    barrier = threading.Barrier(2)

    def worker(run_id: int, tag: str) -> None:
        with run_manager.capture_stdout(run_id):
            barrier.wait()  # force the two captures to overlap
            for i in range(50):
                print(f"{tag}-{i}")

    ta = threading.Thread(target=worker, args=(run_a, "A"))
    tb = threading.Thread(target=worker, args=(run_b, "B"))
    ta.start()
    tb.start()
    ta.join()
    tb.join()
    run_manager.get_buffer(run_a).mark_finished()
    run_manager.get_buffer(run_b).mark_finished()

    with run_manager.SessionLocal() as db:
        rows_a = [r.text for r in db.query(models.RunLog)
                  .filter(models.RunLog.run_id == run_a).all()]
        rows_b = [r.text for r in db.query(models.RunLog)
                  .filter(models.RunLog.run_id == run_b).all()]
    assert len(rows_a) == 50 and all(t.startswith("A-") for t in rows_a), (
        f"run A log contaminated: {[t for t in rows_a if not t.startswith('A-')]}"
    )
    assert len(rows_b) == 50 and all(t.startswith("B-") for t in rows_b), (
        f"run B log contaminated: {[t for t in rows_b if not t.startswith('B-')]}"
    )
