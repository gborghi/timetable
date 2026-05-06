"""Standalone progress-aware runner for the real MEGA BP benchmark.

Writes progress lines to stdout and to a log file in real time,
so a long-running run is visible. Persists final metrics to
``tests/benchmarks/results/mega_bp_real.json`` under a key chosen
by ``--mode`` (``branch-and-price`` -> ``mega_real_bp``,
``iterative-diversified`` -> ``mega_real_id``).

    python tests/benchmarks/run_mega_real.py \
        --mode branch-and-price \
        --time-budget-bp 1800 \
        --time-budget-phase-a 300

The default time-budget-phase-a is 120s (we expect the pickled
MEGA Phase A to converge fast given the structured Italian-school
profile).
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
import time
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
ENGINE = os.path.join(ROOT, "engine")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

PROFS_PKL = os.path.join(
    ROOT, "engine", "scripts", "data", "mega", "profs_mega.pkl")
SCHOOL_PKL = os.path.join(
    ROOT, "engine", "scripts", "data", "mega", "school_mega.pkl")
RESULTS = Path(HERE) / "results" / "mega_bp_real.json"
LOG_DIR = Path(HERE) / "results"


def log(msg: str, log_file=None):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    if log_file is not None:
        log_file.write(line + "\n")
        log_file.flush()


def load_real_mega():
    with open(PROFS_PKL, "rb") as f:
        profs = pickle.load(f)
    with open(SCHOOL_PKL, "rb") as f:
        school = pickle.load(f)
    return profs, school


def run_phase_a(profs, time_limit_s, log_file):
    import cpsat_v2_timetable as cv2  # type: ignore
    log(f"Phase A: build_indices ...", log_file)
    t0 = time.time()
    classes_v, triples, class_profs = cv2.build_indices(profs)
    log(f"Phase A: build_indices done in {time.time()-t0:.1f}s "
        f"({len(triples)} triples)", log_file)
    log(f"Phase A: solve_phase_a (limit {time_limit_s:.0f}s) ...",
        log_file)
    t0 = time.time()
    dc_value = cv2.solve_phase_a(
        profs, classes_v, triples, class_profs,
        time_limit=int(time_limit_s),
        workers=4, log=False,
    )
    t = time.time() - t0
    if dc_value is None:
        log(f"Phase A: returned None after {t:.1f}s", log_file)
    else:
        n4 = sum(1 for k, v in dc_value.items()
                 if isinstance(k, tuple) and len(k) == 4 and v > 0)
        log(f"Phase A: ok in {t:.1f}s ({n4} cattedra-day entries)",
            log_file)
    return dc_value, t


def run_bp(profs, dc_value, time_budget_s, log_file):
    import column_generation as cg  # type: ignore
    log(f"BP: starting "
        f"(mode=branch-and-price, granularity=curriculum, "
        f"budget {time_budget_s:.0f}s)", log_file)
    t0 = time.time()
    sol, info = cg.run_column_generation(
        profs, dc_value,
        time_budget_s=time_budget_s,
        patterns_per_teacher=3,
        max_iterations=3,
        completion_time_limit=120.0,
        completion_workers=4,
        log=True,
        mode="branch-and-price",
        granularity="curriculum",
        branching_strategy="ryan_foster",
        bp_max_iterations=5,
        pricer_time_limit=10.0,
        pricer_workers=2,
        dual_stabilization=True,
        dual_step_alpha=0.2,
        max_active_columns=10000,
        rc_smoothing_horizon=20,
        parallel_workers=0,
    )
    t = time.time() - t0
    log(f"BP: done in {t:.1f}s, "
        f"feasible_assembly={info.get('feasible_after_assembly')}, "
        f"feasible_completion={info.get('feasible_after_completion')}",
        log_file)
    return sol, info, t


def run_iterative_diversified(profs, dc_value, time_budget_s, log_file):
    import column_generation as cg  # type: ignore
    log(f"ID: starting "
        f"(mode=iterative-diversified, budget {time_budget_s:.0f}s)",
        log_file)
    t0 = time.time()
    sol, info = cg.run_column_generation(
        profs, dc_value,
        time_budget_s=time_budget_s,
        patterns_per_teacher=3,
        max_iterations=5,
        completion_time_limit=120.0,
        completion_workers=4,
        log=False,
        mode="iterative-diversified",
    )
    t = time.time() - t0
    log(f"ID: done in {t:.1f}s, "
        f"feasible_assembly={info.get('feasible_after_assembly')}, "
        f"feasible_completion={info.get('feasible_after_completion')}",
        log_file)
    return sol, info, t


def persist(scale: str, metrics: dict, results_path: Path = RESULTS):
    results_path.parent.mkdir(parents=True, exist_ok=True)
    all_results: dict = {}
    if results_path.exists():
        try:
            with open(results_path, "r", encoding="utf-8") as f:
                all_results = json.load(f)
        except Exception:
            all_results = {}
    all_results[scale] = metrics
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--mode",
        choices=["branch-and-price", "iterative-diversified", "both"],
        default="both")
    ap.add_argument("--time-budget-bp", type=float, default=1800.0)
    ap.add_argument("--time-budget-id", type=float, default=600.0)
    ap.add_argument("--time-budget-phase-a", type=float, default=120.0)
    ap.add_argument("--log-file", default=None)
    ap.add_argument(
        "--results-file", default=None,
        help="Override the JSON results path (default: "
             "tests/benchmarks/results/mega_bp_real.json). Useful "
             "for re-running after a fix without overwriting v1.")
    args = ap.parse_args()
    results_path = (Path(args.results_file)
                     if args.results_file else RESULTS)

    log_path = args.log_file or os.path.join(
        LOG_DIR, f"mega_real_{int(time.time())}.log")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = open(log_path, "w", encoding="utf-8")
    try:
        log(f"=== run_mega_real start ===", log_file)
        log(f"log file: {log_path}", log_file)
        log(f"mode: {args.mode}", log_file)
        profs, school = load_real_mega()
        n_classes = len(school.get("classes", []))
        n_teachers = len(profs)
        log(f"loaded MEGA: {n_classes} classes / {n_teachers} teachers",
            log_file)

        dc_value, t_phase_a = run_phase_a(
            profs, args.time_budget_phase_a, log_file)
        if dc_value is None:
            log("Phase A returned None -- aborting", log_file)
            return 1

        n_cattedre = sum(1 for k, v in dc_value.items()
                         if isinstance(k, tuple)
                         and len(k) == 4 and v > 0)

        if args.mode in ("branch-and-price", "both"):
            sol, info, t_bp = run_bp(
                profs, dc_value, args.time_budget_bp, log_file)
            hard = bool(info.get("feasible_after_assembly")
                        or info.get("feasible_after_completion"))
            metrics = {
                "scenario": "mega_real",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "n_classes": n_classes,
                "n_teachers": n_teachers,
                "n_cattedre": n_cattedre,
                "mode": "branch-and-price",
                "granularity": "curriculum",
                "t_phase_a_s": float(t_phase_a),
                "t_bp_s": float(t_bp),
                "t_total_s": float(t_phase_a + t_bp),
                "target_total_s": 1800.0 + args.time_budget_phase_a,
                "hard_cap_total_s": 3600.0 + args.time_budget_phase_a,
                "hard_feasible": hard,
                "soft_obj": info.get("master_obj_final"),
                "n_columns": (info.get("bp_dw_n_columns")
                               or info.get("n_patterns_total_final")),
                "n_iterations": info.get("bp_iterations_done"),
                "n_rf_nodes_explored": info.get("rf_tree_nodes_explored"),
                "n_columns_purged": info.get(
                    "bp_columns_purged_total", 0),
                "parallel_workers_used": info.get(
                    "bp_parallel_workers_used", 1),
                "bp_terminated_reason": info.get("bp_terminated_reason"),
                "warnings": info.get("warnings", []),
            }
            persist("mega_real_bp", metrics, results_path)
            log(f"BP metrics persisted: hard={hard}, "
                f"t_total={metrics['t_total_s']:.1f}s", log_file)

        if args.mode in ("iterative-diversified", "both"):
            sol, info, t_id = run_iterative_diversified(
                profs, dc_value, args.time_budget_id, log_file)
            hard = bool(info.get("feasible_after_assembly")
                        or info.get("feasible_after_completion"))
            metrics = {
                "scenario": "mega_real",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "n_classes": n_classes,
                "n_teachers": n_teachers,
                "n_cattedre": n_cattedre,
                "mode": "iterative-diversified",
                "t_phase_a_s": float(t_phase_a),
                "t_id_s": float(t_id),
                "t_total_s": float(t_phase_a + t_id),
                "hard_feasible": hard,
                "soft_obj": info.get("master_obj_final"),
                "warnings": info.get("warnings", []),
            }
            persist("mega_real_id", metrics, results_path)
            log(f"ID metrics persisted: hard={hard}, "
                f"t_total={metrics['t_total_s']:.1f}s", log_file)

        log("=== run_mega_real done ===", log_file)
        return 0
    finally:
        log_file.close()


if __name__ == "__main__":
    sys.exit(main())
