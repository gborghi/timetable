"""Step 4c smoke benchmark on the SMALL/MEDIUM scenarios.

The full 10-granularity matrix on the real MEGA dataset (100 classes
/ 178 teachers) takes ~60-90 minutes per granularity with the BP+RF
stack and is therefore deferred to a user-driven multi-hour run via
``run_mega_bp_step4_oo_rf.py``. This script validates the same Step
4 code path end-to-end on a small synthetic instance (~5 classes)
that fits a 5-minute budget per granularity, so the new BP+RF stack
gets exercised across every dispatch path under CI-friendly bounds.

Output JSON: ``tests/benchmarks/results/step4_smoke_{scale}.json``.
"""
from __future__ import annotations

import argparse
import json
import os
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


GRANULARITIES = (
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


def build_small_scenario():
    """3-class hand-built scenario with 4 teachers (~24 hours/class).
    Each class lands in {0, 4, 5, 6} hours/day after Phase A."""
    profs = {
        "Rossi": {
            "classi": {
                "1A": {"Matematica": {"ore": 4}},
                "1B": {"Matematica": {"ore": 4}},
                "2A": {"Matematica": {"ore": 4}},
            }, "glibero": [6], "max_hours": 18,
        },
        "Bianchi": {
            "classi": {
                "1A": {"Italiano": {"ore": 4}},
                "1B": {"Italiano": {"ore": 4}},
                "2A": {"Italiano": {"ore": 4}},
            }, "glibero": [6], "max_hours": 18,
        },
        "Verdi": {
            "classi": {
                "1A": {"Storia": {"ore": 4},
                        "Filosofia": {"ore": 4}},
                "1B": {"Storia": {"ore": 4},
                        "Filosofia": {"ore": 4}},
                "2A": {"Storia": {"ore": 4},
                        "Filosofia": {"ore": 4}},
            }, "glibero": [6], "max_hours": 18,
        },
        "Neri": {
            "classi": {
                "1A": {"Scienzemotorie": {"ore": 2},
                        "Inglese": {"ore": 4},
                        "Latino": {"ore": 4}},
                "1B": {"Scienzemotorie": {"ore": 2},
                        "Inglese": {"ore": 4},
                        "Latino": {"ore": 4}},
                "2A": {"Scienzemotorie": {"ore": 2},
                        "Inglese": {"ore": 4},
                        "Latino": {"ore": 4}},
            }, "glibero": [6], "max_hours": 18,
        },
    }
    return profs


def run_one_granularity(profs, dc_value, granularity,
                         time_budget_s, *,
                         rf_pricing_in_nodes: bool):
    import column_generation as cg  # type: ignore
    import metaheuristics as meta  # type: ignore
    t0 = time.time()
    err = None
    sol, info = None, {}
    try:
        sol, info = cg.run_column_generation(
            profs, dc_value,
            time_budget_s=time_budget_s,
            patterns_per_teacher=2,
            max_iterations=2,
            completion_time_limit=15.0,
            completion_workers=2,
            log=False,
            mode="branch-and-price",
            granularity=granularity,
            branching_strategy="ryan_foster",
            bp_max_iterations=3,
            pricer_time_limit=2.0,
            pricer_workers=1,
            dual_stabilization=True,
            dual_step_alpha=0.2,
            max_active_columns=2000,
            rc_smoothing_horizon=10,
            parallel_workers=0,
            rf_pricing_in_nodes=rf_pricing_in_nodes,
            rf_max_depth=4,
            rf_max_nodes=20,
        )
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
        traceback.print_exc()
    t = time.time() - t0
    hard = bool(info.get("feasible_after_assembly")
                or info.get("feasible_after_completion"))
    soft_obj_actual = None
    if sol and meta.is_hard_feasible(sol, profs, verbose=False):
        v, _ = meta.compute_soft(sol, profs)
        soft_obj_actual = float(v)
    return {
        "granularity": granularity,
        "rf_pricing_in_nodes": rf_pricing_in_nodes,
        "t_bp_s": t,
        "hard_feasible": hard,
        "soft_obj": info.get("master_obj_final"),
        "soft_obj_actual": soft_obj_actual,
        "n_columns": info.get("bp_dw_n_columns") or info.get(
            "n_patterns_total_final"),
        "n_iterations": info.get("bp_iterations_done"),
        "rf_tree_nodes_explored": info.get("rf_tree_nodes_explored"),
        "rf_tree_pricing_calls": info.get("rf_tree_pricing_calls", 0),
        "rf_tree_columns_added_in_nodes": info.get(
            "rf_tree_columns_added_in_nodes", 0),
        "rf_tree_terminated_reason": info.get(
            "rf_tree_terminated_reason"),
        "bp_terminated_reason": info.get("bp_terminated_reason"),
        "exception": err,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--time-budget-bp", type=float, default=20.0)
    ap.add_argument("--time-budget-phase-a", type=float, default=10.0)
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--results-file", default=None)
    args = ap.parse_args()

    out_dir = Path(HERE) / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = Path(
        args.results_file or out_dir / "step4_smoke_small.json")

    profs = build_small_scenario()
    print(f"[step4-smoke] {len(profs)} teachers, "
          f"classes={len({c for p in profs.values() for c in p['classi']})}")

    import cpsat_v2_timetable as cv2  # type: ignore
    classes, triples, class_profs = cv2.build_indices(profs)
    t0 = time.time()
    dc_value = cv2.solve_phase_a(
        profs, classes, triples, class_profs,
        time_limit=int(args.time_budget_phase_a),
        workers=2, log=False)
    t_phase_a = time.time() - t0
    print(f"[step4-smoke] Phase A done in {t_phase_a:.1f}s")

    targets = list(args.only) if args.only else list(GRANULARITIES)

    results = {
        "scenario": "step4_smoke_small",
        "n_teachers": len(profs),
        "n_classes": len(classes),
        "n_triples": len(triples),
        "t_phase_a_s": t_phase_a,
        "rows": [],
    }
    for gran in targets:
        print(f"[step4-smoke] BP[{gran}] starting "
              f"(budget {args.time_budget_bp:.0f}s)...")
        row = run_one_granularity(
            profs, dc_value, gran, args.time_budget_bp,
            rf_pricing_in_nodes=True)
        results["rows"].append(row)
        print(f"[step4-smoke] BP[{gran}] -> "
              f"hard={row['hard_feasible']}, "
              f"soft={row['soft_obj_actual']}, "
              f"iters={row['n_iterations']}, "
              f"rf_nodes={row['rf_tree_nodes_explored']}, "
              f"pricing_calls={row['rf_tree_pricing_calls']}, "
              f"reason={row['bp_terminated_reason']!r} "
              f"in {row['t_bp_s']:.1f}s")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"[step4-smoke] wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
