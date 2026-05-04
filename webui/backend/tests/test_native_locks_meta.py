"""Atom 4-5 — native lock support in metaheuristics + ALNS + VNS +
Lagrangian.

Tests that the atomic moves and the runner functions accept a
`locks` set and honour it: the locked keys are never moved.
"""
from __future__ import annotations

import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(HERE)
WEBUI_DIR = os.path.dirname(BACKEND_DIR)
REPO_ROOT = os.path.dirname(WEBUI_DIR)
ENGINE_DIR = os.path.join(REPO_ROOT, "engine")
for p in (WEBUI_DIR, ENGINE_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


def _build_feasible_sol():
    """Build a small profs+sol pair that is HARD-feasible.

    1A has 8 weekly hours: ProfA-Mat 4 + ProfB-Ita 4. The schedule
    places everything on Monday (8..12) using a 5+ pattern... wait,
    cl_day_load constraint requires 4..6. Use 4 hours each day for 2
    days. Day 1 (Mon): 4h. Day 2 (Tue): 4h.
    """
    profs = {
        "ProfA": {
            "classi": {"1A": {"Mat": {"ore": 4}}},
            "glibero": [6, 5, 4],
        },
        "ProfB": {
            "classi": {"1A": {"Ita": {"ore": 4}}},
            "glibero": [6, 5, 4],
        },
    }
    # cl_day_load(1A, day=1) = 4, day=2 = 4 (matches {0,4,5,6}).
    # ProfA-Mat: 2h day1, 2h day2. ProfB-Ita: 2h day1, 2h day2.
    sol = {}
    for d in [1, 2]:
        for h_idx, h in enumerate([8, 9]):
            sol[("ProfA", "1A", "Mat", d, h)] = 1
        for h_idx, h in enumerate([10, 11]):
            sol[("ProfB", "1A", "Ita", d, h)] = 1
    # Fill 0s for the rest of the slot space (some functions iterate)
    for p in ["ProfA", "ProfB"]:
        for cl in ["1A"]:
            for s in (["Mat"] if p == "ProfA" else ["Ita"]):
                for d in range(1, 7):
                    for h in range(8, 14):
                        sol.setdefault((p, cl, s, d, h), 0)
    dc_value = {
        ("ProfA", "1A", "Mat", 1): 2,
        ("ProfA", "1A", "Mat", 2): 2,
        ("ProfB", "1A", "Ita", 1): 2,
        ("ProfB", "1A", "Ita", 2): 2,
    }
    return profs, sol, dc_value


def test_atomic_move_rejects_lock_swap_same_prof():
    import metaheuristics as meta  # type: ignore
    profs, sol, dc_value = _build_feasible_sol()
    locked = {("ProfA", "1A", "Mat", 1, 8)}
    rng = random.Random(0)
    # Force the move to try ProfA-day=1 by limiting choices: with
    # only 2 lessons of ProfA on day 1, the rng will pick them. We
    # try multiple times; locked key must never be moved.
    for _ in range(50):
        new_sol = meta._swap_two_lessons_same_prof(
            sol, profs, dc_value, rng, locks=locked)
        if new_sol is None:
            continue
        # Locked slot must still be 1.
        assert new_sol[("ProfA", "1A", "Mat", 1, 8)] == 1


def test_run_sa_does_not_move_locked():
    import metaheuristics as meta  # type: ignore
    profs, sol, dc_value = _build_feasible_sol()
    locked = {("ProfA", "1A", "Mat", 1, 8),
              ("ProfA", "1A", "Mat", 1, 9)}
    new_sol = meta.run_sa(sol, profs, dc_value, time_budget_s=1.5,
                           T0=5.0, alpha=0.99, log=False,
                           locks=locked)
    for k in locked:
        assert new_sol[k] == 1, f"SA moved locked key {k}"


def test_run_alns_does_not_free_locked():
    import alns as alns_mod  # type: ignore
    profs, sol, dc_value = _build_feasible_sol()
    locked = {("ProfA", "1A", "Mat", 1, 8),
              ("ProfB", "1A", "Ita", 2, 11)}
    new_sol, _hist = alns_mod.run_alns(
        sol, profs, dc_value, time_budget_s=2.0,
        log=False, workers=2, T0=2.0, alpha=0.99,
        locks=locked,
    )
    for k in locked:
        assert new_sol[k] == 1, f"ALNS moved locked key {k}"


def test_run_vns_does_not_move_locked():
    import vns as vns_mod  # type: ignore
    profs, sol, dc_value = _build_feasible_sol()
    locked = {("ProfA", "1A", "Mat", 1, 8)}
    new_sol, _hist = vns_mod.run_vns(
        sol, profs, dc_value, time_budget_s=1.5,
        log=False, locks=locked,
    )
    for k in locked:
        assert new_sol[k] == 1, f"VNS moved locked key {k}"


def test_run_lagrangian_inherits_locks_via_sa():
    import lagrangian as lag_mod  # type: ignore
    profs, sol, dc_value = _build_feasible_sol()
    locked = {("ProfA", "1A", "Mat", 1, 8)}
    new_sol, _info = lag_mod.run_lagrangian(
        sol, profs, dc_value, time_budget_s=2.0,
        max_iter=3, log=False, locks=locked,
    )
    for k in locked:
        assert new_sol[k] == 1, f"Lagrangian moved locked key {k}"
