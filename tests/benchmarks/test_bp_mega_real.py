"""Real-MEGA BP scalability benchmark.

Loads the canonical MEGA dataset from
``engine/scripts/data/mega/profs_mega.pkl`` (100 classes, 178
teachers, weekly demand close to 3000 hours) and runs:

  - Phase A (cv2.solve_phase_a) to derive dc_value.
  - The full Branch-and-Price pipeline (mode='branch-and-price'
    with all 4 scalability techniques) at granularity='curriculum'.
  - The iterative-diversified mode for comparison baseline.

Both are marked @pytest.mark.very_slow.

    cd webui/backend
    python -m pytest \
        ../../tests/benchmarks/test_bp_mega_real.py \
        -m very_slow -v --tb=short

Target:
  Phase A wall <= 600s
  BP wall      <= 1800s (target) / 3600s (hard cap)
  Iterative wall is for comparison only -- no pass/fail criterion.

Results are persisted in
    tests/benchmarks/results/mega_bp_real.json
"""
from __future__ import annotations

import json
import os
import pickle
import sys
import time
from pathlib import Path

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
ENGINE = os.path.join(ROOT, "engine")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

PROFS_PKL = os.path.join(ROOT, "engine", "scripts", "data", "mega",
                          "profs_mega.pkl")
SCHOOL_PKL = os.path.join(ROOT, "engine", "scripts", "data", "mega",
                           "school_mega.pkl")
RESULTS = Path(HERE) / "results" / "mega_bp_real.json"


def _load_real_mega():
    """Load the canonical MEGA profs + school dicts. Skips the
    test if the pickles are missing (e.g. fresh checkout)."""
    if not os.path.exists(PROFS_PKL) or not os.path.exists(SCHOOL_PKL):
        pytest.skip(
            f"missing real MEGA pickles "
            f"(expected {PROFS_PKL} and {SCHOOL_PKL})")
    with open(PROFS_PKL, "rb") as f:
        profs = pickle.load(f)
    with open(SCHOOL_PKL, "rb") as f:
        school = pickle.load(f)
    return profs, school


def _run_phase_a(profs: dict, time_limit_s: float = 600.0):
    """Run Phase A on the real MEGA profs to derive dc_value."""
    import cpsat_v2_timetable as cv2  # type: ignore
    classes_v, triples, class_profs = cv2.build_indices(profs)
    dc_value = cv2.solve_phase_a(
        profs, classes_v, triples, class_profs,
        time_limit=int(time_limit_s),
        workers=4, log=False,
    )
    return dc_value


def _persist(scale: str, metrics: dict):
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    all_results: dict = {}
    if RESULTS.exists():
        try:
            with open(RESULTS, "r", encoding="utf-8") as f:
                all_results = json.load(f)
        except Exception:
            all_results = {}
    all_results[scale] = metrics
    with open(RESULTS, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)


@pytest.mark.very_slow
def test_bp_mega_real_branch_and_price():
    """Run BP with all scalability techniques on the real MEGA
    dataset. Hard cap 60 minutes; target 30 minutes."""
    import column_generation as cg  # type: ignore

    profs, school = _load_real_mega()
    n_classes = len(school.get("classes", []))
    n_teachers = len(profs)
    print(f"[mega-real] {n_classes} classes / {n_teachers} teachers")

    t0_a = time.time()
    dc_value = _run_phase_a(profs, time_limit_s=300.0)
    t_phase_a = time.time() - t0_a
    if dc_value is None:
        pytest.skip(
            f"Phase A on real MEGA returned None within 300s; "
            f"this benchmark assumes Phase A completes first")
    print(f"[mega-real] Phase A: {t_phase_a:.1f}s")

    t0_bp = time.time()
    sol, info = cg.run_column_generation(
        profs, dc_value,
        time_budget_s=3600.0,
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
    t_bp = time.time() - t0_bp
    t_total = t_phase_a + t_bp

    hard = bool(info.get("feasible_after_assembly")
                or info.get("feasible_after_completion"))
    metrics = {
        "scenario": "mega_real",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "n_classes": n_classes,
        "n_teachers": n_teachers,
        "n_cattedre": len([k for k, v in dc_value.items()
                            if isinstance(k, tuple) and len(k) == 4
                            and v > 0]),
        "mode": "branch-and-price",
        "granularity": "curriculum",
        "t_phase_a_s": float(t_phase_a),
        "t_bp_s": float(t_bp),
        "t_total_s": float(t_total),
        "target_total_s": 1800.0,
        "hard_cap_total_s": 3600.0,
        "within_target": bool(t_total <= 1800.0),
        "within_hard_cap": bool(t_total <= 3600.0),
        "hard_feasible": hard,
        "soft_obj": info.get("master_obj_final"),
        "n_columns": (info.get("bp_dw_n_columns")
                       or info.get("n_patterns_total_final")),
        "n_iterations": info.get("bp_iterations_done"),
        "n_rf_nodes_explored": info.get("rf_tree_nodes_explored"),
        "n_columns_purged": info.get("bp_columns_purged_total", 0),
        "parallel_workers_used": info.get(
            "bp_parallel_workers_used", 1),
        "bp_terminated_reason": info.get("bp_terminated_reason"),
        "warnings": info.get("warnings", []),
    }
    _persist("mega_real_bp", metrics)
    assert t_total <= 3600.0, (
        f"BP@mega_real exceeded hard cap 3600s "
        f"(actual: {t_total:.1f}s). See {RESULTS}.")
    assert hard, (
        f"BP@mega_real did not produce HARD-feasible solution. "
        f"Warnings: {info.get('warnings')}. See {RESULTS}.")


@pytest.mark.very_slow
def test_bp_mega_real_iterative_diversified_baseline():
    """Iterative-diversified baseline on real MEGA for comparison
    with the BP run."""
    import column_generation as cg  # type: ignore

    profs, school = _load_real_mega()
    n_classes = len(school.get("classes", []))
    n_teachers = len(profs)

    t0_a = time.time()
    dc_value = _run_phase_a(profs, time_limit_s=300.0)
    t_phase_a = time.time() - t0_a
    if dc_value is None:
        pytest.skip(
            "Phase A on real MEGA returned None within 300s")

    t0 = time.time()
    sol, info = cg.run_column_generation(
        profs, dc_value,
        time_budget_s=1800.0,
        patterns_per_teacher=3,
        max_iterations=5,
        completion_time_limit=120.0,
        completion_workers=4,
        log=True,
        mode="iterative-diversified",
    )
    t_id = time.time() - t0
    hard = bool(info.get("feasible_after_assembly")
                or info.get("feasible_after_completion"))

    metrics = {
        "scenario": "mega_real",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "n_classes": n_classes,
        "n_teachers": n_teachers,
        "mode": "iterative-diversified",
        "t_phase_a_s": float(t_phase_a),
        "t_id_s": float(t_id),
        "t_total_s": float(t_phase_a + t_id),
        "hard_feasible": hard,
        "soft_obj": info.get("master_obj_final"),
        "warnings": info.get("warnings", []),
    }
    _persist("mega_real_id", metrics)
    assert hard, (
        f"iterative-diversified@mega_real not HARD-feasible. "
        f"Warnings: {info.get('warnings')}. See {RESULTS}.")
