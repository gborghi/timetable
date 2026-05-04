"""Performance regression tests.

These tests guard against the kind of regression that would have
been caught EARLIER if it had existed: a sync diagnostic endpoint
that locks the FastAPI event loop for 30s, a list endpoint that
suddenly takes seconds because of an N+1 query introduced by a
new ORM relationship, or a saved-views fetch that turns into a
slow LIKE query.

Each test enforces a wall-clock budget. Numbers are deliberately
generous (5x typical observed latency) so the tests don't flake
on slow CI hardware, but tight enough to fail when something
genuinely degrades by an order of magnitude.

The tests use FastAPI TestClient against the live (dev) DB so
they reflect realistic data volumes (1100 students, 90 teachers,
50 classes, 11k lessons).
"""
from __future__ import annotations

import os
import sys
import time

import pytest

# Make backend importable regardless of cwd.
HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(os.path.dirname(HERE))
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)


@pytest.fixture(scope="module")
def client():
    """One TestClient per module against the live app."""
    from fastapi.testclient import TestClient
    from backend.main import app
    return TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def _warmup_diagnostic_endpoints(client):
    """Pay the cold-start cost (SQLAlchemy connection pool, GIL
    contention from the previous test's bg threads) BEFORE the first
    parametrized `test_heavy_diagnostic_is_async` runs, so its 1000ms
    budget reflects steady-state behaviour.

    The first POST to /api/diagnostics/* creates the run row and
    spawns the async target thread. On a cold process the very first
    POST can absorb several hundred ms of pool init -- enough to
    occasionally push `correlations-body2` (the third parametrized
    variant) over budget when it follows two other heavy POSTs.

    We discard the response: this is purely a warmup."""
    try:
        client.post("/api/diagnostics/distributions", json={})
    except Exception:
        # Warmup must never fail the suite; swallow and let the real
        # tests report any actual problem.
        pass
    yield


# ----- List endpoints budgets ----------------------------------------

LIST_BUDGETS_MS = {
    "/api/teachers": 1500,
    "/api/classes": 1500,
    "/api/classrooms": 1500,
    "/api/subjects": 1500,
    "/api/students?limit=10": 3000,    # students has paginated hot path
    "/api/saved-views": 500,
    "/api/saved-views?entity=teachers": 500,
    "/api/optimize/runs?limit=15": 1000,
    "/api/dataset/state": 500,
    "/api/health": 200,
    "/api/monitor/constraints": 1500,
}


@pytest.mark.parametrize("path,budget_ms", list(LIST_BUDGETS_MS.items()))
def test_list_endpoint_within_budget(client, path, budget_ms):
    """Each list endpoint must return within `budget_ms`. Failure
    here means a UI tab will FEEL stuck."""
    t0 = time.time()
    r = client.get(path)
    dt_ms = (time.time() - t0) * 1000.0
    assert r.status_code == 200, (
        f"{path} returned {r.status_code}: {r.text[:200]}"
    )
    assert dt_ms < budget_ms, (
        f"{path} took {dt_ms:.0f}ms (budget {budget_ms}ms)"
    )


# ----- Diagnostic endpoints MUST be async ---------------------------

# Heavy diagnostics MUST spawn a /runs entry and return quickly.
# Synchronously running them would freeze the FastAPI event loop
# (10-30s on a real school) -- the bug Giovanni hit. These tests
# enforce that POST /api/diagnostics/<x> returns within 1 second
# with a `run_id` field, NOT the full result inline.

ASYNC_DIAG_ENDPOINTS = [
    ("/api/diagnostics/montecarlo", {"n_samples": 100}),
    ("/api/diagnostics/bipartite", {"mode": "classes"}),
    ("/api/diagnostics/correlations", {}),
    ("/api/diagnostics/distributions", {}),
]


@pytest.mark.parametrize("path,body", ASYNC_DIAG_ENDPOINTS)
def test_heavy_diagnostic_is_async(client, path, body):
    """The POST must return < 1s with {run_id} -- not block until
    the analysis completes."""
    t0 = time.time()
    r = client.post(path, json=body)
    dt_ms = (time.time() - t0) * 1000.0
    assert r.status_code == 200, (
        f"{path}: {r.status_code} {r.text[:200]}"
    )
    assert dt_ms < 1000, (
        f"{path} took {dt_ms:.0f}ms - it must be ASYNC. "
        f"If you see this, you probably re-introduced sync logic."
    )
    body_json = r.json()
    assert "run_id" in body_json, (
        f"{path} must return a run_id; got keys {list(body_json.keys())}"
    )


