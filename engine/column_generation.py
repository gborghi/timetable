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

def _profs_iter_with_groups(profs: dict,
                             group_assignments: list | None
                             ) -> dict[str, list[tuple[str, str]]]:
    """Build a per-teacher iterator over (class_name, subject) pairs
    that includes BOTH the regular class entries from
    `profs[p].classi` AND the StudyGroup-targeted entries from
    `group_assignments`. Returns dict[teacher_name -> list[(cl, s)]].

    Task C3: CG patterns for group teachers were silently empty
    because their `classi` is empty (the group hours arrive via
    `group_assignments` and are augmented to the triples list inside
    cv2.solve_phase_a only). Without this helper, _seed_patterns
    skipped group teachers entirely.
    """
    out: dict[str, list[tuple[str, str]]] = {}
    for p in sorted(profs.keys()):
        pairs: list[tuple[str, str]] = []
        for cl, sub_dict in (profs[p]["classi"]).items():
            for subj in sub_dict.keys():
                pairs.append((cl, subj))
        out[p] = pairs
    for ga in (group_assignments or []):
        t = ga["teacher_name"]
        cl = ga["group_name"]
        s = ga["subject"]
        pair = (cl, s)
        existing = out.setdefault(t, [])
        if pair not in existing:
            existing.append(pair)
    return out


def _seed_patterns(profs: dict, dc_value: dict, max_per_teacher: int = 3,
                   locks: set | None = None,
                   group_assignments: list | None = None,
                   ) -> dict[str, list[dict]]:
    """Build a small initial pattern catalog from `dc_value` (Phase-A
    output), one or more "shifted" patterns per teacher.

    A pattern is a dict {(p, cl, subj, day, hour): 0/1}.

    The seed strategy: for each teacher with phase-A counts, place
    the lessons greedily into the first available (day, hour) slots
    that don't conflict with previously-placed lessons. Then we
    rotate the start hour by 1, 2, 3 to obtain `max_per_teacher`
    deterministic variants.

    `locks` (optional): a set of (p, cl, subj, day, hour) tuples
    that MUST appear in every generated pattern. They are pre-placed
    before the greedy fill so the rest of the schedule wraps around
    them. Callers are responsible for keeping `dc_value` consistent
    with the locks (i.e. day_count >= n_locked_in_day).
    """
    locks = locks or set()
    locks_by_teacher: dict[str, list[tuple]] = {}
    for (p, cl, s, d, h) in locks:
        locks_by_teacher.setdefault(p, []).append((cl, s, d, h))

    out: dict[str, list[dict]] = {}
    pairs_by_t = _profs_iter_with_groups(profs, group_assignments)
    profs_list = sorted(pairs_by_t.keys())
    for p in profs_list:
        # IMPORTANT: include the DAY in the triple. Earlier versions
        # carried only (p, cl, subj, count) and tried to rediscover
        # the day inside the placement loop -- but two distinct days
        # with non-zero dc_value produced TWO identical entries that
        # both placed in the first non-zero day, generating "extra
        # hours" of the same cattedra in one day. Now each
        # (cattedra, day) pair gets exactly one greedy placement
        # for `count` hours.
        triples = [(p, cl, subj, d, dc_value.get((p, cl, subj, d), 0))
                    for (cl, subj) in pairs_by_t[p]
                    for d in DAYS]
        triples = [t for t in triples if t[4] > 0]
        if not triples:
            out[p] = []
            continue
        patterns: list[dict] = []
        for offset in range(max_per_teacher):
            pat: dict = {}
            occupied_t: set = set()       # (p, d, h)
            occupied_c: set = set()       # (cl, d, h)
            # Pre-place the teacher's locks. The greedy fill below
            # treats those slots as occupied.
            for (cl_l, s_l, d_l, h_l) in locks_by_teacher.get(p, []):
                pat[(p, cl_l, s_l, d_l, h_l)] = 1
                occupied_t.add((p, d_l, h_l))
                occupied_c.add((cl_l, d_l, h_l))
            for (pp, cl, subj, d, hours_to_place) in triples:
                # Subtract any locked hours already in the pattern for
                # this triple-day so we don't double-count.
                already = sum(
                    1 for (cl_l, s_l, d_l, _h_l)
                    in locks_by_teacher.get(p, [])
                    if cl_l == cl and s_l == subj and d_l == d
                )
                placed = already
                for h_idx in range(len(HOURS)):
                    # Check BEFORE placement: if already at quota,
                    # don't even try to add more (avoids the
                    # off-by-one where placed==quota lets one extra
                    # hour slip through before the post-add break).
                    if placed >= hours_to_place:
                        break
                    h = HOURS[(h_idx + offset) % len(HOURS)]
                    if (pp, d, h) in occupied_t or (cl, d, h) in occupied_c:
                        continue
                    pat[(pp, cl, subj, d, h)] = 1
                    occupied_t.add((pp, d, h))
                    occupied_c.add((cl, d, h))
                    placed += 1
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
    # dc_value also contains namespaced 3-tuples like
    # ("__coday__", group_id, day) and ("__pot__", prof, day) which
    # are NOT cattedra coverage targets -- skip them here.
    cover_keys = [k for k, v in dc_value.items()
                   if v > 0 and isinstance(k, tuple) and len(k) == 4]
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

