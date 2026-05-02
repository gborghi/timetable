"""In-process job manager. Each job runs in its own thread, captures stdout
into a ring buffer + DB, and exposes async iterators for SSE log streaming.

The engine module functions are CPU-bound (ortools / numpy) so threads
don't give true parallelism. They DO let us cancel work cooperatively and
read live output without blocking the event loop."""
from __future__ import annotations

import asyncio
import datetime as dt
import io
import json
import sys
import threading
import time
import traceback
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

from . import models
from .db import SessionLocal


@dataclass
class _RunBuffer:
    """Per-run queue + condition for streaming logs. Newcomers can replay
    the full buffer first, then stream live."""
    lines: list[str] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    cond: threading.Condition = field(init=False)
    finished: bool = False

    def __post_init__(self):
        self.cond = threading.Condition(self.lock)

    def append(self, text: str):
        with self.cond:
            self.lines.append(text)
            self.cond.notify_all()

    def mark_finished(self):
        with self.cond:
            self.finished = True
            self.cond.notify_all()

    def snapshot(self) -> tuple[list[str], bool]:
        with self.cond:
            return list(self.lines), self.finished

    def wait_for_more(self, since: int, timeout: float = 30.0) -> None:
        with self.cond:
            self.cond.wait_for(
                lambda: self.finished or len(self.lines) > since,
                timeout=timeout,
            )


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
        pass
    return True


def is_cancel_requested(run_id: int) -> bool:
    """Check inside a long-running target() to bail early."""
    with _CANCELLED_LOCK:
        return run_id in _CANCELLED_RUNS


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
    buf = get_buffer(run_id)
    buf.append(line)
    # Persist asynchronously: open a short-lived session.
    try:
        with SessionLocal() as db:
            seq = db.query(models.RunLog).filter(
                models.RunLog.run_id == run_id
            ).count()
            db.add(models.RunLog(run_id=run_id, seq=seq, text=line[:4096]))
            db.commit()
    except Exception:
        pass


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
    t = threading.Thread(target=_runner, args=(run_id, target), daemon=True)
    _THREADS[run_id] = t
    t.start()


def _runner(run_id: int, target: Callable[[int], None]) -> None:
    buf = get_buffer(run_id)
    update_run(
        run_id, status="running",
        started_at=dt.datetime.utcnow(),
    )
    try:
        with capture_stdout(run_id):
            target(run_id)
        update_run(
            run_id, status="done", progress=1.0,
            finished_at=dt.datetime.utcnow(),
        )
        _emit_line(run_id, "[run] done")
    except Exception as exc:  # pragma: no cover
        tb = traceback.format_exc()
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
            pass
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
                if r.status in ("done", "failed") and finished:
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
                    if r2 is not None and r2.status in ("done", "failed"):
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
