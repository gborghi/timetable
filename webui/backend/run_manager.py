"""In-process job manager. Each job runs in its own thread, captures stdout
into a ring buffer + DB, and exposes async iterators for SSE log streaming.

The engine module functions are CPU-bound (ortools / numpy) so threads
don't give true parallelism. They DO let us cancel work cooperatively and
read live output without blocking the event loop.

Reliability notes (audit round 4):
  * `_BUFFERS` / `_THREADS` used to grow without bound. Each finished
    run leaves a buffer pinned forever, and the dict was never pruned.
    We now schedule deferred eviction in a daemon "reaper" thread that
    drops buffers older than _BUFFER_TTL_S since `mark_finished`.
  * `_emit_line()` opened a fresh `SessionLocal` for every log line AND
    ran `COUNT(*)` against `run_logs` per line to compute `seq`. On
    runs that print thousands of lines this collapsed the DB. We now:
      - keep `seq` as an in-memory counter on `_RunBuffer`;
      - flush log lines in batches via a single background "log-writer"
        daemon thread per run, using `bulk_save_objects`;
      - guarantee a final flush on `mark_finished`.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import io
import json
import logging
import os
import queue
import sys
import threading
import traceback
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

from . import models
from .db import SessionLocal

log = logging.getLogger("pitantum.run_manager")


# Tunables -----------------------------------------------------------------

# Maximum interval (seconds) between log-line batch flushes to the DB.
# At higher rates we batch up to _LOG_BATCH_MAX lines per round trip.
_LOG_FLUSH_INTERVAL_S = 0.5
_LOG_BATCH_MAX = 200

# How long to keep a finished run's buffer in memory before eviction.
# 5 minutes is enough for the UI to replay the log once the user opens
# the run details page; older logs can be replayed from the DB.
_BUFFER_TTL_S = 5 * 60

# How often the reaper sweeps the buffer dict.
_REAPER_INTERVAL_S = 60

# Admission control: cap how many runs execute the CPU-bound solver
# concurrently. Each solve loads the full-school data structures into
# memory and saturates cores under the GIL; N simultaneous big-school
# solves thrash CPU and can OOM the process. Excess runs stay 'pending'
# and start as slots free up (a simple in-process queue). Default 1 --
# raise via PITANTUM_MAX_CONCURRENT_RUNS for beefier hosts.
def _max_concurrent_runs() -> int:
    try:
        return max(1, int(os.environ.get("PITANTUM_MAX_CONCURRENT_RUNS", "1")))
    except ValueError:
        return 1


_RUN_SLOTS = threading.BoundedSemaphore(_max_concurrent_runs())


@dataclass
class _RunBuffer:
    """Per-run queue + condition for streaming logs. Newcomers can replay
    the full buffer first, then stream live."""
    lines: list[str] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    cond: threading.Condition = field(init=False)
    finished: bool = False
    # Monotonic sequence counter persisted on the matching RunLog row.
    # Held in-memory (instead of COUNT(*) per line) so log writes stay
    # O(1) on the DB side, not O(N).
    next_seq: int = 0
    # Background writer thread + work queue. Started lazily on the
    # first log line of the run, joined on `mark_finished`.
    _writer: Optional[threading.Thread] = None
    _writer_q: "queue.Queue[Optional[tuple[int, str]]]" = field(
        default_factory=queue.Queue,
    )
    finished_at: Optional[float] = None

    def __post_init__(self):
        self.cond = threading.Condition(self.lock)

    def _ensure_writer(self, run_id: int) -> None:
        # Caller must hold `self.lock`.
        if self._writer is not None and self._writer.is_alive():
            return
        self._writer = threading.Thread(
            target=_log_writer_loop, args=(run_id, self), daemon=True,
        )
        self._writer.start()

    def append(self, text: str, run_id: int):
        with self.cond:
            self.lines.append(text)
            self._ensure_writer(run_id)
            seq = self.next_seq
            self.next_seq += 1
            try:
                self._writer_q.put_nowait((seq, text))
            except queue.Full:
                # Writer queue is unbounded; this is unreachable but
                # we keep the try/except for forward-compat.
                pass
            self.cond.notify_all()

    def mark_finished(self):
        with self.cond:
            if not self.finished:
                self.finished = True
                self.finished_at = time.monotonic()
                # Sentinel tells the writer thread to flush + exit.
                try:
                    self._writer_q.put_nowait(None)
                except queue.Full:
                    pass
            self.cond.notify_all()
        # Join the writer thread (outside the lock) so callers don't
        # observe a finished buffer that still has pending log writes.
        w = self._writer
        if w is not None and w.is_alive():
            w.join(timeout=10.0)

    def snapshot(self) -> tuple[list[str], bool]:
        with self.cond:
            return list(self.lines), self.finished

    def wait_for_more(self, since: int, timeout: float = 30.0) -> None:
        with self.cond:
            self.cond.wait_for(
                lambda: self.finished or len(self.lines) > since,
                timeout=timeout,
            )


def _log_writer_loop(run_id: int, buf: _RunBuffer) -> None:
    """Background thread: drain `buf._writer_q` and bulk-insert RunLog
    rows in batches. Exits on sentinel `None` after one final flush.

    A single DB session is reused across the whole run so we don't pay
    the SessionLocal() construction cost per batch. On commit error we
    rollback and keep going -- losing a log line is preferable to
    crashing the run.
    """
    pending: list[tuple[int, str]] = []

    def _flush(db) -> None:
        if not pending:
            return
        try:
            db.bulk_save_objects([
                models.RunLog(run_id=run_id, seq=seq, text=line[:4096])
                for seq, line in pending
            ])
            db.commit()
        except Exception:
            log.exception("run_manager: log batch flush failed run_id=%d", run_id)
            try:
                db.rollback()
            except Exception:
                pass
        pending.clear()

    try:
        with SessionLocal() as db:
            last_flush = time.monotonic()
            while True:
                # Block up to the flush interval for the next item, then
                # try to drain whatever else is queued without blocking.
                try:
                    item = buf._writer_q.get(timeout=_LOG_FLUSH_INTERVAL_S)
                except queue.Empty:
                    item = "_TIMEOUT"

                if item is None:
                    # Sentinel -> flush + exit.
                    _flush(db)
                    return
                if item != "_TIMEOUT":
                    pending.append(item)
                # Best-effort drain so a burst doesn't trickle one at a time.
                while len(pending) < _LOG_BATCH_MAX:
                    try:
                        nxt = buf._writer_q.get_nowait()
                    except queue.Empty:
                        break
                    if nxt is None:
                        _flush(db)
                        return
                    pending.append(nxt)
                now = time.monotonic()
                if (
                    len(pending) >= _LOG_BATCH_MAX
                    or now - last_flush >= _LOG_FLUSH_INTERVAL_S
                ):
                    _flush(db)
                    last_flush = now
    except Exception:
        log.exception("run_manager: log-writer thread crashed run_id=%d", run_id)


# Top-level singleton state ---------------------------------------------

_BUFFERS: dict[int, _RunBuffer] = {}
_BUFFERS_LOCK = threading.Lock()
_THREADS: dict[int, threading.Thread] = {}

# Cooperative cancellation: the user clicks the "kill" button in the
# /runs list, which calls request_cancel(run_id). Long-running solver
# code can check `is_cancel_requested(run_id)` periodically and bail
# out cleanly. The DB row is also flipped to status='cancelled' so the
# UI stops showing it as active even if the thread takes its time.
_CANCELLED_RUNS: set[int] = set()
_CANCELLED_LOCK = threading.Lock()


def _start_reaper_once() -> None:
    """Start the background buffer reaper exactly once per process."""
    with _BUFFERS_LOCK:
        if getattr(_start_reaper_once, "_started", False):
            return
        _start_reaper_once._started = True  # type: ignore[attr-defined]
        threading.Thread(
            target=_reaper_loop, name="run_manager.reaper", daemon=True,
        ).start()


def _reaper_loop() -> None:
    """Sweep `_BUFFERS` / `_THREADS` and drop entries whose run has been
    finished for more than `_BUFFER_TTL_S`. Prevents the slow leak that
    used to grow the dicts every time a run completed.
    """
    while True:
        try:
            time.sleep(_REAPER_INTERVAL_S)
            cutoff = time.monotonic() - _BUFFER_TTL_S
            to_drop: list[int] = []
            with _BUFFERS_LOCK:
                for rid, buf in _BUFFERS.items():
                    fin_at = buf.finished_at
                    if buf.finished and fin_at is not None and fin_at < cutoff:
                        to_drop.append(rid)
                for rid in to_drop:
                    _BUFFERS.pop(rid, None)
                    _THREADS.pop(rid, None)
            with _CANCELLED_LOCK:
                for rid in to_drop:
                    _CANCELLED_RUNS.discard(rid)
            if to_drop:
                log.info("run_manager: reaped %d finished run buffers",
                         len(to_drop))
        except Exception:
            log.exception("run_manager: reaper iteration failed")


def request_cancel(run_id: int) -> bool:
    """Mark a run as cancel-requested. Idempotent. Returns True iff
    the run was running/pending (i.e., the cancel had any effect)."""
    with SessionLocal() as db:
        r = db.get(models.Run, run_id)
        if r is None:
            return False
        if r.status not in ("running", "pending"):
            return False
        r.status = "cancelled"
        r.error = (r.error or "") + "\n[cancel] richiesto dall'utente"
        r.finished_at = dt.datetime.utcnow()
        db.commit()
    with _CANCELLED_LOCK:
        _CANCELLED_RUNS.add(run_id)
    # Mark the SSE buffer as finished so the log stream closes.
    try:
        buf = get_buffer(run_id)
        _emit_line(run_id, "[cancel] richiesto dall'utente")
        buf.mark_finished()
    except Exception:
        log.exception("request_cancel: failed to mark buffer finished "
                      "run_id=%d", run_id)
    return True


def is_cancel_requested(run_id: int) -> bool:
    """Check inside a long-running target() to bail early."""
    with _CANCELLED_LOCK:
        return run_id in _CANCELLED_RUNS


class RunCancelled(Exception):
    """Raised by `raise_if_cancelled` to unwind a running target() when
    the user has requested cancellation. `_runner` catches it and leaves
    the run in the 'cancelled' state instead of overwriting it to
    'done'/'failed'."""


def raise_if_cancelled(run_id: int) -> None:
    """Cooperative cancellation check. Call at safe boundaries inside a
    long-running target() (between pipeline steps, per-day iterations,
    metaheuristic rounds). Raises `RunCancelled` if a cancel was
    requested so the orchestration unwinds promptly instead of running
    to the full time budget."""
    if is_cancel_requested(run_id):
        raise RunCancelled(run_id)


def get_buffer(run_id: int) -> _RunBuffer:
    with _BUFFERS_LOCK:
        if run_id not in _BUFFERS:
            _BUFFERS[run_id] = _RunBuffer()
        return _BUFFERS[run_id]


# stdout/stderr capture --------------------------------------------------


class _TeeWriter(io.TextIOBase):
    """Writes to the underlying stream *and* the run buffer."""

    def __init__(self, run_id: int, downstream):
        self.run_id = run_id
        self.downstream = downstream
        self.buf = ""

    def write(self, s: str):
        try:
            if self.downstream is not None:
                self.downstream.write(s)
        except Exception:
            pass
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            line = line.rstrip("\r")
            if line:
                _emit_line(self.run_id, line)
        return len(s)

    def flush(self):
        try:
            if self.downstream is not None:
                self.downstream.flush()
        except Exception:
            pass


def _emit_line(run_id: int, line: str):
    """Enqueue one log line for SSE delivery + batched DB persistence.

    Constant-time: no SessionLocal()/COUNT(*) per call (the sequence is
    tracked on the buffer; persistence is done in batches by a single
    background writer thread per run).
    """
    buf = get_buffer(run_id)
    buf.append(line, run_id)


@contextmanager
def capture_stdout(run_id: int):
    old_out = sys.stdout
    old_err = sys.stderr
    sys.stdout = _TeeWriter(run_id, old_out)
    sys.stderr = _TeeWriter(run_id, old_err)
    try:
        yield
    finally:
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass
        sys.stdout = old_out
        sys.stderr = old_err


# Run lifecycle ---------------------------------------------------------


def reconcile_orphaned_runs() -> int:
    """Mark runs left non-terminal by a crash/OOM/restart as failed.

    Run state lives in this process's memory (buffers, threads,
    semaphore). When the process dies mid-solve, the DB row stays
    'running'/'pending' forever: the worker thread is gone, no buffer
    will ever be `finished`, so its SSE stream loops indefinitely and
    delete-run refuses to remove it (it looks active). Call this once at
    startup, before serving traffic, to sweep those ghosts into a
    terminal 'failed' state. Returns the number of rows reconciled.
    """
    n = 0
    try:
        with SessionLocal() as db:
            orphans = (
                db.query(models.Run)
                .filter(models.Run.status.in_(("running", "pending")))
                .all()
            )
            now = dt.datetime.utcnow()
            for r in orphans:
                r.status = "failed"
                r.error = (
                    (r.error or "")
                    + "\n[reconcile] interrotto da riavvio/crash del backend"
                )
                r.finished_at = now
                n += 1
            if n:
                db.commit()
    except Exception:
        log.exception("run_manager: orphan reconciliation failed")
        return 0
    if n:
        log.warning(
            "run_manager: reconciled %d orphaned run(s) to 'failed' at startup",
            n,
        )
    return n


def active_run_count() -> int:
    """Number of runs currently running or queued. Used to refuse
    destructive whole-DB operations (clear / import-db / restore) while
    a solver is mid-flight -- overwriting the DB file or truncating
    tables under a live run corrupts both."""
    try:
        with SessionLocal() as db:
            return (
                db.query(models.Run)
                .filter(models.Run.status.in_(("running", "pending")))
                .count()
            )
    except Exception:
        log.exception("run_manager: active_run_count failed")
        return 0


def create_run(kind: str, name: str, profile: Optional[str],
               params: dict[str, Any]) -> int:
    with SessionLocal() as db:
        r = models.Run(
            kind=kind,
            name=name,
            profile=profile,
            params_json=json.dumps(params),
            status="pending",
            progress=0.0,
        )
        db.add(r)
        db.commit()
        db.refresh(r)
        return r.id


def update_run(run_id: int, **kw: Any) -> None:
    with SessionLocal() as db:
        r = db.get(models.Run, run_id)
        if r is None:
            return
        for k, v in kw.items():
            if k == "metrics":
                r.metrics_json = json.dumps(v)
            elif k == "params":
                r.params_json = json.dumps(v)
            else:
                setattr(r, k, v)
        db.commit()


def start_thread(run_id: int, target: Callable[[int], None]) -> None:
    _start_reaper_once()
    t = threading.Thread(target=_runner, args=(run_id, target), daemon=True)
    with _BUFFERS_LOCK:
        _THREADS[run_id] = t
    t.start()


def _runner(run_id: int, target: Callable[[int], None]) -> None:
    buf = get_buffer(run_id)
    # Admission control: wait for a free solver slot. The run stays
    # 'pending' meanwhile (its row was created 'pending'), so the UI
    # shows it queued. Poll with a timeout so a run cancelled *while
    # queued* exits without ever consuming a slot.
    acquired = False
    while not acquired:
        if is_cancel_requested(run_id):
            update_run(
                run_id, status="cancelled",
                finished_at=dt.datetime.utcnow(),
            )
            _emit_line(run_id, "[run] cancelled while queued")
            buf.mark_finished()
            return
        acquired = _RUN_SLOTS.acquire(timeout=0.5)
    update_run(
        run_id, status="running",
        started_at=dt.datetime.utcnow(),
    )
    try:
        with capture_stdout(run_id):
            target(run_id)
        # A cancel may have been requested *during* target() (e.g. the
        # solver ran to its budget after the user clicked cancel, or a
        # cooperative check hadn't fired yet). Never flip a cancelled
        # run back to 'done' -- that made the Run table lie about
        # outcomes. request_cancel() already set status='cancelled'.
        if is_cancel_requested(run_id):
            update_run(
                run_id, progress=1.0,
                finished_at=dt.datetime.utcnow(),
            )
            _emit_line(run_id, "[run] cancelled")
        else:
            update_run(
                run_id, status="done", progress=1.0,
                finished_at=dt.datetime.utcnow(),
            )
            _emit_line(run_id, "[run] done")
    except RunCancelled:
        # Cooperative cancellation unwound the target. The DB row is
        # already 'cancelled' (set by request_cancel); just close out.
        update_run(
            run_id, status="cancelled",
            finished_at=dt.datetime.utcnow(),
        )
        _emit_line(run_id, "[run] cancelled")
    except Exception as exc:  # pragma: no cover
        tb = traceback.format_exc()
        # Guard the same lie on the failure path: if the user cancelled
        # and the target happened to raise while unwinding, keep it
        # 'cancelled' rather than masking it as a crash.
        if is_cancel_requested(run_id):
            update_run(
                run_id, status="cancelled",
                finished_at=dt.datetime.utcnow(),
            )
            _emit_line(run_id, "[run] cancelled")
        else:
            update_run(
                run_id, status="failed", error=tb,
                finished_at=dt.datetime.utcnow(),
            )
            _emit_line(run_id, f"[run] FAILED: {exc}")
            _emit_line(run_id, tb)
    finally:
        # Order matters: invalidate the server-side TTL cache FIRST,
        # then close the SSE stream. The client's `onEnd` callback
        # fires the moment the SSE closes and immediately re-fetches
        # /api/dataset/state and the graph endpoints. If we bumped
        # AFTER mark_finished() the client could win the race and read
        # the still-cached pre-run snapshot.
        try:
            from .utils.ttl_cache import bump_mutation
            bump_mutation()
        except Exception:
            log.exception(
                "run_manager: bump_mutation failed run_id=%d", run_id,
            )
        # Release the admission-control slot so a queued run can start.
        if acquired:
            try:
                _RUN_SLOTS.release()
            except ValueError:
                log.exception(
                    "run_manager: slot release imbalance run_id=%d", run_id,
                )
        buf.mark_finished()


# SSE streaming ---------------------------------------------------------


async def stream_events(run_id: int, replay: bool = True) -> Iterable[str]:
    """Async generator yielding SSE-formatted events for a run."""
    buf = get_buffer(run_id)
    cursor = 0
    if replay:
        lines, _ = buf.snapshot()
        for line in lines:
            yield _format_event("log", line)
            cursor += 1
    while True:
        # Run a short blocking wait in a thread so we don't block the loop
        await asyncio.get_event_loop().run_in_executor(
            None, buf.wait_for_more, cursor, 5.0
        )
        lines, finished = buf.snapshot()
        for line in lines[cursor:]:
            yield _format_event("log", line)
        cursor = len(lines)
        # Periodic status push so the UI can update progress
        with SessionLocal() as db:
            r = db.get(models.Run, run_id)
            if r is not None:
                yield _format_event("status", json.dumps({
                    "status": r.status,
                    "progress": r.progress,
                    "obj_value": r.obj_value,
                    "metrics": json.loads(r.metrics_json or "{}"),
                    "solution_id": r.solution_id,
                }))
                if r.status in ("done", "failed", "cancelled") and finished:
                    yield _format_event("end", r.status)
                    return
        if finished:
            # The buffer is finished but the row may still show 'running'
            # for a few ms because the worker thread's update_run commit
            # hasn't propagated to this connection yet. Wait + re-read
            # a few times before declaring 'done' as a fallback.
            for _ in range(10):
                await asyncio.sleep(0.1)
                with SessionLocal() as db2:
                    r2 = db2.get(models.Run, run_id)
                    if r2 is not None and r2.status in (
                            "done", "failed", "cancelled"):
                        yield _format_event("end", r2.status)
                        return
            yield _format_event("end", "done")
            return


def _format_event(event: str, data: str) -> str:
    safe = data.replace("\r", "")
    out = f"event: {event}\n"
    for line in safe.split("\n"):
        out += f"data: {line}\n"
    out += "\n"
    return out
