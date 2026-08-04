"""Finding 19 (remaining item): the monolithic week solve is a single long
``Solve`` that would leave the progress bar frozen. ``_ProgressCallback``
advances it during the solve. These tests run a real (tiny) CP-SAT solve with
the callback attached and assert it reports progress within its band, tagged
with the right step, and throttles its DB writes.
"""
from __future__ import annotations

from ortools.sat.python import cp_model

from backend import optimization


def _run_with_callback(cb, *, n_vars=6):
    """Tiny optimisation model that yields at least one incumbent so the
    solution callback fires at least once."""
    m = cp_model.CpModel()
    xs = [m.NewIntVar(0, 100, f"x{i}") for i in range(n_vars)]
    for i in range(1, n_vars):
        m.Add(xs[i] >= xs[i - 1])
    m.Add(sum(xs) >= 37)
    m.Minimize(sum(xs))
    cp_model.CpSolver().Solve(m, cb)


def test_progress_callback_reports_within_band(monkeypatch):
    calls = []
    monkeypatch.setattr(optimization, "update_run",
                        lambda rid, **kw: calls.append((rid, kw)))

    cb = optimization._ProgressCallback(
        7, base=0.30, span=0.58, time_limit=5.0, step="phase_b")
    _run_with_callback(cb)

    assert calls, "callback never reported progress"
    for rid, kw in calls:
        assert rid == 7
        assert kw["current_step"] == "phase_b"
        # Monotone bounded fraction: never below base, never past base+span.
        assert 0.30 <= kw["progress"] <= 0.30 + 0.58


def test_progress_callback_throttles(monkeypatch):
    """With a large min_interval, only the FIRST solution emits (the rest are
    within the throttle window), so the callback never floods update_run."""
    calls = []
    monkeypatch.setattr(optimization, "update_run",
                        lambda rid, **kw: calls.append((rid, kw)))

    cb = optimization._ProgressCallback(
        1, base=0.0, span=1.0, time_limit=5.0, min_interval=1e9)
    _run_with_callback(cb, n_vars=8)

    # Even if the solver found several incumbents, the huge interval collapses
    # them to a single emitted update.
    assert len(calls) <= 1


def test_progress_callback_honours_the_callers_band(monkeypatch):
    """The band is the CALLER's, not the solve's: run_full_pipeline hands
    over one `i/n_steps` slice. Hard-coding run_phase_b's 0.30/0.58 made
    the bar overshoot the pipeline step and then jump backwards when the
    next step set its own progress."""
    calls = []
    monkeypatch.setattr(optimization, "update_run",
                        lambda rid, **kw: calls.append((rid, kw)))

    # Step 2 of 6 in a full pipeline.
    cb = optimization._ProgressCallback(
        9, base=2 / 6, span=1 / 6, time_limit=5.0, step="phase_b")
    _run_with_callback(cb)

    assert calls, "callback never reported progress"
    for _rid, kw in calls:
        assert 2 / 6 <= kw["progress"] <= 3 / 6


def test_progress_callback_stops_the_search_on_cancel(monkeypatch):
    """CP-SAT polls nothing, so a cancel during a long Solve used to wait
    out the entire time budget. The callback is the only point inside the
    solve where we get control back."""
    monkeypatch.setattr(optimization, "is_cancel_requested",
                        lambda rid: True)
    calls = []
    monkeypatch.setattr(optimization, "update_run",
                        lambda rid, **kw: calls.append((rid, kw)))

    cb = optimization._ProgressCallback(
        3, base=0.0, span=1.0, time_limit=5.0)
    _run_with_callback(cb, n_vars=8)

    # Stopped at the first incumbent: no progress reported, and the solve
    # returned rather than exhausting its budget.
    assert calls == []


def test_progress_callback_swallows_update_errors(monkeypatch):
    """Progress is best-effort: an update_run failure must never break the
    solve (the callback runs inside the solver's search)."""
    def boom(rid, **kw):
        raise RuntimeError("db down")
    monkeypatch.setattr(optimization, "update_run", boom)

    cb = optimization._ProgressCallback(
        1, base=0.0, span=1.0, time_limit=5.0)
    # Must not raise.
    _run_with_callback(cb)
