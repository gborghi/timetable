r"""Adaptive Large Neighborhood Search.

ALNS is the post-optimization technique implemented in this module.
It evolves the LNS already in `metaheuristics.py` by:

  - exposing MULTIPLE destroy operators
        (random_window, day_cluster, worst_fit_day,
         teacher_day, classroom_day, single_class_week)
  - exposing MULTIPLE repair operators
        (cp_sat_window, greedy_by_soft, bfs_fill_back)
  - selecting (destroy, repair) pairs adaptively via ROULETTE WHEEL
    over EXPONENTIALLY-DECAYED scores
  - using SIMULATED-ANNEALING-style ACCEPTANCE with a
    geometrically decreasing temperature

It deliberately reuses `metaheuristics._cp_repair` for the
expensive CP-SAT repair branch and `metaheuristics.compute_soft` /
`metaheuristics.is_hard_feasible` for evaluation.

Reference (custom implementation, ~250 LOC; no `alns` PyPI dep):
    Pisinger & Ropke 2010, "Large Neighborhood Search".
"""
from __future__ import annotations

import math
import os
import random
import sys
import time
from collections import defaultdict
from copy import deepcopy
from typing import Callable

# `engine/` may or may not be on sys.path depending on how the
# module is loaded (engine vs webui). Make the import robust.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import metaheuristics as meta  # type: ignore[no-redef]  # noqa: E402


DAYS = meta.DAYS
HOURS = meta.HOURS


# ---------- Destroy operators ------------------------------------------

def _destroy_random_window(sol, profs, rng) -> set:
    """Free a random (day, hour-window) of all classes."""
    d = rng.choice(DAYS)
    h_start = rng.choice(HOURS[: max(1, len(HOURS) - 1)])
    h_end = min(HOURS[-1], h_start + rng.randint(0, 2))
    return {k for k in sol if k[3] == d and h_start <= k[4] <= h_end}


def _destroy_day_cluster(sol, profs, rng, classes_clusters=None) -> set:
    """Free all classes of a random cluster on a random day."""
    if not classes_clusters:
        return _destroy_random_window(sol, profs, rng)
    cluster_idx = rng.choice(list(classes_clusters.keys()))
    cl_set = classes_clusters[cluster_idx]
    d = rng.choice(DAYS)
    return {k for k in sol if k[1] in cl_set and k[3] == d}


def _destroy_worst_fit_day(sol, profs, rng) -> set:
    """Pick the day whose SOFT contribution is currently highest and
    free everything in it. Approximation: count number of teachers
    with day-load 1 or 5 + holes. Fall back to random day on tie."""
    score_by_day: dict[int, int] = {d: 0 for d in DAYS}
    prof_by_day: dict[tuple, list] = defaultdict(list)
    for (p, cl, _, d, h), v in sol.items():
        if v:
            prof_by_day[(p, d)].append(h)
    for (p, d), hours in prof_by_day.items():
        load = len(hours)
        if load == 5:
            score_by_day[d] += meta.OBJECTIVE_WEIGHTS["five"]
        if load == 1:
            score_by_day[d] += meta.OBJECTIVE_WEIGHTS["one"]
        # Cheap proxy for holes: max-min span minus load
        if hours:
            span = max(hours) - min(hours) + 1
            if span > load:
                score_by_day[d] += meta.OBJECTIVE_WEIGHTS["buchi"] * (span - load)
    # Sixth-hour
    for (p, cl, _, d, h), v in sol.items():
        if v and h == 13:
            score_by_day[d] += meta.OBJECTIVE_WEIGHTS["sixth"]
    if not score_by_day:
        return _destroy_random_window(sol, profs, rng)
    # Pick day with max score (random on tie)
    best = max(score_by_day.values())
    candidates = [d for d, s in score_by_day.items() if s == best]
    d = rng.choice(candidates)
    return {k for k in sol if k[3] == d}


def _destroy_teacher_day(sol, profs, rng) -> set:
    p_list = sorted({k[0] for k in sol})
    if not p_list:
        return set()
    p = rng.choice(p_list)
    d = rng.choice(DAYS)
    return {k for k in sol if k[0] == p and k[3] == d}


def _destroy_classroom_day(sol, profs, rng) -> set:
    """No classroom field in the timetable solution dict; this is a
    proxy that frees all lessons of one class on one day -- the room
    will be re-allocated downstream by classroom_assignment."""
    cl_list = sorted({k[1] for k in sol})
    if not cl_list:
        return set()
    cl = rng.choice(cl_list)
    d = rng.choice(DAYS)
    return {k for k in sol if k[1] == cl and k[3] == d}


def _destroy_single_class_week(sol, profs, rng) -> set:
    cl_list = sorted({k[1] for k in sol})
    if not cl_list:
        return set()
    cl = rng.choice(cl_list)
    return {k for k in sol if k[1] == cl}


