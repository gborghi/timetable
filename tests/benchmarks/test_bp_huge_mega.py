"""HUGE / MEGA-scale BP scalability benchmark.

Runs the full Branch-and-Price pipeline (mode='branch-and-price'
with all 4 scalability techniques: Ryan-Foster recursive tree,
dual stabilization, column management, parallel pricing) on
synthetic scenarios sized to match the real `engine/big_mock_school.py`
HUGE and MEGA profiles, and reports timing + diagnostics.

Both tests are marked `@pytest.mark.very_slow` -- they are NOT
included in the default pytest run. Invoke with:

    cd webui/backend
    python -m pytest ../../tests/benchmarks/test_bp_huge_mega.py \
        -m very_slow -v --tb=short

Two parameterised scales (matching `engine/big_mock_school.py`
PROFILES at margin=0.0):

    - huge: 50 classes / 95 teachers / 4 subject pools
            -- ~200 cattedre, target HARD-feasibility ~5 min
            (the per-teacher load matches engine's HUGE profile).
    - mega: 100 classes / 174 teachers / 4 subject pools
            -- ~400 cattedre, target HARD-feasibility 30 min
            (the user's MEGA acceptance criterion).

The 60-min hard cap is enforced by `time_budget_s = 3600`.

Synthetic scenario design: each (teacher, class) cattedra is
4 hrs/week packed into a single day (full 8-11 block) so the
H1 (consecutive), H2 (starts at 8) and H3 (presence at h=11)
class-day HARD constraints are satisfied by construction.
Teachers are partitioned across 4 subject pools and assigned
classes in CONTIGUOUS blocks (round-robin produces a periodicity
collision -- see commit history). A Latin-square-like rotation
day(class_idx, subject_idx) = (class_idx + subject_idx) % 6 + 1
gives each teacher a different day for each of their classes.

Results are persisted as JSON in
    tests/benchmarks/results/bp_scalability.json
under per-scale keys (huge / mega).
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
ENGINE = os.path.join(ROOT, "engine")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

RESULTS_DIR = Path(HERE) / "results"
RESULTS_PATH = RESULTS_DIR / "bp_scalability.json"


def _build_synthetic_scenario(n_classes: int, n_teachers: int):
    """Build a synthetic HUGE/MEGA-style scenario.

    Calibrated to match `engine/big_mock_school.py` profile sizes:
      - HUGE: 50 classes, ~95 teachers (margin=0.0 produces 89,
        margin=0.05 produces 92; we use 95 as a clean midpoint).
      - MEGA: 100 classes, ~174 teachers (margin=0.0 produces 171,
        margin=0.05 produces 179; we use 174).

      - 4 subject pools (Mat / Ita / Sto / Ing); each pool size =
        n_teachers // 4 (any remainder added to the first pool).
      - Each (teacher, class) cattedra is 4 hrs on a single day
        (full 8-11 block) so H1/H2/H3 hold by construction.
      - Day chosen so no teacher visits two classes on the same
        day, AND each class sees its 4 subjects on 4 different
        days.
    """
    subjects = ["Mat", "Ita", "Sto", "Ing"]
    classes = []
    for ci in range(n_classes):
        year = (ci // 20) + 1   # 1..5
        section = chr(ord("A") + (ci % 20))  # A..T
        classes.append(f"{year}{section}")
    if len(set(classes)) != n_classes:
        classes = [f"C{i:03d}" for i in range(n_classes)]

    # Subject pools: distribute teachers across 4 pools, ensuring
    # each pool has at least ceil(n_classes / 6) teachers so the
    # block-based class assignment never overflows.
    base = max(1, n_teachers // len(subjects))
    extra = n_teachers - base * len(subjects)
    pool_sizes = [base + (1 if i < extra else 0)
                   for i in range(len(subjects))]

    profs: dict = {}
    pools: dict[str, list[str]] = {}
    for si, subj in enumerate(subjects):
        pool = []
        for pi in range(pool_sizes[si]):
            tname = f"T_{subj}_{pi:03d}"
            pool.append(tname)
            profs[tname] = {
                "max_hours": 30,
                "glibero": [6],
                "classi": {},
            }
        pools[subj] = pool

    # Block-based assignment: teacher pi in subject s's pool takes
    # classes [pi*block, ..., (pi+1)*block-1]. Day rotation gives
    # a different day per (teacher, class).
    dc: dict = {}
    for ci, cl in enumerate(classes):
        for si, subj in enumerate(subjects):
            pool = pools[subj]
            block = (n_classes + len(pool) - 1) // len(pool)
            pi = min(ci // max(block, 1), len(pool) - 1)
            tname = pool[pi]
            day = ((ci + si) % 6) + 1
            profs[tname]["classi"][cl] = {subj: {"ore": 4}}
            dc[(tname, cl, subj, day)] = 4

    return profs, dc, classes, list(profs.keys())


def _run_bp_benchmark(scale: str, n_classes: int, n_teachers: int,
                      time_budget_s: float, granularity: str):
    """Run a single scale and persist metrics."""
    import column_generation as cg  # type: ignore

    profs, dc_value, classes, teachers = _build_synthetic_scenario(
        n_classes, n_teachers)

    t0 = time.time()
    sol, info = cg.run_column_generation(
        profs, dc_value,
        time_budget_s=time_budget_s,
        patterns_per_teacher=2,
        max_iterations=2,
        completion_time_limit=60.0,
        completion_workers=4,
        log=True,
        mode="branch-and-price",
        granularity=granularity,
        branching_strategy="ryan_foster",
        bp_max_iterations=3,
        pricer_time_limit=10.0,
        pricer_workers=2,
        dual_stabilization=True,
        dual_step_alpha=0.2,
        max_active_columns=10000,
        rc_smoothing_horizon=20,
        parallel_workers=0,
    )
    t_bp = time.time() - t0

    hard_feasible = bool(
        info.get("feasible_after_assembly")
        or info.get("feasible_after_completion"))
    soft_obj = info.get("master_obj_final")
    n_columns = info.get("bp_dw_n_columns") or info.get(
        "n_patterns_total_final")
    n_iterations = info.get("bp_iterations_done")
    n_rf_nodes = info.get("rf_tree_nodes_explored")
    n_purges = info.get("bp_columns_purged_total", 0)
    workers = info.get("bp_parallel_workers_used", 1)
    bp_term = info.get("bp_terminated_reason")

    metrics = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "scale": scale,
        "n_classes": n_classes,
        "n_teachers": n_teachers,
        "n_cattedre": len(dc_value),
        "granularity": granularity,
        "t_bp_s": float(t_bp),
        "time_budget_s": float(time_budget_s),
        "hard_feasible": hard_feasible,
        "soft_obj": (float(soft_obj) if soft_obj is not None else None),
        "n_columns": (int(n_columns) if n_columns is not None else None),
        "n_iterations": (int(n_iterations)
                          if n_iterations is not None else None),
        "n_rf_nodes_explored": (int(n_rf_nodes)
                                 if n_rf_nodes is not None else None),
        "n_columns_purged": int(n_purges),
        "parallel_workers_used": int(workers),
        "bp_terminated_reason": bp_term,
        "warnings": info.get("warnings", []),
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    all_results: dict = {}
    if RESULTS_PATH.exists():
        try:
            with open(RESULTS_PATH, "r", encoding="utf-8") as f:
                all_results = json.load(f)
        except Exception:
            all_results = {}
    all_results[scale] = metrics
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)

    return hard_feasible, t_bp, metrics


@pytest.mark.very_slow
def test_bp_huge_50_classes():
    """HUGE: 50 classes / ~95 teachers (matches engine's HUGE
    profile, margin=0.05). Target HARD-feasible within 5 min;
    hard cap 10 min."""
    hard_feasible, t_bp, metrics = _run_bp_benchmark(
        scale="huge",
        n_classes=50, n_teachers=95,
        time_budget_s=600.0,
        granularity="curriculum",
    )
    assert hard_feasible, (
        f"BP@huge not HARD-feasible within 600s "
        f"(t_bp={t_bp:.1f}s). Metrics: {metrics}")


@pytest.mark.very_slow
def test_bp_mega_100_classes():
    """MEGA: 100 classes / ~174 teachers (matches engine's MEGA
    profile, margin=0.0-0.05). Target HARD-feasible within 30 min
    (1800s); hard cap 60 min (3600s) -- the user's MEGA acceptance
    criterion."""
    hard_feasible, t_bp, metrics = _run_bp_benchmark(
        scale="mega",
        n_classes=100, n_teachers=174,
        time_budget_s=3600.0,
        granularity="curriculum",
    )
    assert hard_feasible, (
        f"BP@mega not HARD-feasible within 3600s "
        f"(t_bp={t_bp:.1f}s). Metrics: {metrics}")
