"""Atom 1 — native lock constraints in temporal decomposition.

Tests that `engine/decomposition_temporal.py:run_temporal_pipeline`
correctly propagates locked_day_count to the master and
locked_by_day to each per-day solver. We exercise the function
directly (not the FastAPI run pipeline) using a small in-memory
school.
"""
from __future__ import annotations

import os
import pickle
import sys
import tempfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(HERE)
WEBUI_DIR = os.path.dirname(BACKEND_DIR)
REPO_ROOT = os.path.dirname(WEBUI_DIR)
ENGINE_DIR = os.path.join(REPO_ROOT, "engine")
for p in (WEBUI_DIR, ENGINE_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


def _make_profs():
    """Same shape as test_native_locks._make_profs but with a more
    realistic free-day distribution so the solver can satisfy all
    classes in 2 weekdays each (4+6 or 5+5 hours per day)."""
    return {
        "ProfA": {
            "classi": {"1A": {"Mat": {"ore": 4}},
                        "1B": {"Mat": {"ore": 4}}},
            "glibero": [6, 5, 4],
        },
        "ProfB": {
            "classi": {"1A": {"Ita": {"ore": 4}},
                        "1B": {"Ita": {"ore": 4}}},
            "glibero": [6, 5, 4],
        },
        "ProfC": {
            "classi": {"1A": {"Sto": {"ore": 2}},
                        "1B": {"Sto": {"ore": 2}}},
            "glibero": [6, 5, 4],
        },
    }


def _run_temporal(profs, *, locked_dc=None, locked_by_day=None):
    import decomposition_temporal as dec_t  # type: ignore
    with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as tmp:
        pickle.dump(profs, tmp)
        path = tmp.name
    try:
        return dec_t.run_temporal_pipeline(
            path,
            parallel=False,        # sequential: avoids ProcessPoolExecutor
            n_workers=1,
            time_a=2,
            time_day=2,
            cpsat_workers_per_day=2,
            enforce_no_holes=True,
            log_progress=False,
            out_path=None,
            dc_out_path=None,
            locked_day_count=locked_dc,
            locked_by_day=locked_by_day,
        )
    finally:
        os.unlink(path)


def test_temporal_lock_respected_by_day_solver():
    profs = _make_profs()
    locked_dc = {("ProfA", "1A", "Mat", 2): 2}
    locked_by_day = {2: [("ProfA", "1A", "Mat", 8),
                          ("ProfA", "1A", "Mat", 9)]}
    res = _run_temporal(profs, locked_dc=locked_dc,
                         locked_by_day=locked_by_day)
    sol = res["full_solution"]
    assert sol[("ProfA", "1A", "Mat", 2, 8)] == 1
    assert sol[("ProfA", "1A", "Mat", 2, 9)] == 1
    # Total Mat hours for ProfA-1A still 4 over the week.
    n = sum(v for (p, c, s, _, _), v in sol.items()
            if p == "ProfA" and c == "1A" and s == "Mat")
    assert n == 4


def test_temporal_lock_violating_max_per_day_fails_clearly():
    """Lock 3 hours of the same cattedra in a single day: that
    exceeds MAX_PER_DAY_TRIPLE=2, so the master (Phase A) raises
    INFEASIBLE with a lock-aware message. The pipeline catches the
    exception and returns status='master_failed' with the error
    message in the result dict."""
    profs = _make_profs()
    locked_dc = {("ProfA", "1A", "Mat", 2): 3}
    res = _run_temporal(profs, locked_dc=locked_dc)
    assert res["status"] == "master_failed"
    err = res.get("error", "")
    assert "INFEASIBLE" in err or "infeasible" in err.lower()
    assert "lock" in err.lower()
