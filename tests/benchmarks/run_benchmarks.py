"""Reproducible benchmark suite for piTantum solvers.

Iterates `(scenario, combination)` pairs N times, persisting one
row per run as CSV in `tests/benchmarks/results/`. Designed to be
runnable in two modes:

  --quick   1 run per (scenario, combination); skips the heavy
            ITP scenario; ~5-10 minutes total.
  --full    5 runs per (scenario, combination); includes ITP;
            >1 hour, intended for CI nightly or manual one-shot.

Each row records:
  scenario | combination | run_idx | seed | status |
  t_phase_a | t_phase_b | t_post | t_total |
  obj_value | n_lessons | hard_feasible | error_msg

Failures (timeout, infeasible, exceptions) are recorded as rows
with status != 'ok', NOT propagated as exceptions, so a single
failing run doesn't kill the whole batch.

Usage:
  cd webui/backend
  ../../.venv/Scripts/python -m tests.benchmarks.run_benchmarks --quick

Output:
  tests/benchmarks/results/bench_<timestamp>.csv
  tests/benchmarks/results/bench_latest.csv  (symlink-ish copy)
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import os
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

# Path bootstrap: import sibling test fixtures + engine.
HERE = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(TESTS_DIR)
ENGINE_DIR = os.path.join(REPO_ROOT, "engine")
SCHEDULE_DIR = os.path.join(REPO_ROOT, "schedule")
WEBUI_DIR = os.path.join(REPO_ROOT, "webui")
BACKEND_DIR = os.path.join(WEBUI_DIR, "backend")
for p in (REPO_ROOT, WEBUI_DIR, BACKEND_DIR, ENGINE_DIR, SCHEDULE_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


# --------------------------------------------------------------------
# Combinations to benchmark
# --------------------------------------------------------------------

@dataclass
class Combination:
    """A solver pipeline to time."""
    name: str
    description: str
    runner: Callable
    """Callable signature: (profs, inputs, dc, sol, *, time_a, time_b)
    -> (new_sol, info_dict). For the baseline `phase_b` it just
    returns (sol, {}).
    """


@dataclass
class BenchRow:
    scenario: str
    combination: str
    tightness_in: float    # input config tightness in [0, 1]
    tightness_score: float # measured composite score post-build
    run_idx: int
    seed: int
    status: str
    t_phase_a: float
    t_phase_b: float
    t_post: float
    t_total: float
    obj_value: Optional[float]
    n_lessons: Optional[int]
    hard_feasible: Optional[bool]
    n_assignments: int
    n_classes: int
    n_teachers: int
    error_msg: str


# --------------------------------------------------------------------
# Solver inner helpers
# --------------------------------------------------------------------

def _run_phase_b_mono(profs, inputs, *, time_a: float, time_b: float):
    """Phase A timetabling + per-day Phase B. Returns
    (dc, sol, t_phase_a, t_phase_b)."""
    import cpsat_v2_timetable as cv2  # type: ignore
    coteach, support, pot, par, grp = inputs
    classes_v, triples, class_profs = cv2.build_indices(profs)
    t0 = time.time()
    dc = cv2.solve_phase_a(
        profs, classes_v, triples, class_profs,
        time_limit=time_a, workers=2, log=False,
        coteach_groups=coteach, support_assignments=support,
        potenziamento_assignments=pot, parallel_groups=par,
        group_assignments=grp,
    )
    t_a = time.time() - t0
    full = {}
    t0 = time.time()
    for d in cv2.DAYS:
        out, _ = cv2.solve_phase_b_for_day(
            d, profs, classes_v, triples, class_profs, dc,
            time_limit=time_b, workers=2, log=False,
            coteach_groups=coteach, support_assignments=support,
            parallel_groups=par, group_assignments=grp,
        )
        if out:
            full.update(out)
    t_b = time.time() - t0
    return dc, full, t_a, t_b


def _runner_phase_b(profs, inputs, dc, sol, *, time_a, time_b):
    return sol, {}


def _runner_lns(profs, inputs, dc, sol, *, time_a, time_b):
    import metaheuristics as meta  # type: ignore
    coteach, support, pot, par, grp = inputs
    new_sol, _ = meta.run_lns(
        sol, profs, dc, time_budget_s=5.0, log=False, workers=2,
        coteach_groups=coteach, support_assignments=support,
        parallel_groups=par, group_assignments=grp,
    )
    return new_sol, {}


def _runner_sa(profs, inputs, dc, sol, *, time_a, time_b):
    import metaheuristics as meta  # type: ignore
    coteach, support, pot, par, grp = inputs
    new_sol = meta.run_sa(
        sol, profs, dc, time_budget_s=5.0, log=False,
        coteach_groups=coteach, support_assignments=support,
        parallel_groups=par, group_assignments=grp,
    )
    return new_sol, {}


def _runner_alns(profs, inputs, dc, sol, *, time_a, time_b):
    import alns as alns_mod  # type: ignore
    coteach, support, pot, par, grp = inputs
    new_sol, _ = alns_mod.run_alns(
        sol, profs, dc, time_budget_s=8.0, log=False, workers=2,
        coteach_groups=coteach, support_assignments=support,
        parallel_groups=par, group_assignments=grp,
    )
    return new_sol, {}


def _runner_vns(profs, inputs, dc, sol, *, time_a, time_b):
    import vns as vns_mod  # type: ignore
    coteach, support, pot, par, grp = inputs
    new_sol, _ = vns_mod.run_vns(
        sol, profs, dc, time_budget_s=5.0, log=False,
        coteach_groups=coteach, support_assignments=support,
        parallel_groups=par, group_assignments=grp,
    )
    return new_sol, {}


def _runner_lagrangian(profs, inputs, dc, sol, *, time_a, time_b):
    import lagrangian as lag_mod  # type: ignore
    coteach, support, pot, par, grp = inputs
    cls = sorted({c for p in profs.values() for c in p["classi"]})
    classes_clusters = {0: set(cls[:len(cls) // 2]),
                         1: set(cls[len(cls) // 2:])}
    new_sol, _ = lag_mod.run_lagrangian(
        sol, profs, dc, time_budget_s=8.0, max_iter=2,
        classes_clusters=classes_clusters, log=False,
        coteach_groups=coteach, support_assignments=support,
        parallel_groups=par, group_assignments=grp,
    )
    return new_sol, {}


def _runner_cg(profs, inputs, dc, sol, *, time_a, time_b):
    import column_generation as cg  # type: ignore
    coteach, support, pot, par, grp = inputs
    new_sol, info = cg.run_column_generation(
        profs, dc, time_budget_s=15.0, patterns_per_teacher=2,
        max_iterations=2, log=False,
        coteach_groups=coteach, support_assignments=support,
        parallel_groups=par, group_assignments=grp,
    )
    return new_sol if new_sol is not None else sol, info


COMBINATIONS: list[Combination] = [
    Combination("phase_b", "Phase A + Phase B mono baseline",
                 _runner_phase_b),
    Combination("phase_b+lns", "Phase B + 5s LNS post-pass",
                 _runner_lns),
    Combination("phase_b+sa", "Phase B + 5s SA post-pass",
                 _runner_sa),
    Combination("phase_b+alns", "Phase B + 8s ALNS post-pass",
                 _runner_alns),
    Combination("phase_b+vns", "Phase B + 5s VNS post-pass",
                 _runner_vns),
    Combination("phase_b+lagrangian",
                 "Phase B + 8s Lagrangian relaxation refinement",
                 _runner_lagrangian),
    Combination("phase_b+cg",
                 "Phase B + 15s Column Generation post-pass",
                 _runner_cg),
]


# --------------------------------------------------------------------
# Scenario builders (wrap the existing test fixtures)
# --------------------------------------------------------------------

def _make_scenario_db_session(profile: str):
    """Create a fresh sqlite DB + Session for a scenario."""
    import tempfile
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.orm import sessionmaker
    tmpdir = tempfile.mkdtemp(prefix=f"bench_{profile}_")
    url = f"sqlite:///{tmpdir}/bench.db"
    test_engine = create_engine(
        url,
        connect_args={"check_same_thread": False},
        future=True,
    )
    TestSession = sessionmaker(
        bind=test_engine, autoflush=False, autocommit=False,
        future=True,
    )
    from backend import db as backend_db
    from backend import models  # noqa: F401
    backend_db.Base.metadata.create_all(bind=test_engine)
    insp = inspect(test_engine)
    has_col = lambda tbl, col: (
        insp.has_table(tbl)
        and any(c["name"] == col for c in insp.get_columns(tbl))
    )
    with test_engine.begin() as conn:
        if insp.has_table("assignments"):
            for col, ddl in (
                ("coteach_group_id",
                 "ALTER TABLE assignments ADD COLUMN "
                 "coteach_group_id INTEGER"),
                ("is_support",
                 "ALTER TABLE assignments ADD COLUMN "
                 "is_support INTEGER NOT NULL DEFAULT 0"),
                ("is_potenziamento",
                 "ALTER TABLE assignments ADD COLUMN "
                 "is_potenziamento INTEGER NOT NULL DEFAULT 0"),
                ("parallel_group_id",
                 "ALTER TABLE assignments ADD COLUMN "
                 "parallel_group_id INTEGER"),
                ("group_id",
                 "ALTER TABLE assignments ADD COLUMN "
                 "group_id INTEGER"),
            ):
                if not has_col("assignments", col):
                    conn.execute(text(ddl))
        if insp.has_table("coteach_groups"):
            if not has_col("coteach_groups", "group_id"):
                conn.execute(text(
                    "ALTER TABLE coteach_groups ADD COLUMN "
                    "group_id INTEGER"))
        if insp.has_table("lessons"):
            if not has_col("lessons", "group_name"):
                conn.execute(text(
                    "ALTER TABLE lessons ADD COLUMN "
                    "group_name VARCHAR(120)"))
    return test_engine, TestSession


def _build_scenario(name: str, seed: int,
                     tightness: float = 0.5):
    """Returns (Scenario, db_session). Caller must close.

    `tightness` is mapped to the apply_tightness scaler on top of
    the factory defaults (see scenarios.builder).
    """
    from backend.tests.scenarios import (  # type: ignore
        Scenario, apply_tightness,
        liceo_piccolo, liceo_medio, istituto_tecnico, mega,
    )
    factories = {
        "liceo_piccolo": liceo_piccolo,
        "liceo_medio": liceo_medio,
        "istituto_tecnico": istituto_tecnico,
        "mega": mega,
    }
    factory = factories[name]
    cfg = factory(rng_seed=seed)
    cfg = apply_tightness(cfg, tightness)
    eng, Session = _make_scenario_db_session(name)
    db = Session()
    try:
        sc = Scenario.build(db, cfg)
    except Exception:
        db.close()
        raise
    return sc, db, eng


# --------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------

def _compute_softs(profs, sol):
    import metaheuristics as meta  # type: ignore
    try:
        v, m = meta.compute_soft(sol, profs)
        return float(v)
    except Exception:
        return None


def _is_hard_feasible(profs, sol, inputs):
    import metaheuristics as meta  # type: ignore
    coteach, support, pot, par, grp = inputs
    try:
        return bool(meta.is_hard_feasible(
            sol, profs, verbose=False,
            group_assignments=grp,
            coteach_groups=coteach,
            parallel_groups=par,
            support_assignments=support,
        ))
    except Exception:
        return None


def run_one(scenario_name: str, combo: Combination,
             run_idx: int, seed: int,
             tightness: float = 0.5,
             *, time_a_phase_a: float = 30.0,
             time_b: float = 12.0) -> BenchRow:
    """Build the scenario, run Phase A + Phase B + post-pass, time it."""
    from backend.tests.scenarios import tightness_score  # type: ignore
    started = time.time()
    error = ""
    status = "ok"
    t_a = t_b = t_post = 0.0
    obj = None
    n_lessons = None
    hard_ok = None
    n_a = n_c = n_t = 0
    measured_score = 0.0
    try:
        sc, db, eng = _build_scenario(scenario_name, seed, tightness)
        try:
            n_a = sc.meta.n_assignments
            n_c = sc.meta.n_classes
            n_t = sc.meta.n_teachers
            measured_score = tightness_score(sc.meta)
            profs, *rest = sc.solver_inputs()
            inputs = tuple(rest)
            dc, sol, t_a, t_b = _run_phase_b_mono(
                profs, inputs,
                time_a=time_a_phase_a, time_b=time_b,
            )
            n_lessons = sum(1 for v in sol.values() if v == 1)
            t_post0 = time.time()
            new_sol, _info = combo.runner(
                profs, inputs, dc, sol,
                time_a=time_a_phase_a, time_b=time_b,
            )
            t_post = time.time() - t_post0
            obj = _compute_softs(profs, new_sol)
            hard_ok = _is_hard_feasible(profs, new_sol, inputs)
            if hard_ok is False:
                status = "hard_violation"
        finally:
            db.close()
            eng.dispose()
    except Exception as e:
        status = "exception"
        error = f"{type(e).__name__}: {str(e)[:300]}"
        traceback.print_exc()
    t_total = time.time() - started
    return BenchRow(
        scenario=scenario_name, combination=combo.name,
        tightness_in=tightness, tightness_score=measured_score,
        run_idx=run_idx, seed=seed, status=status,
        t_phase_a=round(t_a, 2), t_phase_b=round(t_b, 2),
        t_post=round(t_post, 2), t_total=round(t_total, 2),
        obj_value=obj, n_lessons=n_lessons,
        hard_feasible=hard_ok,
        n_assignments=n_a, n_classes=n_c, n_teachers=n_t,
        error_msg=error,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true",
                     help="small only, 1 tightness, 1 run per pair")
    ap.add_argument("--full", action="store_true",
                     help="3 tightness x 3 scenarios x 3 runs")
    ap.add_argument("--mega", action="store_true",
                     help="include MEGA (long; budget hours)")
    ap.add_argument("--scenarios", type=str, default=None,
                     help="comma-separated list, overrides preset")
    ap.add_argument("--tightness", type=str, default=None,
                     help="comma-separated [0,1] floats")
    ap.add_argument("--n-runs", type=int, default=None,
                     help="runs per (scenario, combo, tightness)")
    ap.add_argument("--out", type=str, default=None,
                     help="output CSV path; default = "
                          "tests/benchmarks/results/bench_<ts>.csv")
    args = ap.parse_args()

    if args.scenarios:
        scenarios = [s.strip() for s in args.scenarios.split(",")
                      if s.strip()]
    elif args.mega:
        scenarios = ["liceo_piccolo", "liceo_medio",
                      "istituto_tecnico", "mega"]
    elif args.full:
        scenarios = ["liceo_piccolo", "liceo_medio",
                      "istituto_tecnico"]
    else:
        scenarios = ["liceo_piccolo"]

    if args.tightness:
        tightness_levels = [float(x) for x in
                             args.tightness.split(",") if x.strip()]
    elif args.full or args.mega:
        tightness_levels = [0.2, 0.5, 0.8]
    else:
        tightness_levels = [0.5]

    if args.n_runs is not None:
        n_runs = max(1, args.n_runs)
    elif args.full or args.mega:
        n_runs = 3
    else:
        n_runs = 1

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    if args.out:
        out_path = args.out
    else:
        out_path = os.path.join(
            HERE, "results", f"bench_{ts}.csv")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    fields = [f.name for f in dataclasses.fields(BenchRow)]
    n_done = 0
    started = time.time()
    total_pairs = (len(scenarios) * len(COMBINATIONS)
                    * len(tightness_levels) * n_runs)
    print(f"[bench] writing to {out_path}")
    print(f"[bench] grid: {len(scenarios)} scenarios x "
          f"{len(COMBINATIONS)} combos x "
          f"{len(tightness_levels)} tightness x {n_runs} runs "
          f"= {total_pairs} total")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for sc_name in scenarios:
            for tlev in tightness_levels:
                for combo in COMBINATIONS:
                    for run_idx in range(n_runs):
                        seed = 42 + run_idx
                        print(f"\n[bench] {n_done + 1}/{total_pairs} "
                              f"=== {sc_name} | t={tlev} | "
                              f"{combo.name} | run {run_idx + 1}"
                              f"/{n_runs} (seed={seed}) ===")
                        row = run_one(sc_name, combo, run_idx,
                                       seed, tightness=tlev)
                        w.writerow(dataclasses.asdict(row))
                        f.flush()
                        n_done += 1
                        print(f"[bench]    -> status={row.status} "
                              f"t_total={row.t_total}s "
                              f"obj={row.obj_value} "
                              f"score={row.tightness_score}")
    # Update bench_latest.csv copy for downstream plotting
    latest = os.path.join(HERE, "results", "bench_latest.csv")
    try:
        import shutil
        shutil.copy(out_path, latest)
    except Exception:
        pass
    elapsed = time.time() - started
    print(f"\n[bench] DONE: {n_done} rows in {elapsed:.1f}s "
          f"-> {out_path}")


if __name__ == "__main__":
    main()
