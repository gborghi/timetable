"""Phase 5 -- BP V1 iteration analysis under different ``dc_value``
sources.

Open question from Phase 3: when ``cp_sat_scope='week'`` runs the
monolithic week solver and Phase A is either skipped or used only as
a soft hint, the resulting day-distribution is NOT enforced as a
hard equality. If we then drive a Branch-and-Price V1 master
(granularity = ``teacher`` / ``teacher-day`` / ``teacher-class`` /
``teacher-class-subject`` / ``teacher-subject``) on top of this
"loose" ``dc_value``, do the cover duals (lambda) become binding
enough to produce more than the single ``no_improving_column``
iteration we observe in the legacy day-mode?

This benchmark answers the question empirically.

Workflow per scenario:

  1. Build a small (~10 classes) and a medium (~25 classes)
     scenario via ``engine.big_mock_school.build_dataset`` +
     ``profs_dict_from_dataset``.
  2. Run ``cv2.solve_phase_a`` -> ``dc_phase_a``. This is the hard
     distribution the legacy day-mode uses.
  3. Run ``MonolithicSolver(scope=None, dc_value=None)`` (= the week
     solver in ``phase_a_mode='skip'`` flavour) -> ``sol_week`` and
     derive ``dc_week`` from the actual placement.
  4. Pretty-print whether ``dc_phase_a == dc_week`` (often yes on
     small scenarios, frequently no on medium ones).
  5. For each of the 5 V1 granularities, run BP twice -- once with
     ``dc_phase_a``, once with ``dc_week`` -- and record:
       - ``bp_iterations_done``
       - ``bp_columns_added_total``
       - ``bp_terminated_reason``
       - ``master_obj_initial`` / ``master_obj_final``
       - ``soft_obj_actual`` (from ``compute_soft`` if HARD-feasible)
  6. Save the matrix to JSON.

Output: ``tests/benchmarks/results/bp_v1_scope_week.json``.

Run with::

    python tests/benchmarks/run_bp_v1_scope_week.py \
        --bp-budget 30 --pricer-time-limit 3 --workers 2

Default budgets are tuned to keep the entire run under ~5 min on a
laptop so it's CI-friendly. The script is NOT marked as a pytest
test -- it's a one-shot harness; the integration coverage lives in
``webui/backend/tests/test_scope_week_integration.py``.
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
for p in (ENGINE, WEBUI, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)


# V1 master granularities -- the ones that key cover constraints on
# (teacher, ...) and therefore exercise the lambda/mu duals tested by
# the iteration-count question. The "class*" / "day" / "curriculum"
# variants belong to V2 master and are explicitly out-of-scope here.
GRANULARITIES_V1 = (
    "teacher",
    "teacher-day",
    "teacher-class",
    "teacher-class-subject",
    "teacher-subject",
)


def _profs_small_3_classes():
    """Hand-built small scenario, 3 classes / 10 cattedre (~36h /
    class). Same shape used by ``test_scope_week_integration.py``."""
    profs: dict = {}
    for cl in ("1A", "1B", "1C"):
        profs[f"TM_{cl}"] = {
            "classi": {cl: {"Matematica": {"ore": 4}}},
            "max_hours": 18,
        }
        profs[f"TI_{cl}"] = {
            "classi": {cl: {"Italiano": {"ore": 4}}},
            "max_hours": 18,
        }
        profs[f"TS_{cl}"] = {
            "classi": {cl: {"Storia": {"ore": 3}}},
            "max_hours": 18,
        }
    profs["TMot"] = {
        "classi": {cl: {"Scienzemotorie": {"ore": 2}}
                    for cl in ("1A", "1B", "1C")},
        "max_hours": 18,
    }
    return profs


def _profs_medium_step4_smoke():
    """4-teacher / 3-class scenario from ``run_small_step4_smoke``.
    Larger per-teacher load (4-5 classes per cattedra) so BP has a
    bigger column-pool to enrich than the small fixture."""
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
                "1A": {"Storia": {"ore": 4}, "Filosofia": {"ore": 4}},
                "1B": {"Storia": {"ore": 4}, "Filosofia": {"ore": 4}},
                "2A": {"Storia": {"ore": 4}, "Filosofia": {"ore": 4}},
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


def _restore_dc_from_solution(sol):
    from collections import defaultdict
    out: dict = defaultdict(int)
    for k, v in sol.items():
        if v != 1:
            continue
        p, cl, subj, d, _h = k
        out[(p, cl, subj, d)] += 1
    return dict(out)


def _normalize_dc(dc):
    """Drop zero entries and return as a sorted dict so two
    ``dc_value`` instances can be compared structurally."""
    return {k: int(v) for k, v in sorted(dc.items()) if v > 0}


def _compare_dc(dc_a: dict, dc_b: dict) -> dict:
    """Return a small diff summary between two ``dc_value`` dicts."""
    a = _normalize_dc(dc_a)
    b = _normalize_dc(dc_b)
    keys_a = set(a.keys())
    keys_b = set(b.keys())
    common = keys_a & keys_b
    diff_keys = sum(1 for k in common if a[k] != b[k])
    return {
        "n_keys_a": len(keys_a),
        "n_keys_b": len(keys_b),
        "n_only_a": len(keys_a - keys_b),
        "n_only_b": len(keys_b - keys_a),
        "n_common_diff": diff_keys,
        "identical": (a == b),
    }


def _phase_a_dc(profs, time_limit_s, workers):
    import cpsat_v2_timetable as cv2  # type: ignore
    classes_v, triples, class_profs = cv2.build_indices(profs)
    return cv2.solve_phase_a(
        profs, classes_v, triples, class_profs,
        time_limit=int(time_limit_s), workers=workers, log=False,
    )


def _week_dc(profs, time_limit_s, workers):
    """Run the week solver in ``phase_a_mode='skip'`` style and
    derive ``dc_value`` from its solution."""
    try:
        from cp_sat_constraint_model import (  # type: ignore
            MonolithicSolver, ConstraintConfig)
    except ImportError:
        from engine.cp_sat_constraint_model import (  # type: ignore
            MonolithicSolver, ConstraintConfig)
    cfg = ConstraintConfig(
        enforce_no_holes=True,
        enforce_h3_presence_at_11=True,
        enforce_motorie_pair=False,
        enforce_math_italian_pair=True,
    )
    ms = MonolithicSolver(profs, dc_value=None, config=cfg, scope=None)
    sol, status = ms.solve(time_limit_s=float(time_limit_s),
                            workers=workers, log=False)
    if sol is None:
        raise RuntimeError(
            f"week solver failed for scenario, status={status}")
    return _restore_dc_from_solution(sol), sol


def _run_bp_v1(profs, dc_value, granularity, *, bp_budget,
               pricer_time_limit, pricer_workers,
               bp_max_iterations):
    import column_generation as cg  # type: ignore
    import metaheuristics as meta  # type: ignore
    t0 = time.time()
    err = None
    sol, info = None, {}
    try:
        sol, info = cg.run_column_generation(
            profs, dc_value,
            time_budget_s=bp_budget,
            patterns_per_teacher=2,
            max_iterations=2,
            completion_time_limit=15.0,
            completion_workers=pricer_workers,
            log=False,
            mode="branch-and-price",
            granularity=granularity,
            branching_strategy="ryan_foster",
            bp_max_iterations=bp_max_iterations,
            pricer_time_limit=pricer_time_limit,
            pricer_workers=pricer_workers,
            dual_stabilization=True,
            dual_step_alpha=0.2,
            max_active_columns=2000,
            rc_smoothing_horizon=10,
            parallel_workers=0,
            rf_pricing_in_nodes=False,  # focus on pure BP iterations
        )
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
        traceback.print_exc()
    t = time.time() - t0
    soft_obj_actual = None
    hard = False
    if sol and meta.is_hard_feasible(sol, profs, verbose=False):
        v, _ = meta.compute_soft(sol, profs)
        soft_obj_actual = float(v)
        hard = True
    return {
        "granularity": granularity,
        "t_bp_s": round(t, 3),
        "hard_feasible": hard,
        "soft_obj_actual": soft_obj_actual,
        "bp_iterations_done": info.get("bp_iterations_done"),
        "bp_columns_added_total": info.get("bp_columns_added_total"),
        "bp_terminated_reason": info.get("bp_terminated_reason"),
        "master_obj_initial": info.get("master_obj_initial"),
        "master_obj_final": info.get("master_obj_final"),
        "n_patterns_total_initial": info.get("n_patterns_total_initial"),
        "n_patterns_total_final": info.get("n_patterns_total_final"),
        "exception": err,
    }


def run_scenario(name, build_fn, *, phase_a_budget, week_budget,
                 bp_budget, pricer_time_limit, pricer_workers,
                 bp_max_iterations, granularities):
    print(f"\n[bp-v1-week] === scenario {name!r} ===")
    profs = build_fn()
    n_teachers = len(profs)
    n_classes = len({c for p in profs.values() for c in p["classi"]})
    n_cattedre = sum(len(p["classi"]) for p in profs.values())
    print(f"[bp-v1-week] {n_teachers} teachers, {n_classes} classes, "
          f"~{n_cattedre} cattedre")

    t0 = time.time()
    dc_phase_a = _phase_a_dc(profs, phase_a_budget, pricer_workers)
    t_phase_a = time.time() - t0
    print(f"[bp-v1-week] Phase A: {t_phase_a:.1f}s, "
          f"{sum(1 for v in dc_phase_a.values() if v > 0)} non-zero entries")

    t0 = time.time()
    dc_week, _sol_week = _week_dc(profs, week_budget, pricer_workers)
    t_week = time.time() - t0
    print(f"[bp-v1-week] Week solver: {t_week:.1f}s, "
          f"{sum(1 for v in dc_week.values() if v > 0)} non-zero entries")

    diff = _compare_dc(dc_phase_a, dc_week)
    print(f"[bp-v1-week] dc_phase_a vs dc_week: {diff}")

    rows: list[dict] = []
    for gran in granularities:
        for src_label, dc in (("phase_a", dc_phase_a),
                                ("week", dc_week)):
            print(f"[bp-v1-week] BP[{gran}, dc={src_label}] starting...")
            row = _run_bp_v1(
                profs, dc, gran,
                bp_budget=bp_budget,
                pricer_time_limit=pricer_time_limit,
                pricer_workers=pricer_workers,
                bp_max_iterations=bp_max_iterations,
            )
            row["dc_source"] = src_label
            row["scenario"] = name
            rows.append(row)
            print(f"[bp-v1-week] BP[{gran}, dc={src_label}] -> "
                  f"hard={row['hard_feasible']}, "
                  f"iters={row['bp_iterations_done']}, "
                  f"cols={row['bp_columns_added_total']}, "
                  f"reason={row['bp_terminated_reason']!r}, "
                  f"t={row['t_bp_s']}s")

    return {
        "scenario": name,
        "n_teachers": n_teachers,
        "n_classes": n_classes,
        "n_cattedre": n_cattedre,
        "t_phase_a_s": round(t_phase_a, 3),
        "t_week_s": round(t_week, 3),
        "dc_phase_a_vs_week_diff": diff,
        "rows": rows,
    }


def summarize(out: dict) -> dict:
    """Compact per-(scenario, granularity, dc_source) summary suited
    for the user-manual write-up."""
    summary = []
    for sc in out["scenarios"]:
        for r in sc["rows"]:
            summary.append({
                "scenario": sc["scenario"],
                "granularity": r["granularity"],
                "dc_source": r["dc_source"],
                "iters": r["bp_iterations_done"],
                "cols_added": r["bp_columns_added_total"],
                "terminated": r["bp_terminated_reason"],
                "soft": r["soft_obj_actual"],
                "hard": r["hard_feasible"],
                "t_s": r["t_bp_s"],
            })
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase-a-budget", type=float, default=10.0)
    ap.add_argument("--week-budget", type=float, default=30.0)
    ap.add_argument("--bp-budget", type=float, default=30.0)
    ap.add_argument("--pricer-time-limit", type=float, default=3.0)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--bp-max-iter", type=int, default=5)
    ap.add_argument("--only", nargs="*", default=None,
                     help="restrict to a subset of granularities")
    ap.add_argument("--results-file", default=None)
    args = ap.parse_args()

    granularities = (tuple(args.only) if args.only
                      else GRANULARITIES_V1)
    out_dir = Path(HERE) / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.results_file
                     or out_dir / "bp_v1_scope_week.json")

    scenarios_data = []
    for (name, build_fn) in [
        ("small", _profs_small_3_classes),
        ("medium", _profs_medium_step4_smoke),
    ]:
        try:
            sc = run_scenario(
                name, build_fn,
                phase_a_budget=args.phase_a_budget,
                week_budget=args.week_budget,
                bp_budget=args.bp_budget,
                pricer_time_limit=args.pricer_time_limit,
                pricer_workers=args.workers,
                bp_max_iterations=args.bp_max_iter,
                granularities=granularities,
            )
            scenarios_data.append(sc)
        except Exception as e:  # noqa: BLE001
            print(f"[bp-v1-week] scenario {name} failed: "
                  f"{type(e).__name__}: {e}")
            traceback.print_exc()

    out = {
        "kind": "bp_v1_scope_week",
        "phase_a_budget_s": args.phase_a_budget,
        "week_budget_s": args.week_budget,
        "bp_budget_s": args.bp_budget,
        "bp_max_iterations": args.bp_max_iter,
        "pricer_time_limit_s": args.pricer_time_limit,
        "workers": args.workers,
        "granularities": list(granularities),
        "scenarios": scenarios_data,
    }
    out["summary"] = summarize(out)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"\n[bp-v1-week] wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
