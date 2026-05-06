"""Granularity-vs-BP matrix on the real MEGA dataset.

Runs ``mode="branch-and-price"`` against the same MEGA instance
(100 classes, 178 teachers) once per granularity and persists every
result row into a single matrix JSON. Phase A is computed once and
cached as a pickle so the 9 BP runs share the same primal warm-start
seed.

Usage:
    python tests/benchmarks/run_mega_granularity_matrix.py \\
        --time-budget-bp 1800 \\
        --time-budget-phase-a 600 \\
        --skip teacher curriculum \\
        --results-file tests/benchmarks/results/mega_bp_granularity_matrix.json

Already-recorded granularities are NOT skipped automatically; pass
--skip to omit them. The granularity ``auto`` resolves to whatever
``_suggest_cg_granularity(n_classes)`` returns (= curriculum on
100 classes).
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
import time
import traceback
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
ENGINE = os.path.join(ROOT, "engine")
WEBUI = os.path.join(ROOT, "webui")
for p in (ENGINE, WEBUI):
    if p not in sys.path:
        sys.path.insert(0, p)

PROFS_PKL = os.path.join(
    ROOT, "engine", "scripts", "data", "mega", "profs_mega.pkl")
SCHOOL_PKL = os.path.join(
    ROOT, "engine", "scripts", "data", "mega", "school_mega.pkl")
RESULTS_DIR = Path(HERE) / "results"
DC_VALUE_PKL = RESULTS_DIR / "mega_phase_a_dc_value.pkl"
DEFAULT_RESULTS = RESULTS_DIR / "mega_bp_granularity_matrix.json"

GRANULARITIES = (
    "auto",
    "teacher",
    "teacher-day",
    "teacher-class",
    "teacher-class-subject",
    "teacher-subject",
    "class",
    "class-day",
    "day",
    "curriculum",
)


def log(msg: str, log_file=None) -> None:
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


def compute_or_load_phase_a(profs, time_limit_s, log_file):
    """Return (dc_value, t_phase_a). On cache hit, t_phase_a=0."""
    if DC_VALUE_PKL.exists():
        try:
            with open(DC_VALUE_PKL, "rb") as f:
                dc_value = pickle.load(f)
            n4 = sum(1 for k, v in dc_value.items()
                     if isinstance(k, tuple) and len(k) == 4 and v > 0)
            log(f"Phase A: loaded from cache "
                f"({DC_VALUE_PKL.name}, {n4} entries)", log_file)
            return dc_value, 0.0
        except Exception as e:  # noqa: BLE001
            log(f"Phase A: cache read failed ({e}); recomputing",
                log_file)

    import cpsat_v2_timetable as cv2  # type: ignore
    log("Phase A: build_indices ...", log_file)
    t0 = time.time()
    classes_v, triples, class_profs = cv2.build_indices(profs)
    log(f"Phase A: build_indices done in {time.time()-t0:.1f}s "
        f"({len(triples)} triples)", log_file)
    log(f"Phase A: solve_phase_a (limit {time_limit_s:.0f}s) ...",
        log_file)
    t0 = time.time()
    dc_value = cv2.solve_phase_a(
        profs, classes_v, triples, class_profs,
        time_limit=int(time_limit_s), workers=4, log=False,
    )
    t = time.time() - t0
    if dc_value is None:
        log(f"Phase A: returned None after {t:.1f}s", log_file)
        return None, t
    n4 = sum(1 for k, v in dc_value.items()
             if isinstance(k, tuple) and len(k) == 4 and v > 0)
    log(f"Phase A: ok in {t:.1f}s ({n4} cattedra-day entries)",
        log_file)
    DC_VALUE_PKL.parent.mkdir(parents=True, exist_ok=True)
    with open(DC_VALUE_PKL, "wb") as f:
        pickle.dump(dc_value, f)
    log(f"Phase A: cached at {DC_VALUE_PKL}", log_file)
    return dc_value, t


def run_bp_granularity(profs, dc_value, granularity, time_budget_s,
                       log_file):
    """Run BP for one granularity. Returns the metrics dict."""
    import column_generation as cg  # type: ignore
    log(f"BP[{granularity}]: starting "
        f"(budget {time_budget_s:.0f}s)", log_file)
    t0 = time.time()
    err = None
    sol, info = None, {}
    try:
        sol, info = cg.run_column_generation(
            profs, dc_value,
            time_budget_s=time_budget_s,
            patterns_per_teacher=3,
            max_iterations=3,
            completion_time_limit=120.0,
            completion_workers=4,
            log=False,
            mode="branch-and-price",
            granularity=granularity,
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
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
        log(f"BP[{granularity}]: EXCEPTION {err}", log_file)
        log(traceback.format_exc(), log_file)
    t = time.time() - t0
    hard = bool(info.get("feasible_after_assembly")
                or info.get("feasible_after_completion"))
    metrics = {
        "granularity": granularity,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "t_bp_s": float(t),
        "hard_feasible": hard,
        "soft_obj": info.get("master_obj_final"),
        "n_columns": (info.get("bp_dw_n_columns")
                      or info.get("n_patterns_total_final")),
        "n_iterations": info.get("bp_iterations_done"),
        "n_rf_nodes_explored": info.get("rf_tree_nodes_explored"),
        "n_columns_purged": info.get("bp_columns_purged_total", 0),
        "bp_terminated_reason": info.get("bp_terminated_reason"),
        "warnings": info.get("warnings", []),
        "exception": err,
    }
    if err is None:
        log(f"BP[{granularity}]: done in {t:.1f}s, "
            f"hard={hard}, soft={metrics['soft_obj']}, "
            f"iters={metrics['n_iterations']}, "
            f"reason={metrics['bp_terminated_reason']!r}",
            log_file)
    return metrics


def persist_row(metrics: dict, results_path: Path) -> None:
    results_path.parent.mkdir(parents=True, exist_ok=True)
    all_results: dict = {}
    if results_path.exists():
        try:
            with open(results_path, "r", encoding="utf-8") as f:
                all_results = json.load(f)
        except Exception:
            all_results = {}
    all_results[metrics["granularity"]] = metrics
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--time-budget-bp", type=float, default=1800.0)
    ap.add_argument("--time-budget-phase-a", type=float, default=600.0)
    ap.add_argument("--skip", nargs="*", default=[])
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--log-file", default=None)
    ap.add_argument(
        "--results-file", default=str(DEFAULT_RESULTS))
    args = ap.parse_args()

    log_path = args.log_file or os.path.join(
        RESULTS_DIR, f"mega_matrix_{int(time.time())}.log")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    log_file = open(log_path, "w", encoding="utf-8")
    results_path = Path(args.results_file)
    try:
        log("=== run_mega_granularity_matrix start ===", log_file)
        log(f"log file: {log_path}", log_file)
        log(f"results file: {results_path}", log_file)

        profs, school = load_real_mega()
        n_classes = len(school.get("classes", []))
        n_teachers = len(profs)
        log(f"loaded MEGA: {n_classes} classes / "
            f"{n_teachers} teachers", log_file)

        dc_value, t_phase_a = compute_or_load_phase_a(
            profs, args.time_budget_phase_a, log_file)
        if dc_value is None:
            log("Phase A returned None -- aborting", log_file)
            return 1
        n_cattedre = sum(1 for k, v in dc_value.items()
                         if isinstance(k, tuple)
                         and len(k) == 4 and v > 0)

        targets = (list(args.only) if args.only
                   else list(GRANULARITIES))
        targets = [g for g in targets if g not in set(args.skip)]
        log(f"targets ({len(targets)}): {targets}", log_file)

        for gran in targets:
            metrics = run_bp_granularity(
                profs, dc_value, gran,
                args.time_budget_bp, log_file)
            metrics["scenario"] = "mega_real"
            metrics["n_classes"] = n_classes
            metrics["n_teachers"] = n_teachers
            metrics["n_cattedre"] = n_cattedre
            metrics["t_phase_a_s"] = float(t_phase_a)
            persist_row(metrics, results_path)
            log(f"persisted granularity={gran!r}", log_file)
        log("=== run_mega_granularity_matrix done ===", log_file)
        return 0
    finally:
        log_file.close()


if __name__ == "__main__":
    sys.exit(main())
