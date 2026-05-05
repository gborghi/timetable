"""MEGA-scale BP scalability benchmark.

Runs the full Branch-and-Price pipeline (mode='branch-and-price'
with all 4 scalability techniques: Ryan-Foster recursive tree,
dual stabilization, column management, parallel pricing) on a
synthetic large scenario and reports timing + diagnostics.

The test is marked `@pytest.mark.very_slow` -- it is NOT included
in the default pytest run. Invoke with:

    cd webui/backend
    python -m pytest ../../tests/benchmarks/test_bp_mega.py \
        -m very_slow -v --tb=short

Two parameterized scales:
    - mega_50: 50 classes / 50 teachers / 4 subjects each
               -- ~600 cattedre, target HARD-feasibility ~5 min
    - mega_100: 100 classes / 100 teachers / 4 subjects each
                -- ~1600 cattedre, target HARD-feasibility ~30 min
                (the user's MEGA acceptance criterion).
The 60-min hard cap is enforced by pytest's time_budget_s = 3600.

Synthetic scenario design: each (teacher, class) cattedra is 4
hrs/week packed into a single day (full 8-11 block) -- the H1/
H2/H3 class-day HARD constraints are satisfied by construction.
A Latin-square-like rotation distributes teachers across days.

Results are persisted as JSON in
    tests/benchmarks/results/mega_bp.json
with keys: timestamp, scale, n_classes, n_teachers, t_bp_s,
hard_feasible, soft_obj, n_columns, n_iterations, n_rf_nodes,
n_purges, parallel_workers_used, bp_terminated_reason.
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
RESULTS_PATH = RESULTS_DIR / "mega_bp.json"


def _build_synthetic_mega(n_classes: int, n_teachers: int):
    """Build a synthetic MEGA-style scenario.

      - n_classes uniquely-named classes
      - n_teachers teachers spread over 4 subjects (Mat / Ita /
        Sto / Ing)
      - Each subject is taught in EVERY class
      - The teachers-per-subject pool is sized so each teacher's
        load is at most max_hours.
      - Each (teacher, class) cattedra is 4 hrs/week packed into a
        single day (full 8-11 block) so H1/H2/H3 (consecutive,
        starts at 8, presence at h=11) hold by construction.
      - Day for (teacher, class) is chosen so no teacher visits
        two classes on the same day.
    """
    subjects = ["Mat", "Ita", "Sto", "Ing"]
    # Class names: 1A..5T tries to mimic Italian school sections.
    classes = []
    for ci in range(n_classes):
        year = (ci // 20) + 1   # 1..5
        section = chr(ord("A") + (ci % 20))  # A..T
        classes.append(f"{year}{section}")
    if len(set(classes)) != n_classes:
        classes = [f"C{i:03d}" for i in range(n_classes)]

    # Each subject has a pool of teachers; each class needs exactly
    # ONE teacher per subject. Pool size for each subject = ceil(
    # n_teachers / 4). Round-robin: class ci's subject-s teacher
    # is teacher_id_in_pool = ci % pool_size.
    teachers_per_subject = max(1, n_teachers // len(subjects))
    profs: dict = {}
    dc: dict = {}
    # Generate teacher names per subject pool.
    pools: dict[str, list[str]] = {}
    for si, subj in enumerate(subjects):
        pool = []
        for pi in range(teachers_per_subject):
            tname = f"T_{subj}_{pi:03d}"
            pool.append(tname)
            profs[tname] = {
                "max_hours": 30,  # generous in the synthetic
                "glibero": [6],
                "classi": {},
            }
        pools[subj] = pool

    # Assign each (class, subject) to a teacher in the pool by
    # CONTIGUOUS BLOCKS (not round-robin): teacher pi in subject s's
    # pool takes classes [pi*block, ..., (pi+1)*block-1]. This way
    # each teacher's classes are at consecutive indices, so the
    # day rotation `(ci + si) % 6 + 1` gives a different day for
    # every (teacher, class) pair (provided block <= 6, which holds
    # whenever pool_size >= n_classes / 6).
    #
    # Round-robin assignment caused a periodicity bug: with
    # pool_size = n_teachers // 4 and n_classes a multiple of 12,
    # every teacher's classes shared the same `ci % 6`, packing
    # them all onto the SAME day -- master LP infeasible.
    for ci, cl in enumerate(classes):
        for si, subj in enumerate(subjects):
            pool = pools[subj]
            block = (n_classes + len(pool) - 1) // len(pool)
            pi = min(ci // max(block, 1), len(pool) - 1)
            tname = pool[pi]
            # Day for this (class, subject): 1..6 with rotation by
            # subject so each class sees its 4 subjects on
            # 4 different days.
            day = ((ci + si) % 6) + 1
            profs[tname]["classi"][cl] = {subj: {"ore": 4}}
            dc[(tname, cl, subj, day)] = 4

    return profs, dc, classes, list(profs.keys())


def _run_bp_benchmark(scale: str, n_classes: int, n_teachers: int,
                      time_budget_s: float, granularity: str):
    """Run a single benchmark scale and persist metrics."""
    import column_generation as cg  # type: ignore

    profs, dc_value, classes, teachers = _build_synthetic_mega(
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
        max_active_columns=5000,
        rc_smoothing_horizon=20,
        parallel_workers=0,  # auto -> cpu_count // 2
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
    # Append-or-update under a "scale" key in the JSON file.
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
def test_bp_mega_synthetic_50_classes():
    """Synthetic 50-class / 50-teacher BP run. Target: HARD-feasible
    within 5 min (300s); hard cap 10 min (600s)."""
    hard_feasible, t_bp, metrics = _run_bp_benchmark(
        scale="mega_50",
        n_classes=50, n_teachers=50,
        time_budget_s=600.0,
        granularity="curriculum",
    )
    assert hard_feasible, (
        f"BP@mega_50 not HARD-feasible within 600s "
        f"(t_bp={t_bp:.1f}s). Metrics: {metrics}")


@pytest.mark.very_slow
def test_bp_mega_synthetic_100_classes():
    """Synthetic 100-class / 100-teacher BP run -- the MEGA
    acceptance criterion. Target 30 min (1800s); hard cap 60 min
    (3600s)."""
    hard_feasible, t_bp, metrics = _run_bp_benchmark(
        scale="mega_100",
        n_classes=100, n_teachers=100,
        time_budget_s=3600.0,
        granularity="curriculum",
    )
    assert hard_feasible, (
        f"BP@mega_100 not HARD-feasible within 3600s "
        f"(t_bp={t_bp:.1f}s). Metrics: {metrics}")