def test_hall_check_sync_path_stays_fast(client):
    """Hall pre-check exposes BOTH a default async path (returns
    {run_id}) and an opt-in inline path (sync=true, returns the full
    diagnostic dict). The inline path powers the green/red button on
    PhaseACard and MUST be fast enough to feel responsive (< 2s on
    the dev DB).

    Renamed from `test_hall_check_stays_sync_and_fast`: hall-check is
    no longer sync by DEFAULT (commit 9568218 made it async unless
    sync=true), but the sync path still exists and still has a budget.
    """
    t0 = time.time()
    r = client.post(
        "/api/diagnostics/hall-check",
        json={"n_samples": 256, "sync": True},
    )
    dt_ms = (time.time() - t0) * 1000.0
    assert r.status_code == 200, r.text[:200]
    assert dt_ms < 2000, f"Hall check took {dt_ms:.0f}ms (budget 2000ms)"
    res = r.json()
    assert "ok" in res
    assert "n_classes" in res
    assert "n_teachers" in res


def test_hall_check_default_is_async(client):
    """The default POST (no sync flag) must spawn an async run and
    return {run_id} within the same 1s budget as the other heavy
    diagnostics. Guards against accidentally re-defaulting to sync."""
    t0 = time.time()
    r = client.post("/api/diagnostics/hall-check", json={"n_samples": 256})
    dt_ms = (time.time() - t0) * 1000.0
    assert r.status_code == 200, r.text[:200]
    assert dt_ms < 1000, (
        f"hall-check (async path) took {dt_ms:.0f}ms - it must be ASYNC."
    )
    res = r.json()
    assert "run_id" in res, (
        f"hall-check default must return run_id; got keys {list(res.keys())}"
    )


# ----- Cumulative tab-switch budget ---------------------------------

def test_full_tab_cycle_within_budget(client):
    """Simulate a user clicking through ALL list tabs sequentially
    (the scenario the user reported as 'after 3-4 tabs the page
    freezes'). Total wallclock for the 7 main list endpoints must
    fit in 15 seconds.

    The budget is generous because the test runs in-process via
    TestClient AGAINST THE LIVE DEV DB (1100 students, 90
    teachers, 11k lessons), and may overlap with a running
    uvicorn that also queries SQLite -- the test is meant to
    catch order-of-magnitude regressions, not micro-tuning.
    """
    tabs = [
        "/api/teachers",
        "/api/classes",
        "/api/classrooms",
        "/api/subjects",
        "/api/students?limit=10",
        "/api/groups",
        "/api/curricula",
    ]
    t0 = time.time()
    for path in tabs:
        r = client.get(path)
        assert r.status_code == 200, f"{path}: {r.status_code}"
    dt_total = time.time() - t0
    assert dt_total < 15.0, (
        f"Tab cycle took {dt_total:.1f}s (budget 15s). "
        f"This is the scenario the user reports as 'stuck'."
    )


# ----- Saved views must NOT introduce N+1 ---------------------------

def test_saved_views_list_constant_time(client):
    """The /api/saved-views endpoint must scale O(1) wrt other
    entities -- a regression that joined into other tables would
    show up as a >2s response on the dev DB.
    Also exercises the entity= filter."""
    for entity in ("teachers", "classes", "classrooms", "subjects",
                    "students", "groups", "curricula"):
        t0 = time.time()
        r = client.get(f"/api/saved-views?entity={entity}")
        dt_ms = (time.time() - t0) * 1000.0
        assert r.status_code == 200
        assert dt_ms < 2000, (
            f"saved-views?entity={entity}: {dt_ms:.0f}ms"
        )


# ----- Run summary budget -------------------------------------------

def test_run_summary_lightweight(client):
    """The /api/optimize/runs/{id}/summary aggregate must be cheap
    even on runs with thousands of telemetry samples. We test on
    run_id=1 if it exists, else skip. Budget 2s (telemetry sums)."""
    runs = client.get("/api/optimize/runs?limit=1").json()
    if not runs:
        pytest.skip("no runs yet on this DB")
    rid = runs[0]["id"]
    t0 = time.time()
    r = client.get(f"/api/optimize/runs/{rid}/summary")
    dt_ms = (time.time() - t0) * 1000.0
    assert r.status_code == 200
    assert dt_ms < 2000, (
        f"runs/{rid}/summary took {dt_ms:.0f}ms (budget 2000ms)"
    )
