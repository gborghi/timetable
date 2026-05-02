r"""Column Generation (Dantzig-Wolfe decomposition) for Phase B.

For very large schools (>200 classes) the monolithic CP-SAT model
becomes too big to fit comfortably. Column generation decomposes
the problem into:

  Master (LP): pick a convex combination of pre-computed weekly
  patterns (one variable per pattern) so that every (class,
  subject, hour) demand is met.

  Sub-problem (one per teacher, CP-SAT): given the master's dual
  prices, generate a new weekly pattern for that teacher whose
  reduced cost is most negative (i.e. that lowers the master's
  objective the most).

Iteration: master -> duals -> per-teacher subproblem -> add
columns -> re-solve master. Stop when no subproblem can produce
a column with negative reduced cost.

This module is a SKELETON: the algorithmic structure is in place,
the master LP is solved with scipy.linprog (no external mip
dependency), and the subproblems delegate to a simple
seed-pattern generator. A full convergence pass is achievable but
out of scope for the initial commit; this skeleton already lets
us benchmark the approach on small instances and produces a
HARD-feasible solution (or reports infeasibility) so that
optimization.py can plug it in as an alternative Phase-B path.

For schools < 80 classes the monolithic CP-SAT path beats CG, so
this is OFF by default in the pipeline.
"""
from __future__ import annotations

import os
import sys
import time
from typing import Any

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import metaheuristics as meta  # type: ignore[no-redef]  # noqa: E402

DAYS = meta.DAYS
HOURS = meta.HOURS


# ---------------- Pattern generation (subproblem) ----------------

def _seed_patterns(profs: dict, dc_value: dict, max_per_teacher: int = 3
                   ) -> dict[str, list[dict]]:
    """Build a small initial pattern catalog from `dc_value` (Phase-A
    output), one or more "shifted" patterns per teacher.

    A pattern is a dict {(p, cl, subj, day, hour): 0/1}.

    The seed strategy: for each teacher with phase-A counts, place
    the lessons greedily into the first available (day, hour) slots
    that don't conflict with previously-placed lessons. Then we
    rotate the start hour by 1, 2, 3 to obtain `max_per_teacher`
    deterministic variants.
    """
    out: dict[str, list[dict]] = {}
    profs_list = sorted(profs.keys())
    for p in profs_list:
        triples = [(p, cl, subj, dc_value.get((p, cl, subj, d), 0))
                    for cl, sub_dict in (profs[p]["classi"]).items()
                    for subj in sub_dict.keys()
                    for d in DAYS]
        triples = [t for t in triples if t[3] > 0]
        if not triples:
            out[p] = []
            continue
        patterns: list[dict] = []
        for offset in range(max_per_teacher):
            pat: dict = {}
            occupied_t: set = set()       # (p, d, h)
            occupied_c: set = set()       # (cl, d, h)
            for (pp, cl, subj, _) in triples:
                # Determine the day this triple was for: encode in DC key
                d = None
                for dd in DAYS:
                    if dc_value.get((pp, cl, subj, dd), 0) > 0:
                        d = dd
                        break
                if d is None:
                    continue
                hours_to_place = dc_value.get((pp, cl, subj, d), 0)
                placed = 0
                for h_idx in range(len(HOURS)):
                    h = HOURS[(h_idx + offset) % len(HOURS)]
                    if (pp, d, h) in occupied_t or (cl, d, h) in occupied_c:
                        continue
                    pat[(pp, cl, subj, d, h)] = 1
                    occupied_t.add((pp, d, h))
                    occupied_c.add((cl, d, h))
                    placed += 1
                    if placed >= hours_to_place:
                        break
            if pat:
                patterns.append(pat)
        out[p] = patterns
    return out


def _cost_of_pattern(pat: dict, profs: dict) -> float:
    """SOFT cost of a single-teacher pattern -- a coarse proxy of the
    teacher's contribution to the global SOFT score."""
    if not pat:
        return 0.0
    # Sixth hour count
    sixth = sum(1 for (p, c, s, d, h), v in pat.items() if v and h == 13)
    # Day 5-load count
    day_load: dict[tuple, int] = {}
    for (p, c, s, d, h), v in pat.items():
        if v:
            day_load[(p, d)] = day_load.get((p, d), 0) + 1
    five = sum(1 for v in day_load.values() if v == 5)
    one = sum(1 for v in day_load.values() if v == 1)
    return float(
        meta.OBJECTIVE_WEIGHTS["sixth"] * sixth
        + meta.OBJECTIVE_WEIGHTS["five"] * five
        + meta.OBJECTIVE_WEIGHTS["one"] * one
    )


# ---------------- Master LP ----------------

