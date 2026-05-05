r"""Lagrangian Relaxation with subgradient ascent.

Decomposition strategy:

  - The teacher-class bipartite is partitioned into clusters by
    spectral decomposition (`decomposition_spectral_v2`).
  - "Bridge" edges (teachers/classes shared across clusters) are
    DUALIZED: their corresponding constraints are removed from the
    primal and replaced with multipliers `lambda_b` in the
    objective.
  - Per-cluster CP-SAT subproblems use these multipliers as
    additional cost coefficients.

Subgradient ascent updates:

  lambda_{k+1} = max(0, lambda_k + alpha_k * g_k)

where `g_k` is the violation of the dualized constraint at the
current primal solution, and `alpha_k` follows a diminishing
schedule:  alpha_k = alpha_0 / (1 + k).

This module provides a SKELETON implementation: it identifies
bridges, runs the standard decomposition for the primary
subproblems, computes a single-pass Lagrangian update, and
returns a HARD-feasible solution (or fails over to the standard
decomposition output). The full multi-iteration ascent is left
as future work; the skeleton already exposes all the public
hooks the caller needs.
"""
from __future__ import annotations

import os
import sys
import time
from collections import defaultdict
from typing import Any

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import metaheuristics as meta  # type: ignore[no-redef]  # noqa: E402


def _identify_bridges(profs: dict, classes_clusters: dict[int, set[str]]
                      ) -> list[tuple[str, int, int]]:
    """A 'bridge' here is a (teacher, cluster_a, cluster_b) triple
    where the teacher has students in both clusters."""
    if not classes_clusters:
        return []
    out: list[tuple[str, int, int]] = []
    cluster_of_class: dict[str, int] = {}
    for ci, clset in classes_clusters.items():
        for c in clset:
            cluster_of_class[c] = ci
    for t, info in profs.items():
        teacher_clusters: set[int] = set()
        for cl in (info.get("classi") or {}).keys():
            ci = cluster_of_class.get(cl)
            if ci is not None:
                teacher_clusters.add(ci)
        if len(teacher_clusters) >= 2:
            tc_sorted = sorted(teacher_clusters)
            for i in range(len(tc_sorted)):
                for j in range(i + 1, len(tc_sorted)):
                    out.append((t, tc_sorted[i], tc_sorted[j]))
    return out


def run_lagrangian(sol: dict, profs: dict, dc_value: dict,
                   *, time_budget_s: float = 60.0,
                   max_iter: int = 8,
                   tolerance: float = 1e-2,
                   alpha_0: float = 1.0,
                   classes_clusters: dict[int, set[str]] | None = None,
                   log: bool = True,
                   locks: set | None = None,
                   coteach_groups=None,
                   support_assignments=None,
                   parallel_groups=None,
                   group_assignments=None) -> tuple[dict, dict]:
    """Lagrangian relaxation skeleton.

    The skeleton runs `max_iter` subgradient steps but does NOT
    reformulate the primal each step (which would require touching
    `cpsat_v2_timetable.py`). Instead it tracks lambda values that
    a future full implementation can plug in.

    `locks` (optional): set of (p, cl, s, d, h) tuples that must
    remain at value 1. The inner SA refines under those constraints
    (it filters destroy candidates by lock); the subgradient also
    excludes locked bridge slots, otherwise the multipliers
    diverge against an unmovable floor.

    Returns (best_sol, info).
    """
    t0 = time.time()
    bridges = _identify_bridges(profs, classes_clusters or {})
    info: dict[str, Any] = {
        "kind": "lagrangian",
        "max_iter": max_iter,
        "tolerance": tolerance,
        "alpha_0": alpha_0,
        "n_bridges": len(bridges),
        "iterations": [],
        "duration_s": None,
        "warnings": [],
    }
    if not bridges:
        info["warnings"].append(
            "nessun bridge inter-cluster: la rilassazione e' banale"
        )
        info["duration_s"] = time.time() - t0
        return sol, info

    # Initialise multipliers
    lam = {b: 0.0 for b in bridges}

    best_sol = meta.deepcopy_sol(sol)
    best_val, _ = meta.compute_soft(best_sol, profs)

    # FU-5: when locks are active, the locked slots are IMMOVABLE.
    # The subgradient counts violations the local search could
    # remove; counting locked slots would push the multipliers up
    # against an unmovable floor and diverge. Exclude them from
    # the violation tally.
    if locks:
        n_locked_bridge = sum(
            1 for k_ in locks
            if k_[0] in {b[0] for b in bridges}
        )
        if n_locked_bridge:
            info["warnings"].append(
                f"{n_locked_bridge} locked slots on bridge teachers "
                f"are excluded from the subgradient")

    for k in range(max_iter):
        if time.time() - t0 > time_budget_s:
            info["warnings"].append("time budget exhausted")
            break
        # Subgradient: violation of each bridge's constraint at the
        # current primal. For the SKELETON we use a coarse proxy:
        # count of non-zero bridge teacher slots, EXCLUDING locked
        # ones (they are immovable for SA and would push the
        # multiplier to diverge against a floor).
        violation = {}
        for b in bridges:
            t, ca, cb = b
            cnt = sum(
                1 for k_, v_ in best_sol.items()
                if v_ and k_[0] == t
                and (locks is None or k_ not in locks)
            )
            violation[b] = float(cnt)
        # Update multipliers
        alpha_k = alpha_0 / (1.0 + k)
        max_change = 0.0
        for b, g in violation.items():
            new_lam = max(0.0, lam[b] + alpha_k * g)
            max_change = max(max_change, abs(new_lam - lam[b]))
            lam[b] = new_lam
        # Run a quick local-search refinement at this lambda vector.
        # (In a full impl this would re-build the CP-SAT model with
        # the new lambdas.)
        try:
            refined = meta.run_sa(
                best_sol, profs, dc_value,
                max(2.0, time_budget_s / max(1, max_iter)),
                T0=2.0, alpha=0.97, log=False, locks=locks,
                coteach_groups=coteach_groups,
                support_assignments=support_assignments,
                parallel_groups=parallel_groups,
                group_assignments=group_assignments,
            )
        except Exception:
            refined = best_sol
        v, _ = meta.compute_soft(refined, profs)
        if v < best_val and meta.is_hard_feasible(
                refined, profs, verbose=False,
                group_assignments=group_assignments):
            best_sol = refined
            best_val = v
        info["iterations"].append({
            "k": k,
            "alpha_k": alpha_k,
            "lambda_max": max(lam.values()) if lam else 0.0,
            "lambda_change": max_change,
            "best_val": best_val,
        })
        if max_change < tolerance:
            info["converged_at"] = k
            break

    info["duration_s"] = time.time() - t0
    info["final_best_val"] = best_val
    if log:
        print(f"[Lagrangian] {len(info['iterations'])} iter, "
              f"final obj={best_val} "
              f"in {info['duration_s']:.1f}s")
    return best_sol, info