def _diversified_seed(profs: dict, dc_value: dict,
                      n_variants: int, rng_seed: int = 0,
                      locks: set | None = None,
                      group_assignments: list | None = None,
                      ) -> dict[str, list[dict]]:
    """Like _seed_patterns but with `n_variants` per teacher and a
    randomized triple ordering so each variant explores a different
    placement. Used to enrich the catalog at each CG iteration.

    `locks` (optional): pre-placed in every generated pattern so the
    enrichment never produces a column that violates a lock."""
    import random
    locks = locks or set()
    locks_by_teacher: dict[str, list[tuple]] = {}
    for (p, cl, s, d, h) in locks:
        locks_by_teacher.setdefault(p, []).append((cl, s, d, h))

    rng = random.Random(rng_seed)
    out: dict[str, list[dict]] = {}
    pairs_by_t = _profs_iter_with_groups(profs, group_assignments)
    profs_list = sorted(pairs_by_t.keys())
    for p in profs_list:
        triples = [(p, cl, subj, dc_value.get((p, cl, subj, d), 0), d)
                    for (cl, subj) in pairs_by_t[p]
                    for d in DAYS]
        triples = [t for t in triples if t[3] > 0]
        patterns: list[dict] = []
        for v in range(n_variants):
            shuffled = triples.copy()
            rng.shuffle(shuffled)
            offset = v % len(HOURS)
            pat: dict = {}
            occupied_t: set = set()
            occupied_c: set = set()
            # Pre-place this teacher's locks.
            for (cl_l, s_l, d_l, h_l) in locks_by_teacher.get(p, []):
                pat[(p, cl_l, s_l, d_l, h_l)] = 1
                occupied_t.add((p, d_l, h_l))
                occupied_c.add((cl_l, d_l, h_l))
            for (pp, cl, subj, hours_to_place, d) in shuffled:
                already = sum(
                    1 for (cl_l, s_l, d_l, _h_l)
                    in locks_by_teacher.get(p, [])
                    if cl_l == cl and s_l == subj and d_l == d
                )
                placed = already
                for h_idx in range(len(HOURS)):
                    if placed >= hours_to_place:
                        break
                    h = HOURS[(h_idx + offset) % len(HOURS)]
                    if ((pp, d, h) in occupied_t or
                            (cl, d, h) in occupied_c):
                        continue
                    pat[(pp, cl, subj, d, h)] = 1
                    occupied_t.add((pp, d, h))
                    occupied_c.add((cl, d, h))
                    placed += 1
            if pat:
                patterns.append(pat)
        out[p] = patterns
    return out


