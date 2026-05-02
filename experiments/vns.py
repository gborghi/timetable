r"""Variable Neighborhood Search.

Systematic intensification: cycle through neighbourhoods of
INCREASING size (1-swap, 2-swap, 3-chain, k-opt). For each
neighbourhood, explore exhaustively up to a budget; the moment a
strictly improving move is found we accept it and restart from
neighbourhood 1. When the entire cycle 1..K passes without any
improvement, the search stops.

This is the canonical VNS schema (Mladenovic & Hansen, 1997).

The neighbourhoods reuse `metaheuristics`'s atomic feasibility
checks so a VNS move never breaks HARD constraints.
"""
from __future__ import annotations

import os
import random
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import metaheuristics as meta  # type: ignore[no-redef]  # noqa: E402

DAYS = meta.DAYS
HOURS = meta.HOURS


# ---------------- Neighbourhood 1: single swap ----------------

def _n1_one_swap(sol, profs, dc_value, rng, budget_iter: int,
                 best_val: float):
    """Try up to `budget_iter` 1-swaps of the same prof. Returns the
    first strictly-improving feasible neighbour, else None."""
    for _ in range(budget_iter):
        new_sol = meta._swap_two_lessons_same_prof(sol, profs,
                                                    dc_value, rng)
        if new_sol is None:
            continue
        v, _ = meta.compute_soft(new_sol, profs)
        if v < best_val:
            return new_sol, v
    return None, best_val


# ---------------- Neighbourhood 2: two paired swaps ----------------

def _n2_two_swaps(sol, profs, dc_value, rng, budget_iter: int,
                  best_val: float):
    for _ in range(budget_iter):
        s1 = meta._swap_two_lessons_same_prof(sol, profs, dc_value, rng)
        if s1 is None:
            continue
        s2 = meta._swap_two_lessons_same_class(s1, profs, dc_value, rng)
        candidate = s2 if s2 is not None else s1
        v, _ = meta.compute_soft(candidate, profs)
        if v < best_val:
            return candidate, v
    return None, best_val


# ---------------- Neighbourhood 3: 3-chain ----------------

def _n3_three_chain(sol, profs, dc_value, rng, budget_iter: int,
                    best_val: float):
    """Compose 3 atomic moves; accept if the chain end is strictly
    better. The intermediate states need NOT be improving."""
    for _ in range(budget_iter):
        a = meta._move_lesson_to_empty_slot(sol, profs, dc_value, rng)
        if a is None:
            continue
        b = meta._swap_two_lessons_same_prof(a, profs, dc_value, rng)
        if b is None:
            continue
        c = meta._swap_two_lessons_same_class(b, profs, dc_value, rng)
        candidate = c if c is not None else b
        v, _ = meta.compute_soft(candidate, profs)
        if v < best_val:
            return candidate, v
    return None, best_val


# ---------------- Neighbourhood 4: k-opt (k = 4..6) ----------------

def _nk_kopt(sol, profs, dc_value, rng, budget_iter: int,
             best_val: float, k_min: int = 4, k_max: int = 6):
    """k-opt is a chain of k atomic moves with k randomly chosen in
    [k_min, k_max]. Exposed-budget-bounded; very expensive per
    iteration so the budget is small."""
    moves = [
        meta._swap_two_lessons_same_prof,
        meta._move_lesson_to_empty_slot,
        meta._swap_two_lessons_same_class,
    ]
    for _ in range(budget_iter):
        k = rng.randint(k_min, k_max)
        cur = sol
        ok = True
        for _ in range(k):
            mv = rng.choice(moves)
            nxt = mv(cur, profs, dc_value, rng)
            if nxt is None:
                ok = False
                break
            cur = nxt
        if not ok:
            continue
        v, _ = meta.compute_soft(cur, profs)
        if v < best_val:
            return cur, v
    return None, best_val


NEIGHBOURHOODS = [
    ("1-swap",   _n1_one_swap,    400),
    ("2-swap",   _n2_two_swaps,   200),
    ("3-chain",  _n3_three_chain, 100),
    ("k-opt",    _nk_kopt,         40),
]


# ---------------- Main loop ----------------

def run_vns(sol, profs, dc_value, time_budget_s,
            log: bool = True, rng_seed: int = 7,
            enabled_neighbourhoods: list[str] | None = None
            ) -> tuple[dict, list]:
    """Variable Neighbourhood Search.

    Args:
      time_budget_s:     wall-clock cap; the loop also stops when a
                         full pass through all neighbourhoods finds
                         nothing.
      enabled_neighbourhoods: subset of {"1-swap","2-swap","3-chain","k-opt"};
                              default = all.

    Returns:
      (best_sol, history)
    """
    rng = random.Random(rng_seed)
    best = meta.deepcopy_sol(sol)
    best_val, _ = meta.compute_soft(best, profs)
    init_val = best_val
    history = [dict(stage="initial", val=init_val)]

    if enabled_neighbourhoods is None:
        nbhs = NEIGHBOURHOODS
    else:
        wanted = set(enabled_neighbourhoods)
        nbhs = [n for n in NEIGHBOURHOODS if n[0] in wanted]
    if not nbhs:
        return best, history

    t_start = time.time()
    full_pass_no_improvement = 0
    while time.time() - t_start < time_budget_s:
        improved_in_pass = False
        for name, fn, budget_iter in nbhs:
            if time.time() - t_start > time_budget_s:
                break
            new_sol, new_val = fn(best, profs, dc_value, rng,
                                   budget_iter, best_val)
            if new_sol is not None and new_val < best_val:
                if not meta.is_hard_feasible(new_sol, profs,
                                              verbose=False):
                    history.append(dict(stage=name,
                                         status="hard_violation"))
                    continue
                history.append(dict(
                    stage=name, status="improve",
                    val=new_val, prev=best_val,
                ))
                best = new_sol
                best_val = new_val
                improved_in_pass = True
                # restart from neighbourhood 1
                break
            else:
                history.append(dict(stage=name, status="no_improve"))
        if not improved_in_pass:
            full_pass_no_improvement += 1
            if full_pass_no_improvement >= 2:
                # Two empty passes in a row => converged
                break

    if log:
        imp_pct = 100.0 * (init_val - best_val) / max(init_val, 1)
        print(f"[VNS] obj {init_val} -> {best_val} ({imp_pct:.1f}% imp), "
              f"{len(history)} steps, "
              f"empty_passes={full_pass_no_improvement}")
    return best, history
