"""FU-5 — Lagrangian subgradient is lock-aware.

The Lagrangian implementation is documented as a skeleton: it
identifies bridge teachers across spectral clusters, performs a
subgradient ascent on multipliers, and refines via inner SA. The
multipliers themselves are tracked but do not yet feed back into a
re-formulated primal (that would require restructuring CP-SAT).

What FU-5 verifies:
- The inner SA already honours `locks` (atoms 4-5 of the migration).
- The subgradient computation now EXCLUDES locked slots from the
  per-bridge violation count: if it didn't, the multipliers would
  diverge against an unmovable floor.
- Locks on a bridge teacher are reported as a `warnings` entry so
  the caller has visibility into the skeleton's behaviour.
"""
from __future__ import annotations

import os
import sys

import pytest

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


def test_lagrangian_subgradient_excludes_locked_slots():
    """Drive the subgradient computation directly: with locks on a
    bridge teacher, the violation count must NOT include those
    slots. We compare the violation by inspecting the iterations
    info: with all 4 ProfC slots free vs 2 of them locked, the
    initial violation should be smaller in the locked case."""
    import lagrangian as lag_mod  # type: ignore
    profs, dc_value, sol, cc = _build_initial_sol()

    # Run with no locks: subgradient counts all 4 ProfC slots.
    _, info_noloc = lag_mod.run_lagrangian(
        sol, profs, dc_value,
        time_budget_s=1.0, max_iter=1,
        classes_clusters=cc, log=False, locks=None,
    )
    # The skeleton's `violation` is not exposed directly, but the
    # multipliers reflect it: lambda_max after one step should be
    # alpha_0 * sum_violation (alpha_0 default 1.0).
    lam_max_noloc = info_noloc["iterations"][0]["lambda_max"]

    # Now lock 2 of the 4 ProfC slots: subgradient should count 2
    # less, lambda_max should be smaller.
    locks = {("ProfC", "1A", "Sto", 1, 10),
              ("ProfC", "1A", "Sto", 1, 11)}
    _, info_loc = lag_mod.run_lagrangian(
        sol, profs, dc_value,
        time_budget_s=1.0, max_iter=1,
        classes_clusters=cc, log=False, locks=locks,
    )
    lam_max_loc = info_loc["iterations"][0]["lambda_max"]
    # With 2 fewer counted slots, lambda_max with locks should be
    # strictly smaller than without locks.
    assert lam_max_loc < lam_max_noloc, (
        f"lambda_max should decrease when locks reduce countable "
        f"violations: noloc={lam_max_noloc} loc={lam_max_loc}")