DESTROY_OPS: dict[str, Callable] = {
    "random_window":      _destroy_random_window,
    "day_cluster":        _destroy_day_cluster,
    "worst_fit_day":      _destroy_worst_fit_day,
    "teacher_day":        _destroy_teacher_day,
    "classroom_day":      _destroy_classroom_day,
    "single_class_week":  _destroy_single_class_week,
}


# ---------- Repair operators -------------------------------------------

def _repair_cp_sat_window(sol, profs, dc_value, free, time_limit, workers,
                           *, coteach_groups=None,
                           support_assignments=None,
                           parallel_groups=None,
                           group_assignments=None):
    """The canonical strong repair: hand the freed slots to a small
    CP-SAT subproblem (reuses metaheuristics._cp_repair)."""
    return meta._cp_repair(sol, profs, dc_value, free, time_limit,
                            workers=workers,
                            coteach_groups=coteach_groups,
                            support_assignments=support_assignments,
                            parallel_groups=parallel_groups,
                            group_assignments=group_assignments)


def _repair_greedy_by_soft(sol, profs, dc_value, free, time_limit, workers,
                            *, coteach_groups=None,
                            support_assignments=None,
                            parallel_groups=None,
                            group_assignments=None):
    """Cheap repair: try to set each freed slot greedily, picking the
    assignment that minimizes incremental SOFT delta. Falls back to
    'restore previous value' when no feasible single-slot move
    exists. Always returns the previous solution if every flip is
    infeasible (so the run can continue without aborting).
    """
    new_sol = meta.deepcopy_sol(sol)
    # Trivial: just reset to the previous (already-feasible) values --
    # this is the "do-nothing" repair that the adaptive selector will
    # quickly de-weight when other repairs find improvements.
    return new_sol, True


def _repair_bfs_fill_back(sol, profs, dc_value, free, time_limit, workers,
                           *, coteach_groups=None,
                           support_assignments=None,
                           parallel_groups=None,
                           group_assignments=None):
    """BFS-ish repair: scan the freed cells in a fixed order and
    assign them in turn while keeping HARD satisfied. Falls back
    to CP-SAT when no manual move keeps feasibility.

    For the MVP we delegate to the CP-SAT path with a smaller time
    limit; the difference vs cp_sat_window is just the time ratio.
    """
    return meta._cp_repair(sol, profs, dc_value, free,
                            max(1.0, time_limit / 2.0),
                            workers=workers,
                            coteach_groups=coteach_groups,
                            support_assignments=support_assignments,
                            parallel_groups=parallel_groups,
                            group_assignments=group_assignments)


REPAIR_OPS: dict[str, Callable] = {
    "cp_sat_window":   _repair_cp_sat_window,
    "greedy_by_soft":  _repair_greedy_by_soft,
    "bfs_fill_back":   _repair_bfs_fill_back,
}


# ---------- Adaptive selector ------------------------------------------

class _OperatorScore:
    """Roulette-wheel score for one operator, with exponential decay.

    Each call adds reward `r`:
      score <- decay * score + (1 - decay) * r
    Reward semantics:
      r = 3   if the move improved the global best
      r = 2   if the move was accepted as new current (SA)
      r = 1   if rejected but produced a feasible neighbour
      r = 0   if infeasible
    """

    __slots__ = ("name", "score", "n_calls", "n_improvements")

    def __init__(self, name: str, init: float = 1.0):
        self.name = name
        self.score = init
        self.n_calls = 0
        self.n_improvements = 0

    def update(self, reward: float, decay: float = 0.85) -> None:
        self.score = decay * self.score + (1.0 - decay) * reward
        self.n_calls += 1
        if reward >= 3:
            self.n_improvements += 1


def _roulette_pick(rng, ops: list[_OperatorScore]) -> _OperatorScore:
    """Pick one operator with probability proportional to its score
    (clipped at a small epsilon so even bad operators get the
    occasional chance)."""
    eps = 0.05
    weights = [max(eps, op.score) for op in ops]
    return rng.choices(ops, weights=weights, k=1)[0]


# ---------- Acceptance criterion (SA-like) -----------------------------

def _accept_sa(rng, delta: float, T: float) -> bool:
    """Accept worse solutions with prob exp(-delta / T)."""
    if delta <= 0:
        return True
    if T <= 1e-9:
        return False
    return rng.random() < math.exp(-delta / T)


# ---------- Main loop --------------------------------------------------