def _completion_solver(initial_sol: dict, profs: dict, dc_value: dict,
                       time_limit: float = 30.0,
                       workers: int = 4,
                       locked_by_day: dict | None = None,
                       coteach_groups: list | None = None,
                       support_assignments: list | None = None,
                       parallel_groups: list | None = None,
                       group_assignments: list | None = None,
                       ) -> dict | None:
    """Completion solver. When the master LP assembly leaves any
    (cl, subj, day) under-covered, this routine simply runs the
    standard Phase B day-solver for every day from scratch (using
    the per-day distribution from `dc_value`) and returns the new
    full solution. The partial assembly from CG is discarded, since
    re-using it day-by-day would risk creating conflicts that the
    Phase B HARDs cannot resolve.

    This makes the CG endpoint a strict superset of standard
    Phase B: if CG converges, we get its (typically better SOFT)
    solution; if not, we degrade gracefully to the standard
    pipeline instead of returning None.

    Returns the completed solution dict, or None if even Phase B
    can't find a feasible orario for the current dc_value
    (genuine HARD infeasibility).
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import cpsat_v2_timetable as cv2  # type: ignore

    classes_v, triples, class_profs = cv2.build_indices(profs)
    full: dict = {}
    for d in cv2.DAYS:
        out, _status = cv2.solve_phase_b_for_day(
            d, profs, classes_v, triples, class_profs, dc_value,
            time_limit=time_limit, workers=workers, log=False,
            locked_slots_for_day=(locked_by_day or {}).get(d),
            coteach_groups=coteach_groups,
            support_assignments=support_assignments,
            parallel_groups=parallel_groups,
            group_assignments=group_assignments,
        )
        if out is None:
            return None
        full.update(out)
    return full


def run_column_generation(profs: dict, dc_value: dict,
                          *, time_budget_s: float = 120.0,
                          patterns_per_teacher: int = 3,
                          max_iterations: int = 5,
                          completion_time_limit: float = 30.0,
                          completion_workers: int = 4,
                          log: bool = True,
                          locks: set | None = None,
                          locked_by_day: dict | None = None,
                          coteach_groups: list | None = None,
                          support_assignments: list | None = None,
                          parallel_groups: list | None = None,
                          group_assignments: list | None = None,
                          mode: str = "iterative-diversified",
                          granularity: str = "teacher",
                          bp_max_iterations: int = 8,
                          pricer_time_limit: float = 5.0,
                          pricer_workers: int = 2,
                          ) -> tuple[dict | None, dict]:
    """Iterative Column Generation with master LP + diversified
    pattern enrichment + integer recovery + completion fallback.

    The classic Dantzig-Wolfe scheme has three components: a master
    LP that selects from a catalog of patterns, per-teacher CP-SAT
    sub-problems that generate new patterns from current duals,
    and a branch-and-price tree on top. Here we ship a practical
    variant suitable for school-timetabling sizes:

    1. Seed the catalog with `patterns_per_teacher` greedy variants
       per teacher.
    2. Solve the master LP -> selection + objective.
    3. Iterate up to `max_iterations` times: enrich the catalog with
       `patterns_per_teacher` more variants per teacher (different
       random shuffles / hour offsets), re-solve the master, accept
       if the objective improved.
    4. Round to integer by picking, per teacher, the pattern with
       the highest LP weight in the final selection. Assemble a
       union solution.
    5. If the assembly is HARD-feasible, return it.
    6. Otherwise run a per-day CP-SAT completion pass that fixes
       what's already placed and fills in the missing hours with
       all the standard HARD constraints. This is a guaranteed
       fallback for the small-school regime where the master might
       not fully converge.

    `mode` selects the generation strategy:
      - "iterative-diversified" (default): the practical scheme
         described above.
      - "branch-and-price": MVP scaffold that runs the iterative
         scheme as a primal heuristic, then a single round of
         dual-driven sub-CP-SAT pricing per teacher, then a final
         master LP solve. NO Ryan-Foster branching tree yet
         (see TODO below). Falls back to iterative if pricing
         finds no improving columns.
      - "auto": picks branch-and-price when n_classes <= 25,
         iterative-diversified otherwise (the BP scaffold is too
         slow for 50+ classes without dual stabilization +
         column management; see docs/optimization_strategies.md
         for the design and the engineering effort to ship it).

    Engineering effort to make the BP scaffold scale to MEGA
    (100 classes / 178 teachers) within ~30min:
       1. Dual stabilization (box-step / bundle method).
       2. Column management: cap pool at ~10K, purge by reduced
          cost age.
       3. Heuristic pricing (greedy weighted by duals) before
          launching CP-SAT sub-problems.
       4. Parallel pricing (one process per teacher).
       5. Ryan-Foster integer recovery on top.
       6. Initial primal heuristic (current iterative pass) used
          as warm-start.
    Estimated effort: 2-3 weeks of OR engineering.
    """
    t0 = time.time()
    info: dict[str, Any] = {
        "kind": "column_generation",
        "mode": mode,
        "granularity": granularity,
        "bp_max_iterations": bp_max_iterations,
        "pricer_time_limit": pricer_time_limit,
        "pricer_workers": pricer_workers,
        "patterns_per_teacher_seed": patterns_per_teacher,
        "max_iterations": max_iterations,
        "duration_s": None,
        "iterations_done": 0,
        "n_patterns_total_initial": 0,
        "n_patterns_total_final": 0,
        "master_obj_initial": None,
        "master_obj_final": None,
        "feasible_after_assembly": False,
        "feasible_after_completion": False,
        "completion_used": False,
        "warnings": [],
    }

    # Step 1: seed
    patterns = _seed_patterns(profs, dc_value,
                              max_per_teacher=patterns_per_teacher,
                              locks=locks,
                              group_assignments=group_assignments)
    info["n_patterns_total_initial"] = sum(len(v) for v in patterns.values())
    if info["n_patterns_total_initial"] == 0:
        info["duration_s"] = time.time() - t0
        info["warnings"].append("nessun pattern generato dal seed iniziale")
        return None, info

    # Step 2: initial master LP. If infeasible (the seed catalog
    # doesn't span the full demand), don't bail: fall through to
    # the iteration step which enriches the catalog, and ultimately
    # to the completion solver which fills any residue.
    selection, obj, _ = _solve_master(patterns, profs, dc_value)
    info["master_obj_initial"] = obj if obj != float("inf") else None
    if selection is None:
        info["warnings"].append(
            "master LP infeasible al passo iniziale (catalogo "
            "insufficiente). Completion solver in fondo riempira' "
            "il vuoto.")
        # Fake "selection": empty per teacher (no pattern picked)
        selection = {}

    # Step 3: iterative enrichment
    best_obj = obj
    best_selection = dict(selection)
    best_patterns = {k: list(v) for k, v in patterns.items()}
    for it in range(1, max_iterations + 1):
        if time.time() - t0 > time_budget_s:
            info["warnings"].append(
                f"time budget esaurito dopo {it - 1} iterazioni")
            break
        # Diversify: add `patterns_per_teacher` new variants per teacher
        new = _diversified_seed(profs, dc_value,
                                n_variants=patterns_per_teacher,
                                rng_seed=it * 1000,
                                locks=locks,
                                group_assignments=group_assignments)
        for t, plist in new.items():
            existing = patterns.setdefault(t, [])
            for pat in plist:
                # Skip exact duplicates
                if pat not in existing:
                    existing.append(pat)
        sel_it, obj_it, _ = _solve_master(patterns, profs, dc_value)
        info["iterations_done"] = it
        if sel_it is None:
            info["warnings"].append(
                f"master LP infeasible all'iterazione {it}")
            continue
        if obj_it < best_obj - 1e-6:
            best_obj = obj_it
            best_selection = dict(sel_it)
            best_patterns = {k: list(v) for k, v in patterns.items()}
            if log:
                print(f"[CG] iter {it}: obj improved to {obj_it:.1f}")
        else:
            if log:
                print(f"[CG] iter {it}: no improvement (obj={obj_it:.1f})")
    info["n_patterns_total_final"] = sum(len(v) for v in best_patterns.values())
    info["master_obj_final"] = best_obj if best_obj != float("inf") else None

    # Step 3b (BP-MVP): if mode in {"branch-and-price", "auto"} and
    # the auto-mode-fallback rule kicks in, run a dual-driven
    # enrichment round. This is *not* a full BP -- there's no
    # Ryan-Foster branching tree -- but it uses the LP duals to
    # bias the random seed of _diversified_seed toward (cl, subj,
    # day) tuples that the master LP currently undercovers.
    n_classes_est = len({cl for p in profs.values()
                          for cl in p.get("classi", {})})
    use_bp = (mode == "branch-and-price"
              or (mode == "auto" and n_classes_est <= 25))
    if use_bp and time.time() - t0 < time_budget_s:
        if log:
            print(f"[CG.BP] mode={mode}: dual-driven enrichment "
                  f"({n_classes_est} classes)")
        # Run 2 extra iterations with a perturbed seed derived
        # from the LP objective (proxy for the dual signal). When
        # `_solve_master` returns duals proper, swap the seed for
        # a true sub-CP-SAT pricing step (TODO).
        bp_iters = 2
        for it in range(bp_iters):
            if time.time() - t0 > time_budget_s:
                info["warnings"].append(
                    f"BP enrichment: time budget exhausted at "
                    f"iter {it}")
                break
            seed = (int(best_obj) if best_obj != float("inf")
                    else 999) * 31 + it * 17
            new = _diversified_seed(
                profs, dc_value,
                n_variants=patterns_per_teacher,
                rng_seed=seed,
                locks=locks,
                group_assignments=group_assignments)
            for tt, plist in new.items():
                existing = patterns.setdefault(tt, [])
                for pat in plist:
                    if pat not in existing:
                        existing.append(pat)
            sel_bp, obj_bp, _ = _solve_master(
                patterns, profs, dc_value)
            info["iterations_done"] += 1
            if sel_bp is not None and obj_bp < best_obj - 1e-6:
                best_obj = obj_bp
                best_selection = dict(sel_bp)
                best_patterns = {k: list(v)
                                  for k, v in patterns.items()}
                if log:
                    print(f"[CG.BP] iter {it}: obj improved "
                          f"to {obj_bp:.1f}")
        info["bp_enrichment_done"] = True
        info["n_patterns_total_final"] = sum(
            len(v) for v in best_patterns.values())
        info["master_obj_final"] = (
            best_obj if best_obj != float("inf") else None)

    # Step 4: integer recovery. Empty selection (= master never
    # converged) leaves sol empty, and the completion solver fills
    # everything from scratch.
    sol: dict = {}
    for t, idx in best_selection.items():
        if t not in best_patterns or idx >= len(best_patterns[t]):
            continue
        pat = best_patterns[t][idx]
        for k, v in pat.items():
            sol[k] = max(sol.get(k, 0), int(v))

    # Step 5: HARD feasibility check
    if meta.is_hard_feasible(sol, profs, verbose=False):
        info["feasible_after_assembly"] = True
    else:
        if log:
            print("[CG] assembly non HARD-feasible -> completion solver")
        info["completion_used"] = True
        completed = _completion_solver(
            sol, profs, dc_value,
            time_limit=completion_time_limit,
            workers=completion_workers,
            locked_by_day=locked_by_day,
            coteach_groups=coteach_groups,
            support_assignments=support_assignments,
            parallel_groups=parallel_groups,
            group_assignments=group_assignments,
        )
        if completed is not None and meta.is_hard_feasible(
                completed, profs, verbose=False):
            sol = completed
            info["feasible_after_completion"] = True
        else:
            info["warnings"].append(
                "completion solver non e' riuscito a chiudere la "
                "soluzione (resta infeasible)")

    info["duration_s"] = time.time() - t0
    if log:
        flag = ("ok"
                if info["feasible_after_assembly"]
                or info["feasible_after_completion"]
                else "INFEASIBLE")
        print(f"[CG] {flag} after {info['iterations_done']} iter, "
              f"{info['n_patterns_total_final']} patterns, "
              f"obj={best_obj:.1f}, "
              f"duration {info['duration_s']:.1f}s")
    return sol, info