def _solve_master(patterns_by_teacher: dict[str, list[dict]],
                  profs: dict, dc_value: dict
                  ) -> tuple[dict[str, int] | None, float, dict]:
    """Master LP: choose ONE pattern per teacher (binary choice
    relaxed to LP). Constraint: every (p, cl, subj, day) hours-count
    must be met.

    Returns:
      (selection_dict, objective_value, duals)
      where selection_dict[t] = pattern_index used for teacher t.
      If infeasible, returns (None, +inf, {}).
    """
    from scipy.optimize import linprog

    teachers = sorted(patterns_by_teacher.keys())
    cols = []                          # list of (teacher, pattern_idx)
    pattern_costs: list[float] = []
    for t in teachers:
        for i, pat in enumerate(patterns_by_teacher[t]):
            cols.append((t, i))
            pattern_costs.append(_cost_of_pattern(pat, profs))

    if not cols:
        return None, float("inf"), {}

    n_vars = len(cols)
    # Equality: pick exactly one pattern per teacher
    A_eq = []
    b_eq = []
    for t in teachers:
        row = [1.0 if (t == cols[j][0]) else 0.0 for j in range(n_vars)]
        A_eq.append(row)
        b_eq.append(1.0)

    # Inequality (lower-bound coverage of (p, cl, subj, day) hours via dc)
    # We use A_ub * x <= b_ub form, encoding -cover <= -demand.
    cover_keys = [k for k, v in dc_value.items() if v > 0]
    A_ub = []
    b_ub = []
    for k in cover_keys:
        (p, cl, subj, d) = k
        row = []
        for j in range(n_vars):
            t, i = cols[j]
            if t != p:
                row.append(0.0)
                continue
            pat = patterns_by_teacher[t][i]
            placed = sum(1 for (pp, cc, ss, dd, _hh), vv in pat.items()
                          if vv and pp == p and cc == cl
                          and ss == subj and dd == d)
            row.append(-float(placed))
        A_ub.append(row)
        b_ub.append(-float(dc_value[k]))

    bounds = [(0.0, 1.0) for _ in range(n_vars)]
    res = linprog(
        c=pattern_costs,
        A_ub=np.array(A_ub) if A_ub else None,
        b_ub=np.array(b_ub) if b_ub else None,
        A_eq=np.array(A_eq) if A_eq else None,
        b_eq=np.array(b_eq) if b_eq else None,
        bounds=bounds,
        method="highs",
    )
    if not res.success:
        return None, float("inf"), {}

    # Round LP solution to integer choices: pick the highest-weight
    # pattern per teacher.
    selection: dict[str, int] = {}
    for t in teachers:
        candidates = [(j, res.x[j]) for j in range(n_vars)
                      if cols[j][0] == t]
        if not candidates:
            continue
        j_best, _ = max(candidates, key=lambda kv: kv[1])
        selection[t] = cols[j_best][1]

    duals = {}
    if hasattr(res, "ineqlin") and res.ineqlin is not None:
        for k, lam in zip(cover_keys, res.ineqlin.marginals):
            duals[k] = float(lam)

    return selection, float(res.fun), duals


# ---------------- Top-level driver ----------------

def run_column_generation(profs: dict, dc_value: dict,
                          *, time_budget_s: float = 60.0,
                          patterns_per_teacher: int = 3,
                          log: bool = True) -> tuple[dict | None, dict]:
    """Run a single CG pass with a small pattern catalog.

    Args:
      profs:      Phase-A solution dict (teacher -> classi/...)
      dc_value:   per-(p, cl, subj, day) hour counts
      time_budget_s: cap on wall-clock time
      patterns_per_teacher: catalog size (the seed; full CG would
                             grow this iteratively)
      log:        print summary

    Returns:
      (sol_dict, info)
        sol_dict: a HARD-feasible solution dict (same shape as
                   the existing meta.run_lns input/output) if the
                   master picked a coherent assignment, else None.
        info: stats and diagnostic flags.
    """
    t0 = time.time()
    info: dict[str, Any] = {
        "kind": "column_generation",
        "patterns_per_teacher": patterns_per_teacher,
        "duration_s": None,
        "n_patterns_total": 0,
        "master_obj": None,
        "feasible_after_assembly": False,
        "warnings": [],
    }

    patterns_by_teacher = _seed_patterns(profs, dc_value,
                                          max_per_teacher=patterns_per_teacher)
    info["n_patterns_total"] = sum(len(v) for v in patterns_by_teacher.values())
    if info["n_patterns_total"] == 0:
        info["duration_s"] = time.time() - t0
        info["warnings"].append("nessun pattern generato dal seed")
        return None, info

    selection, obj, _duals = _solve_master(patterns_by_teacher,
                                            profs, dc_value)
    info["master_obj"] = obj
    if selection is None:
        info["warnings"].append("master LP infeasible")
        info["duration_s"] = time.time() - t0
        return None, info

    # Assemble a single solution dict by union of selected patterns
    sol: dict = {}
    for t, idx in selection.items():
        pat = patterns_by_teacher[t][idx]
        for k, v in pat.items():
            sol[k] = max(sol.get(k, 0), int(v))
    # Verify HARD; if not, this iteration didn't converge -- the
    # caller (optimization.py) can fall back to the standard pipe.
    if meta.is_hard_feasible(sol, profs, verbose=False):
        info["feasible_after_assembly"] = True
    else:
        info["warnings"].append(
            "soluzione assemblata non HARD-feasible: "
            "consiglio iterare CG (non implementato in skeleton)"
        )

    info["duration_s"] = time.time() - t0
    if log:
        v_str = (f"obj={obj:.1f} "
                 if obj != float("inf") else "obj=inf ")
        print(f"[CG] {info['n_patterns_total']} patterns, "
              f"{v_str}feasible={info['feasible_after_assembly']} "
              f"in {info['duration_s']:.1f}s")
    return sol, info