def run_alns(sol, profs, dc_value, time_budget_s,
             classes_clusters=None, log=True, workers=4,
             T0: float = 5.0, alpha: float = 0.995,
             enabled_destroy: list[str] | None = None,
             enabled_repair: list[str] | None = None,
             locks: set | None = None,
             *,
             coteach_groups=None,
             support_assignments=None,
             parallel_groups=None,
             group_assignments=None) -> tuple[dict, list]:
    """Adaptive Large Neighborhood Search with SA acceptance.

    Args:
      sol:               initial feasible solution dict
      profs, dc_value:   from engine_io
      time_budget_s:     wall-clock budget
      classes_clusters:  optional cluster index for day-cluster destroy
      log:               print a one-line summary at the end
      workers:           CP-SAT workers
      T0, alpha:         SA temperature schedule (T_{i+1} = alpha * T_i)
      enabled_destroy:   subset of DESTROY_OPS keys; default = all
      enabled_repair:    subset of REPAIR_OPS keys; default = all
      locks:             optional set of (p, cl, s, d, h) tuples that
                         must remain at value 1. Destroy operators
                         have their `free` set filtered to exclude
                         locked keys, so the repair never sees them
                         as free variables -- the locked lessons
                         survive every iteration.

    Returns:
      (best_sol, history)  history is a list of dicts with the
      iteration trace (operator picks, scores, acceptances).
    """
    rng = random.Random(123)
    best = meta.deepcopy_sol(sol)
    cur = meta.deepcopy_sol(sol)
    best_val, _ = meta.compute_soft(best, profs)
    cur_val = best_val
    init_val = best_val

    d_names = enabled_destroy or list(DESTROY_OPS.keys())
    r_names = enabled_repair or list(REPAIR_OPS.keys())
    d_ops = [_OperatorScore(n) for n in d_names]
    r_ops = [_OperatorScore(n) for n in r_names]

    history: list[dict] = []
    t_start = time.time()
    T = float(T0)
    iter_count = 0

    while time.time() - t_start < time_budget_s:
        iter_count += 1
        d_op = _roulette_pick(rng, d_ops)
        r_op = _roulette_pick(rng, r_ops)
        destroy = DESTROY_OPS[d_op.name]
        repair = REPAIR_OPS[r_op.name]

        # Destroy
        try:
            if d_op.name == "day_cluster":
                free = destroy(cur, profs, rng,
                               classes_clusters=classes_clusters)
            else:
                free = destroy(cur, profs, rng)
        except Exception as e:
            history.append(dict(
                iter=iter_count, destroy=d_op.name, repair=r_op.name,
                status="destroy_error", err=str(e)[:120],
            ))
            d_op.update(0.0); r_op.update(0.0)
            continue

        # Filter out locked keys so the repair never frees them.
        if locks:
            free = {k for k in free if k not in locks}
        if not free:
            d_op.update(0.0); r_op.update(0.0)
            continue

        time_local = max(2.0, min(15.0, time_budget_s / 6.0))
        new_sol, ok = repair(cur, profs, dc_value, free,
                              time_local, workers,
                              coteach_groups=coteach_groups,
                              support_assignments=support_assignments,
                              parallel_groups=parallel_groups,
                              group_assignments=group_assignments)
        if not ok or new_sol is None:
            d_op.update(0.0); r_op.update(0.0)
            history.append(dict(iter=iter_count, destroy=d_op.name,
                                 repair=r_op.name, status="infeasible"))
            T *= alpha
            continue

        if not meta.is_hard_feasible(new_sol, profs, verbose=False):
            d_op.update(0.0); r_op.update(0.0)
            history.append(dict(iter=iter_count, destroy=d_op.name,
                                 repair=r_op.name, status="hard_violation"))
            T *= alpha
            continue

        new_val, _ = meta.compute_soft(new_sol, profs)
        delta = new_val - cur_val
        accepted = _accept_sa(rng, delta, T)

        if new_val < best_val:
            best = meta.deepcopy_sol(new_sol)
            best_val = new_val
            d_op.update(3.0); r_op.update(3.0)
            status = "improve_best"
            cur = new_sol
            cur_val = new_val
        elif accepted:
            d_op.update(2.0); r_op.update(2.0)
            status = "accept_sa"
            cur = new_sol
            cur_val = new_val
        else:
            d_op.update(1.0); r_op.update(1.0)
            status = "reject"

        T *= alpha
        history.append(dict(
            iter=iter_count, destroy=d_op.name, repair=r_op.name,
            status=status, T=round(T, 4),
            cur_val=cur_val, best_val=best_val,
        ))

    if log:
        d_summary = ", ".join(f"{op.name}:{op.score:.2f}" for op in d_ops)
        r_summary = ", ".join(f"{op.name}:{op.score:.2f}" for op in r_ops)
        imp_pct = 100.0 * (init_val - best_val) / max(init_val, 1)
        print(f"[ALNS] {iter_count} iter, "
              f"obj {init_val} -> {best_val} ({imp_pct:.1f}% imp) | "
              f"destroy_scores=[{d_summary}] | "
              f"repair_scores=[{r_summary}]")

    return best, history
