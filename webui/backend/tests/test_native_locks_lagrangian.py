"""Lagrangian subgradient: genuine bridge-coupling relaxation, lock-aware.

``run_lagrangian`` dualizes the cross-cluster bridge-teacher no-overlap
coupling and PRICES it into each cluster's per-day CP objective
(``solve_phase_b_for_day(..., lagrangian_penalties=...)``), so the
multipliers genuinely steer where a bridge teacher's hours land. The
subgradient is the real cross-cluster collision count; ascent drives it to
a collision-free, HARD-feasible assembly.

What this verifies:
- Locks on a bridge teacher are pinned natively in their cluster (the CP
  solve receives them as ``locked_slots_for_day``) and therefore SURVIVE,
  and the caller is told via a ``warnings`` entry.
- The ascent actually resolves a genuine same-day bridge collision: it sees
  the collision (``n_collisions > 0``), raises the multiplier
  (``lambda_max > 0``), and converges to a collision-free feasible day.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(HERE)
WEBUI_DIR = os.path.dirname(BACKEND_DIR)
REPO_ROOT = os.path.dirname(WEBUI_DIR)
ENGINE_DIR = os.path.join(REPO_ROOT, "engine")
for p in (WEBUI_DIR, ENGINE_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


def _make_two_cluster_school():
    """3 profs, 2 classes (1A in cluster 0, 1B in cluster 1).
    ProfA insegna SOLO 1A (no bridge). ProfB insegna SOLO 1B
    (no bridge). ProfC insegna sia 1A che 1B (bridge). The
    Lagrangian will identify ProfC as the lone bridge teacher."""
    profs = {
        "ProfA": {
            "classi": {"1A": {"Mat": {"ore": 4}}},
            "glibero": [6, 5, 4],
        },
        "ProfB": {
            "classi": {"1B": {"Ita": {"ore": 4}}},
            "glibero": [6, 5, 4],
        },
        "ProfC": {
            "classi": {"1A": {"Sto": {"ore": 2}},
                        "1B": {"Sto": {"ore": 2}}},
            "glibero": [6, 5, 4],
        },
    }
    classes_clusters = {0: {"1A"}, 1: {"1B"}}
    return profs, classes_clusters


def _build_initial_sol():
    """A simple HARD-feasible scaffold: all-zero baseline with the
    needed slots set to 1. Enough to make compute_soft / SA happy
    on a quick invocation."""
    profs, classes_clusters = _make_two_cluster_school()
    sol = {}
    for d in [1, 2]:
        for h in [8, 9]:
            sol[("ProfA", "1A", "Mat", d, h)] = 1
            sol[("ProfB", "1B", "Ita", d, h)] = 1
    sol[("ProfC", "1A", "Sto", 1, 10)] = 1
    sol[("ProfC", "1A", "Sto", 1, 11)] = 1
    sol[("ProfC", "1B", "Sto", 2, 10)] = 1
    sol[("ProfC", "1B", "Sto", 2, 11)] = 1
    # Pad zeros for the iteration-friendly ones.
    for p in ["ProfA", "ProfB", "ProfC"]:
        for cl in ["1A", "1B"]:
            for s in ["Mat", "Ita", "Sto"]:
                for d in range(1, 7):
                    for h in range(8, 14):
                        sol.setdefault((p, cl, s, d, h), 0)
    dc_value = {
        ("ProfA", "1A", "Mat", 1): 2,
        ("ProfA", "1A", "Mat", 2): 2,
        ("ProfB", "1B", "Ita", 1): 2,
        ("ProfB", "1B", "Ita", 2): 2,
        ("ProfC", "1A", "Sto", 1): 2,
        ("ProfC", "1B", "Sto", 2): 2,
    }
    return profs, dc_value, sol, classes_clusters


def test_lagrangian_locks_on_bridge_teacher_survive():
    """Lock 2 ProfC slots (the bridge teacher) and verify they are
    intact after Lagrangian SA refinement."""
    import lagrangian as lag_mod  # type: ignore
    profs, dc_value, sol, cc = _build_initial_sol()
    locks = {("ProfC", "1A", "Sto", 1, 10),
              ("ProfC", "1A", "Sto", 1, 11)}
    new_sol, info = lag_mod.run_lagrangian(
        sol, profs, dc_value,
        time_budget_s=2.0, max_iter=2,
        classes_clusters=cc, log=False,
        locks=locks,
    )
    for k in locks:
        assert new_sol[k] == 1, f"locked bridge slot {k} was moved"
    # The skeleton must record the bridge-lock note in warnings.
    assert any("bridge teachers" in w for w in info["warnings"]), (
        f"missing bridge-lock warning in info['warnings']: "
        f"{info['warnings']}")


def _collision_school():
    """Bridge teacher ProfC teaches 1A (cluster 0) AND 1B (cluster 1) with
    hours on the SAME day -- so solving the clusters independently WILL
    double-book ProfC unless the multipliers push them to disjoint hours."""
    profs = {
        "ProfC": {
            "classi": {"1A": {"Sto": {"ore": 2}},
                        "1B": {"Sto": {"ore": 2}}},
            "min_free_days": 0,
        },
    }
    dc_value = {("ProfC", "1A", "Sto", 1): 2,
                ("ProfC", "1B", "Sto", 1): 2}
    classes_clusters = {0: {"1A"}, 1: {"1B"}}
    class_flags = {c: {"entry_at_8": False, "no_holes": False,
                       "exit_after_12": False} for c in ("1A", "1B")}
    # A deliberately COLLIDING seed: ProfC in both classes at 8,9.
    sol = {("ProfC", "1A", "Sto", 1, 8): 1, ("ProfC", "1A", "Sto", 1, 9): 1,
           ("ProfC", "1B", "Sto", 1, 8): 1, ("ProfC", "1B", "Sto", 1, 9): 1}
    return profs, dc_value, sol, classes_clusters, class_flags


def test_lagrangian_subgradient_resolves_bridge_collision():
    """The multipliers genuinely drive the primal: a same-day bridge
    collision is SEEN by the subgradient, raises the multiplier, and is
    resolved into a collision-free, HARD-feasible day (the pre-fix skeleton
    tracked lambda but never fed it back, so it could not do this)."""
    import lagrangian as lag_mod  # type: ignore
    import metaheuristics as meta  # type: ignore
    profs, dc_value, sol, cc, cf = _collision_school()

    # The colliding seed is not even hard-feasible (ProfC double-booked).
    assert meta.is_hard_feasible(sol, profs, class_flags=cf) is False

    out, info = lag_mod.run_lagrangian(
        sol, profs, dc_value,
        time_budget_s=30.0, max_iter=8,
        classes_clusters=cc, class_flags=cf, log=False,
    )
    assert info["n_bridges"] == 1
    # Day 1 saw a real collision and the multiplier rose above zero.
    day1 = [it for it in info["iterations"] if it["day"] == 1]
    assert day1, "no day-1 ascent recorded"
    assert day1[0]["n_collisions"] > 0, "the same-day bridge clash was missed"
    assert max(it["lambda_max"] for it in day1) > 0, "lambda never rose"
    # It converged and the reconstruction is accepted + hard-feasible.
    assert 1 in info["converged_days"]
    assert info["accepted"] is True
    assert meta.is_hard_feasible(out, profs, class_flags=cf) is True
    # ProfC no longer double-booked: at most one class per (day, hour).
    busy = {}
    for (p, cl, s, d, h), v in out.items():
        if v and p == "ProfC":
            busy.setdefault((d, h), set()).add(cl)
    assert all(len(cls) == 1 for cls in busy.values()), busy


def test_lagrangian_dual_bound_is_reported():
    """A genuine relaxation exposes a Lagrangian dual bound (a lower bound on
    the soft objective under the coupling) -- the skeleton never did."""
    import lagrangian as lag_mod  # type: ignore
    profs, dc_value, sol, cc, cf = _collision_school()
    _out, info = lag_mod.run_lagrangian(
        sol, profs, dc_value,
        time_budget_s=30.0, max_iter=8,
        classes_clusters=cc, class_flags=cf, log=False,
    )
    assert info["dual_bound"] is not None
    assert isinstance(info["dual_bound"], (int, float))
