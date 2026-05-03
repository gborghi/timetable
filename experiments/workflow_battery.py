"""Battery test harness for the Workflow tab.

Hits every standalone endpoint + a curated set of multi-step pipelines
+ every diagnostics endpoint, against the live backend on
http://127.0.0.1:8000. Reports pass / fail + the error message.

USE
    # Make sure the backend is running on :8000 and a profile is
    # already loaded (small recommended for speed).
    cd experiments
    python workflow_battery.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
import urllib.error

BACKEND = "http://127.0.0.1:8000"


def _post(path, body=None, timeout=30):
    data = json.dumps(body or {}).encode("utf-8")
    req = urllib.request.Request(BACKEND + path, data=data,
                                  method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _get(path, timeout=30):
    with urllib.request.urlopen(BACKEND + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _wait_run(run_id, max_s=120):
    deadline = time.time() + max_s
    while time.time() < deadline:
        try:
            run = _get(f"/api/optimize/runs/{run_id}")
            if run.get("status") in ("done", "failed"):
                return run
        except Exception:
            pass
        time.sleep(1)
    return {"status": "timeout"}


def _step(name, fn):
    print(f"\n[battery] === {name} ===")
    try:
        ok, info = fn()
        ICON = "OK " if ok else "ERR"
        print(f"  {ICON}  {info}")
        return ok, info
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        print(f"  ERR  HTTP {e.code}: {body}")
        return False, f"HTTP {e.code}: {body}"
    except Exception as e:
        print(f"  ERR  {type(e).__name__}: {e}")
        return False, str(e)


def _check_run(run_id, max_s=120):
    run = _wait_run(run_id, max_s=max_s)
    st = run.get("status")
    if st != "done":
        err = (run.get("error") or "").splitlines()[-1] if run.get("error") else st
        return False, f"run_{run_id} status={st}: {err}"
    return True, f"run_{run_id} done in {run.get('finished_at')}"


# ---------------------------------------------------------------------
# Test suites
# ---------------------------------------------------------------------

STANDALONE_STEPS = [
    ("hall-check",
        lambda: _post("/api/optimize/hall-check", {})),
    ("assignment (Phase A)",
        lambda: _post("/api/optimize/assignment",
                       {"time_limit_s": 15, "workers": 4, "log": False,
                        "criterion": "balance_weight"})),
    ("phase-b",
        lambda: _post("/api/optimize/phase-b",
                       {"k": 4, "time_a": 10, "time_bridges": 10,
                        "time_cluster": 10, "time_ricucitura": 10,
                        "time_mono": 10, "workers": 4, "log": False,
                        "use_decomposition": True,
                        "optimize_rooms": False})),
    ("meta lns",
        lambda: _post("/api/optimize/meta/lns",
                       {"budget_s": 10, "workers": 2, "log": False,
                        "n_cycles": 1})),
    ("meta sa",
        lambda: _post("/api/optimize/meta/sa",
                       {"budget_s": 10, "workers": 2, "log": False,
                        "n_cycles": 1})),
    ("meta ts",
        lambda: _post("/api/optimize/meta/ts",
                       {"budget_s": 10, "workers": 2, "log": False,
                        "n_cycles": 1})),
    ("meta alns",
        lambda: _post("/api/optimize/meta/alns",
                       {"budget_s": 10, "workers": 2, "log": False,
                        "n_cycles": 1})),
    ("meta vns",
        lambda: _post("/api/optimize/meta/vns",
                       {"budget_s": 10, "workers": 2, "log": False,
                        "n_cycles": 1})),
    ("meta ils",
        lambda: _post("/api/optimize/meta/ils",
                       {"budget_s": 10, "workers": 2, "log": False,
                        "n_cycles": 1})),
    ("rooms",
        lambda: _post("/api/optimize/rooms",
                       {"time_limit_s": 10, "workers": 2,
                        "log": False, "prefer_home": True})),
    ("decomposition recommend",
        lambda: _get("/api/optimize/decomposition/recommend")),
    ("decomposition temporal",
        lambda: _post("/api/optimize/decomposition/temporal",
                       {"pre_distribution_time": 10, "day_time": 10,
                        "parallel_workers": 4})),
    ("decomposition metis",
        lambda: _post("/api/optimize/decomposition/metis",
                       {"k": 0, "imbalance": 1.05,
                        "time_per_cluster": 10, "time_bridges": 10})),
    ("decomposition curriculum",
        lambda: _post("/api/optimize/decomposition/curriculum",
                       {"min_cluster_size": 3,
                        "time_per_cluster": 10, "time_bridges": 10})),
    ("column-generation",
        lambda: _post("/api/optimize/column-generation",
                       {"time_budget_s": 15,
                        "patterns_per_teacher": 2,
                        "max_iterations": 2,
                        "granularity": "teacher",
                        "branching_strategy": "ryan_foster",
                        "parallel": False, "log": False})),
]


def _full_pipeline(steps, name=None, profile="small"):
    """Build a payload for /api/optimize/full-pipeline with the given
    ordered step list + tight time budgets."""
    return {
        "profile": profile,
        "steps": steps,
        "workers": 4,
        "time_assign": 10,
        "phase_b": {"k": 4, "time_a": 10, "time_bridges": 10,
                    "time_cluster": 10, "time_ricucitura": 10,
                    "time_mono": 10, "workers": 4, "log": False,
                    "use_decomposition": True,
                    "optimize_rooms": False,
                    "rooms_time_limit_s": 10,
                    "rooms_prefer_home": True},
        "budget_lns": 8, "budget_sa": 8, "budget_ts": 8,
        "budget_ils": 8,
        "meta_optimize_rooms": False,
        "meta_rooms_time_limit_s": 10,
        "meta_rooms_prefer_home": True,
    }


PIPELINE_COMBOS = [
    ("phase_a only", ["phase_a"]),
    ("phase_a + phase_b", ["phase_a", "phase_b"]),
    ("phase_a + decomp_temporal", ["phase_a", "decomp_temporal"]),
    ("phase_a + decomp_metis", ["phase_a", "decomp_metis"]),
    ("phase_a + decomp_curriculum", ["phase_a", "decomp_curriculum"]),
    ("hall + phase_a + phase_b", ["hall_check", "phase_a", "phase_b"]),
    ("phase_a + phase_b + lns",
        ["phase_a", "phase_b", "lns"]),
    ("phase_a + phase_b + alns + sa + ts",
        ["phase_a", "phase_b", "alns", "sa", "ts"]),
    ("phase_a + phase_b + cg",
        ["phase_a", "phase_b", "cg"]),
    ("only meta on existing solution",
        ["lns", "sa"]),
    ("reorder: ts before sa",
        ["phase_a", "phase_b", "ts", "sa"]),
    ("reorder: ils first among meta",
        ["phase_a", "phase_b", "ils", "lns", "sa"]),
    ("scheduler conflict (decomp_temporal + phase_b -> first wins)",
        ["phase_a", "decomp_temporal", "phase_b"]),
    ("rooms only", ["rooms"]),
    ("phase_a + phase_b + rooms",
        ["phase_a", "phase_b", "rooms"]),
    ("everything tickable except cg/lagrangian",
        ["hall_check", "phase_a", "phase_b", "lns", "alns",
         "sa", "ts", "vns", "ils", "rooms"]),
]


DIAGNOSTICS = [
    ("/api/diagnostics/multi-criteria",
        lambda: _post("/api/diagnostics/multi-criteria", {})),
    ("/api/diagnostics/breaking-points",
        lambda: _post("/api/diagnostics/breaking-points",
                       {"deltas": [-0.05, 0.05]})),
    ("/api/diagnostics/comparator",
        lambda: _get("/api/diagnostics/comparator")),
    ("/api/diagnostics/distributions",
        lambda: _post("/api/diagnostics/distributions", {})),
    ("/api/dashboard/graph?mode=classes",
        lambda: _get("/api/dashboard/graph?mode=classes")),
    ("/api/dashboard/graph?mode=teachers",
        lambda: _get("/api/dashboard/graph?mode=teachers")),
    ("/api/optimize/runs?limit=5",
        lambda: _get("/api/optimize/runs?limit=5")),
    ("/api/dataset/state",
        lambda: _get("/api/dataset/state")),
    ("/api/dataset/available-profiles",
        lambda: _get("/api/dataset/available-profiles")),
]


# ---------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------

def main():
    results = {"standalone": {}, "pipeline": {}, "diagnostics": {}}

    print("\n========== STANDALONE STEPS ==========")
    for label, fn in STANDALONE_STEPS:
        def doit(label=label, fn=fn):
            r = fn()
            if isinstance(r, dict) and "run_id" in r:
                ok, info = _check_run(r["run_id"], max_s=180)
                return ok, info
            return True, "sync ok"
        results["standalone"][label] = _step(label, doit)

    print("\n========== PIPELINE COMBOS ==========")
    for label, steps in PIPELINE_COMBOS:
        def doit(label=label, steps=steps):
            r = _post("/api/optimize/full-pipeline",
                      _full_pipeline(steps))
            return _check_run(r["run_id"], max_s=240)
        results["pipeline"][label] = _step(label, doit)

    print("\n========== DIAGNOSTICS ==========")
    for label, fn in DIAGNOSTICS:
        def doit(label=label, fn=fn):
            r = fn()
            return True, f"keys={list(r.keys())[:5] if isinstance(r, dict) else type(r).__name__}"
        results["diagnostics"][label] = _step(label, doit)

    # ----- summary -----
    print("\n\n========== SUMMARY ==========")
    for section in ("standalone", "pipeline", "diagnostics"):
        n_ok = sum(1 for ok, _ in results[section].values() if ok)
        n_tot = len(results[section])
        print(f"\n{section}: {n_ok}/{n_tot} pass")
        for label, (ok, info) in results[section].items():
            status = "PASS" if ok else "FAIL"
            print(f"  [{status}] {label} -- {info[:120]}")
    n_fail = sum(1 for sec in results.values()
                  for ok, _ in sec.values() if not ok)
    print(f"\nTotal failures: {n_fail}")
    sys.exit(n_fail)


if __name__ == "__main__":
    main()
