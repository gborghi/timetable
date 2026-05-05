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
                  profs: dict, dc_value: dict,
                  *,
                  return_extended: bool = False,
                  ) -> tuple:
    """Master LP: choose ONE pattern per teacher (binary choice
    relaxed to LP). Constraint: every (p, cl, subj, day) hours-count
    must be met.

    Returns (when return_extended=False, default):
      (selection_dict, objective_value, lambda_duals)

    Returns (when return_extended=True):
      (selection_dict, objective_value, lambda_duals, mu_duals,
       lp_x, cols)
      where:
      - selection_dict[t] = pattern_index used for teacher t (the
        rounded integer choice, highest LP weight per teacher).
      - lambda_duals[k] is the dual price (>=0 when binding) of the
        (teacher, class, subject, day) cover inequality, sign-flipped
        from scipy's convention so positive <-> binding.
      - mu_duals[teacher] is the dual of the "exactly one pattern"
        equality.
      - lp_x is the fractional LP solution vector (parallel to cols).
      - cols is the list of (teacher, pattern_idx) tuples.

    If infeasible, returns (None, +inf, {}) or
    (None, +inf, {}, {}, [], cols).
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
        if return_extended:
            return None, float("inf"), {}, {}, [], []
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
        if return_extended:
            return None, float("inf"), {}, {}, [], cols
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

    # Lambda duals (cover inequalities). scipy returns
    # ineqlin.marginals as the dual of A_ub @ x <= b_ub. Our cover
    # rows are -cover <= -demand, so a positive shadow price on a
    # binding cover means scipy returns a negative marginal. Flip
    # sign so positive lambda <-> binding cover (matches the
    # textbook reduced-cost formula
    #     rc(p) = c(p) - mu_t - sum_k lambda_k * placed_p(k)).
    lambda_duals: dict = {}
    if hasattr(res, "ineqlin") and res.ineqlin is not None:
        for k, lam in zip(cover_keys, res.ineqlin.marginals):
            lambda_duals[k] = -float(lam)

    if not return_extended:
        return selection, float(res.fun), lambda_duals

    # Mu duals (one-pattern-per-teacher equalities).
    mu_duals: dict = {}
    if hasattr(res, "eqlin") and res.eqlin is not None:
        for t, mu in zip(teachers, res.eqlin.marginals):
            mu_duals[t] = float(mu)

    return (selection, float(res.fun), lambda_duals, mu_duals,
            list(res.x), cols)


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


# ---------------- Branch-and-Price: pricers ----------------
#
# Each granularity has its own CP-SAT sub-pricer. The pricer output
# is always a full TEACHER-WEEK pattern (dict {(t, cl, s, d, h): 1})
# compatible with the existing master LP (variant 1, "exactly one
# pattern per teacher" equality + cover inequalities).
#
# Pricing pattern: greedy WARM-START, CP-SAT ALWAYS INVOKED.
#
# Two roles for the greedy in every pricer:
#   1. CONTEXT-FILL (out-of-scope slots): `_greedy_base_pattern`
#      pre-places the teacher's slots OUTSIDE the granularity scope
#      (e.g. for teacher-class, all OTHER classes are filled greedy).
#      These slots are added to a lock-out set so the CP-SAT model
#      cannot put any in-scope variable on top of them.
#   2. WARM-START HINT (in-scope slots): a second greedy pass
#      proposes a feasible assignment for the in-scope slots and
#      passes it to the CP-SAT solver via `model.AddHint(var, val)`.
#      This is non-binding -- it only suggests a starting point
#      that helps the solver find a feasible solution faster.
#
# CP-SAT is ALWAYS invoked. There is no path where the greedy
# output replaces the CP-SAT pass:
#   - The CP-SAT model has Boolean variables for every in-scope
#     slot, structural constraints (cattedra-hours equality,
#     teacher and class no-overlap, lock-respect), and the
#     integer-scaled reduced-cost objective
#         Minimize  sum_(slots in scope) [-SCALE*lambda*slot]
#                   + PENALTY_SIXTH * sum_(slots in scope at h13) slot
#   - The pricer emits whatever the CP-SAT solver returns when the
#     model is feasible. If CP-SAT cannot find a feasible solution
#     within the time limit, the pricer returns (None, 0.0) and
#     the greedy output is NOT promoted to a column.
#   - The greedy hint never short-circuits the CP-SAT call.
#
# Reduced cost (LP-side, real units, not SCALE-integer):
#
#     rc(p) = c(p) - mu[t] - sum_(cl', s', d') lambda[t, cl', s', d']
#                                            * placed_p(t, cl', s', d')
#
# where:
#   c(p)         : SOFT cost of the full teacher-week pattern p
#                  (sixth/five/one as in _cost_of_pattern).
#   mu[t]        : dual of the "exactly one pattern per teacher"
#                  equality.
#   lambda[k]    : dual of the (t, cl', s', d') cover inequality,
#                  already sign-flipped so positive <-> binding.
#
# Reduced cost (LP-side, real units, not SCALE-integer):
#
#     rc(p) = c(p) - mu[t] - sum_(cl', s', d') lambda[t, cl', s', d']
#                                            * placed_p(t, cl', s', d')
#
# where:
#   c(p)         : SOFT cost of the full teacher-week pattern p
#                  (sixth/five/one as in _cost_of_pattern).
#   mu[t]        : dual of the "exactly one pattern per teacher"
#                  equality.
#   lambda[k]    : dual of the (t, cl', s', d') cover inequality,
#                  already sign-flipped so positive <-> binding.
#
# When `rc < -eps`, the pattern is an improving column and gets
# appended to the master's catalog.

_SCALE = 100        # integer-scaling for fractional duals
_SIXTH_HOUR = 13    # hour code for 13:00 (the "sixth hour")
_PENALTY_SIXTH = 5 * _SCALE   # SOFT penalty per slot on sixth hour


def _greedy_base_pattern(
    teacher: str, profs: dict, dc_value: dict,
    *,
    skip_classes: set | None = None,
    locks: set | None = None,
    group_assignments: list | None = None,
) -> tuple[dict, set, set]:
    """Greedy-place the teacher's cattedre into a base pattern,
    optionally skipping some class names (those will be filled by
    the CP-SAT pricer that calls this).

    Returns (pattern, occupied_t, occupied_c) where:
      - pattern is a dict of placed (t, cl, s, d, h): 1
      - occupied_t is a set of (t, d, h) the teacher already uses
      - occupied_c is a set of (cl, d, h) the classes already use

    The CP-SAT pricer will treat occupied_t / occupied_c as locked
    out for its variables.
    """
    locks = locks or set()
    skip_classes = skip_classes or set()
    pairs_by_t = _profs_iter_with_groups(profs, group_assignments)
    pairs = pairs_by_t.get(teacher, [])
    pat: dict = {}
    occupied_t: set = set()
    occupied_c: set = set()

    # Pre-place this teacher's locks for the OUT-OF-SCOPE classes
    # (locks for the in-scope class are handled by the CP-SAT
    # pricer that called us, so excluding them here prevents a
    # double lock-in/lock-out conflict on the same slot).
    locks_for_t = [(cl_l, s_l, d_l, h_l)
                    for (p, cl_l, s_l, d_l, h_l) in locks
                    if p == teacher and cl_l not in skip_classes]
    for (cl_l, s_l, d_l, h_l) in locks_for_t:
        pat[(teacher, cl_l, s_l, d_l, h_l)] = 1
        occupied_t.add((teacher, d_l, h_l))
        occupied_c.add((cl_l, d_l, h_l))

    # Greedy-place every cattedra-day NOT in skip_classes.
    for (cl, s) in pairs:
        if cl in skip_classes:
            continue
        for d in DAYS:
            q = int(dc_value.get((teacher, cl, s, d), 0))
            if q == 0:
                continue
            already = sum(1 for (cl_l, s_l, d_l, _h_l) in locks_for_t
                          if cl_l == cl and s_l == s and d_l == d)
            placed = already
            for h in HOURS:
                if placed >= q:
                    break
                if (teacher, d, h) in occupied_t:
                    continue
                if (cl, d, h) in occupied_c:
                    continue
                pat[(teacher, cl, s, d, h)] = 1
                occupied_t.add((teacher, d, h))
                occupied_c.add((cl, d, h))
                placed += 1
    return pat, occupied_t, occupied_c


def _compute_rc(
    pattern: dict, teacher: str, lambda_duals: dict, mu_t: float,
    profs: dict,
) -> float:
    """LP-side reduced cost for a teacher-week pattern."""
    soft = _cost_of_pattern(pattern, profs)
    sum_lambda = 0.0
    placed: dict = {}
    for (p, cl, s, d, _h), v in pattern.items():
        if not v or p != teacher:
            continue
        placed[(teacher, cl, s, d)] = placed.get(
            (teacher, cl, s, d), 0) + 1
    for k, n in placed.items():
        lam = float(lambda_duals.get(k, 0.0))
        if lam != 0.0:
            sum_lambda += lam * n
    return float(soft) - float(mu_t) - sum_lambda


def _pricing_subproblem_teacher_class(
    teacher: str, class_name: str, profs: dict, dc_value: dict,
    lambda_duals: dict, mu_t: float,
    *,
    time_limit: float = 5.0,
    workers: int = 2,
    locks: set | None = None,
    group_assignments: list | None = None,
    eps: float = 1e-6,
) -> tuple[dict | None, float]:
    """CP-SAT pricer for the teacher-class granularity.

    Outputs a full teacher-week pattern in which:
      - the (teacher, class_name, *, *, *) lessons are CP-SAT-
        optimised against the LP duals (objective: minimise
        -SCALE*lambda*placed + PENALTY_SIXTH*placed_at_sixth);
      - the (teacher, other_class, *, *, *) lessons come from a
        greedy base placement and are treated as locked by the
        CP-SAT.

    Returns (pattern, rc_lp) where:
      - pattern is the full teacher-week dict if rc < -eps;
        None otherwise (no improving column was found).
      - rc_lp is the LP-side reduced cost (no SCALE factor),
        useful for diagnostics.
    """
    from ortools.sat.python import cp_model

    pairs_by_t = _profs_iter_with_groups(profs, group_assignments)
    pairs = pairs_by_t.get(teacher, [])
    if not pairs:
        return None, 0.0

    # Subjects this teacher teaches in this specific class.
    subjects_in_class = sorted(
        {s for (cl, s) in pairs if cl == class_name})
    if not subjects_in_class:
        return None, 0.0

    # Greedy base for the OTHER classes; the (teacher, class_name)
    # cattedre will be placed by CP-SAT.
    base_pat, occ_t, occ_c = _greedy_base_pattern(
        teacher, profs, dc_value,
        skip_classes={class_name}, locks=locks,
        group_assignments=group_assignments,
    )

    # Per-subject day-counts that CP-SAT must place.
    triples: list[tuple[str, int, int]] = []  # (subj, d, q)
    for s in subjects_in_class:
        for d in DAYS:
            q = int(dc_value.get((teacher, class_name, s, d), 0))
            if q > 0:
                triples.append((s, d, q))
    if not triples:
        # Demand-free in this class: the greedy base is the column.
        rc = _compute_rc(base_pat, teacher, lambda_duals, mu_t, profs)
        if rc < -eps:
            return base_pat, rc
        return None, rc

    # Greedy WARM-START hint for the in-scope slots: place each
    # cattedra-day's hours sequentially in non-occupied (d, h)
    # slots. The hint is non-binding (does not constrain CP-SAT)
    # but helps the solver find a feasible solution faster. CP-SAT
    # is ALWAYS invoked below; the hint is purely an accelerator.
    hint_set: set = set()  # (s, d, h) tuples greedy chose to place
    _occ_t = set(occ_t)
    _occ_c = set(occ_c)
    for (s, d, q) in triples:
        placed = 0
        for h in HOURS:
            if placed >= q:
                break
            if (teacher, d, h) in _occ_t:
                continue
            if (class_name, d, h) in _occ_c:
                continue
            hint_set.add((s, d, h))
            _occ_t.add((teacher, d, h))
            _occ_c.add((class_name, d, h))
            placed += 1

    model = cp_model.CpModel()
    slot: dict[tuple, cp_model.IntVar] = {}
    for (s, d, _q) in triples:
        for h in HOURS:
            v = model.NewBoolVar(f"slot_{teacher}_{class_name}_{s}_{d}_{h}")
            # Lock-out slots already used by the greedy base or by
            # the teacher's own locks.
            if (teacher, d, h) in occ_t or (class_name, d, h) in occ_c:
                model.Add(v == 0)
            slot[(s, d, h)] = v
            # AddHint: warm-start CP-SAT with the greedy choice.
            model.AddHint(v, 1 if (s, d, h) in hint_set else 0)

    # Cattedra-hours equality: place exactly q hours of (s, d).
    for (s, d, q) in triples:
        model.Add(sum(slot[(s, d, h)] for h in HOURS) == q)

    # Class no-overlap on (d, h): at most one (subject, this-teacher,
    # this-class) slot may be active per (d, h). The other classes'
    # slots are excluded already via occ_c, so this constraint just
    # prevents two subjects from clashing inside the same class slot.
    for d in DAYS:
        for h in HOURS:
            terms = [slot[(s, d, h)] for (s, d2, _q) in triples
                      if d2 == d if (s, d, h) in slot]
            seen = set()
            uniq = []
            for v in terms:
                if id(v) not in seen:
                    seen.add(id(v))
                    uniq.append(v)
            if uniq:
                model.Add(sum(uniq) <= 1)

    # Locks on (t, cl, *, *, *) for THIS teacher+class force slot==1.
    for (p, cl_l, s_l, d_l, h_l) in (locks or ()):
        if p != teacher or cl_l != class_name:
            continue
        v = slot.get((s_l, d_l, h_l))
        if v is not None:
            model.Add(v == 1)

    # Objective: integer-scaled reduced cost contribution from this
    # class slice (the rest of the rc is constant given the greedy
    # base, so it's dropped from the CP-SAT objective and added back
    # in `_compute_rc` afterwards).
    obj_terms: list = []
    for (s, d, _q) in triples:
        lam = float(lambda_duals.get((teacher, class_name, s, d), 0.0))
        lam_int = int(round(lam * _SCALE))
        for h in HOURS:
            v = slot[(s, d, h)]
            if lam_int != 0:
                obj_terms.append(-lam_int * v)
            if h == _SIXTH_HOUR:
                obj_terms.append(_PENALTY_SIXTH * v)
    if obj_terms:
        model.Minimize(sum(obj_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit)
    solver.parameters.num_search_workers = int(workers)
    solver.parameters.log_search_progress = False
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, 0.0

    # Stitch the optimised slice into the greedy base.
    full_pat = dict(base_pat)
    for (s, d, _q) in triples:
        for h in HOURS:
            v = slot[(s, d, h)]
            if solver.Value(v):
                full_pat[(teacher, class_name, s, d, h)] = 1

    rc = _compute_rc(full_pat, teacher, lambda_duals, mu_t, profs)
    if rc < -eps:
        return full_pat, rc
    return None, rc


def _pricing_subproblem_teacher_class_subject(
    teacher: str, class_name: str, subject: str,
    profs: dict, dc_value: dict,
    lambda_duals: dict, mu_t: float,
    *,
    time_limit: float = 5.0,
    workers: int = 2,
    locks: set | None = None,
    group_assignments: list | None = None,
    eps: float = 1e-6,
) -> tuple[dict | None, float]:
    """CP-SAT pricer for the teacher-class-subject granularity.

    Narrower than `_pricing_subproblem_teacher_class`: only the
    (teacher, class_name, subject, *, *) slots are CP-SAT-optimised
    against the LP duals; everything else (the teacher's other
    subjects in this class AND all the teacher's other classes)
    is greedy-placed first and treated as locked.

    Useful when the teacher has multiple subjects in the same class
    (coteach scenarios) and only ONE of them dominates the dual
    signal -- you can refine just that subject without disturbing
    the other.
    """
    from ortools.sat.python import cp_model

    pairs_by_t = _profs_iter_with_groups(profs, group_assignments)
    pairs = pairs_by_t.get(teacher, [])
    if (class_name, subject) not in pairs:
        return None, 0.0

    # Greedy-place EVERYTHING the teacher does, then rip out the
    # (teacher, class_name, subject) entries: those are what the
    # CP-SAT will optimise.
    base_pat, occ_t, occ_c = _greedy_base_pattern(
        teacher, profs, dc_value,
        skip_classes=set(), locks=locks,
        group_assignments=group_assignments,
    )
    # Remove entries to be re-optimised, freeing their occupancy.
    keys_to_drop = [
        k for k in base_pat.keys()
        if k[0] == teacher and k[1] == class_name and k[2] == subject
    ]
    for k in keys_to_drop:
        del base_pat[k]
        _, _, _, d, h = k
        occ_t.discard((teacher, d, h))
        occ_c.discard((class_name, d, h))

    # Per-day demand for the (t, cl, s) cattedra.
    triples: list[tuple[int, int]] = []  # (d, q)
    for d in DAYS:
        q = int(dc_value.get((teacher, class_name, subject, d), 0))
        if q > 0:
            triples.append((d, q))
    if not triples:
        rc = _compute_rc(base_pat, teacher, lambda_duals, mu_t, profs)
        if rc < -eps:
            return base_pat, rc
        return None, rc

    # Greedy WARM-START hint for the in-scope (t, cl, s, *, *)
    # slice. CP-SAT is ALWAYS invoked below; the hint accelerates
    # the search by suggesting a feasible assignment.
    hint_set: set = set()  # (d, h) tuples greedy chose
    _occ_t = set(occ_t)
    _occ_c = set(occ_c)
    for (d, q) in triples:
        placed = 0
        for h in HOURS:
            if placed >= q:
                break
            if (teacher, d, h) in _occ_t:
                continue
            if (class_name, d, h) in _occ_c:
                continue
            hint_set.add((d, h))
            _occ_t.add((teacher, d, h))
            _occ_c.add((class_name, d, h))
            placed += 1

    model = cp_model.CpModel()
    slot: dict[tuple, cp_model.IntVar] = {}
    for (d, _q) in triples:
        for h in HOURS:
            v = model.NewBoolVar(
                f"slot_{teacher}_{class_name}_{subject}_{d}_{h}")
            if (teacher, d, h) in occ_t or (class_name, d, h) in occ_c:
                model.Add(v == 0)
            slot[(d, h)] = v
            model.AddHint(v, 1 if (d, h) in hint_set else 0)

    for (d, q) in triples:
        model.Add(sum(slot[(d, h)] for h in HOURS) == q)

    # Locks force slot==1 for this (t, cl, s, d, h).
    for (p, cl_l, s_l, d_l, h_l) in (locks or ()):
        if p != teacher or cl_l != class_name or s_l != subject:
            continue
        v = slot.get((d_l, h_l))
        if v is not None:
            model.Add(v == 1)

    # Objective: integer-scaled rc contribution from this single
    # cattedra (rest is constant given the greedy base).
    obj_terms: list = []
    for (d, _q) in triples:
        lam = float(lambda_duals.get(
            (teacher, class_name, subject, d), 0.0))
        lam_int = int(round(lam * _SCALE))
        for h in HOURS:
            v = slot[(d, h)]
            if lam_int != 0:
                obj_terms.append(-lam_int * v)
            if h == _SIXTH_HOUR:
                obj_terms.append(_PENALTY_SIXTH * v)
    if obj_terms:
        model.Minimize(sum(obj_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit)
    solver.parameters.num_search_workers = int(workers)
    solver.parameters.log_search_progress = False
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, 0.0

    full_pat = dict(base_pat)
    for (d, _q) in triples:
        for h in HOURS:
            if solver.Value(slot[(d, h)]):
                full_pat[(teacher, class_name, subject, d, h)] = 1
    rc = _compute_rc(full_pat, teacher, lambda_duals, mu_t, profs)
    if rc < -eps:
        return full_pat, rc
    return None, rc


def _pricing_subproblem_teacher_subject(
    teacher: str, subject: str, profs: dict, dc_value: dict,
    lambda_duals: dict, mu_t: float,
    *,
    time_limit: float = 5.0,
    workers: int = 2,
    locks: set | None = None,
    group_assignments: list | None = None,
    eps: float = 1e-6,
) -> tuple[dict | None, float]:
    """CP-SAT pricer for the teacher-subject granularity.

    Optimises the (teacher, *, subject, *, *) slice -- ALL classes
    in which the teacher teaches `subject`, across all (d, h). The
    teacher's OTHER subjects (taught in other classes too) are
    greedy-placed first and locked.

    When useful: teachers with disciplinary specialisation that
    teach the same subject in multiple classes can have their
    weekly load REbalanced across classes without affecting their
    other subjects.
    """
    from ortools.sat.python import cp_model

    pairs_by_t = _profs_iter_with_groups(profs, group_assignments)
    pairs = pairs_by_t.get(teacher, [])
    classes_for_subj = sorted({cl for (cl, s) in pairs if s == subject})
    if not classes_for_subj:
        return None, 0.0

    # Greedy-place EVERYTHING, then rip out the (teacher, *, subject)
    # entries: those are CP-SAT's playground.
    base_pat, occ_t, occ_c = _greedy_base_pattern(
        teacher, profs, dc_value,
        skip_classes=set(), locks=locks,
        group_assignments=group_assignments,
    )
    keys_to_drop = [k for k in base_pat.keys()
                    if k[0] == teacher and k[2] == subject]
    for k in keys_to_drop:
        del base_pat[k]
        _, cl, _, d, h = k
        occ_t.discard((teacher, d, h))
        occ_c.discard((cl, d, h))

    # Per-(class, day) demand for the (t, *, s) slice.
    triples: list[tuple[str, int, int]] = []  # (cl, d, q)
    for cl in classes_for_subj:
        for d in DAYS:
            q = int(dc_value.get((teacher, cl, subject, d), 0))
            if q > 0:
                triples.append((cl, d, q))
    if not triples:
        rc = _compute_rc(base_pat, teacher, lambda_duals, mu_t, profs)
        return (base_pat, rc) if rc < -eps else (None, rc)

    # Greedy WARM-START hint. CP-SAT is ALWAYS invoked.
    hint_set: set = set()  # (cl, d, h) tuples greedy chose
    _occ_t = set(occ_t)
    _occ_c = set(occ_c)
    for (cl, d, q) in triples:
        placed = 0
        for h in HOURS:
            if placed >= q:
                break
            if (teacher, d, h) in _occ_t:
                continue
            if (cl, d, h) in _occ_c:
                continue
            hint_set.add((cl, d, h))
            _occ_t.add((teacher, d, h))
            _occ_c.add((cl, d, h))
            placed += 1

    model = cp_model.CpModel()
    slot: dict[tuple, cp_model.IntVar] = {}
    for (cl, d, _q) in triples:
        for h in HOURS:
            v = model.NewBoolVar(f"slot_{teacher}_{cl}_{subject}_{d}_{h}")
            if (teacher, d, h) in occ_t or (cl, d, h) in occ_c:
                model.Add(v == 0)
            slot[(cl, d, h)] = v
            model.AddHint(v, 1 if (cl, d, h) in hint_set else 0)

    # Cattedra-hours equality per (cl, d).
    for (cl, d, q) in triples:
        model.Add(sum(slot[(cl, d, h)] for h in HOURS) == q)

    # Teacher no-overlap on (d, h): at most one of the new slot vars
    # can be active per (d, h) (they all belong to teacher t).
    for d in DAYS:
        for h in HOURS:
            terms = [slot[(cl, d, h)] for (cl, d2, _q) in triples
                      if d2 == d if (cl, d, h) in slot]
            seen = set()
            uniq = []
            for v in terms:
                if id(v) not in seen:
                    seen.add(id(v))
                    uniq.append(v)
            if uniq:
                model.Add(sum(uniq) <= 1)

    # Locks for (t, *, s, d, h).
    for (p, cl_l, s_l, d_l, h_l) in (locks or ()):
        if p != teacher or s_l != subject:
            continue
        v = slot.get((cl_l, d_l, h_l))
        if v is not None:
            model.Add(v == 1)

    obj_terms: list = []
    for (cl, d, _q) in triples:
        lam = float(lambda_duals.get(
            (teacher, cl, subject, d), 0.0))
        lam_int = int(round(lam * _SCALE))
        for h in HOURS:
            v = slot[(cl, d, h)]
            if lam_int != 0:
                obj_terms.append(-lam_int * v)
            if h == _SIXTH_HOUR:
                obj_terms.append(_PENALTY_SIXTH * v)
    if obj_terms:
        model.Minimize(sum(obj_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit)
    solver.parameters.num_search_workers = int(workers)
    solver.parameters.log_search_progress = False
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, 0.0

    full_pat = dict(base_pat)
    for (cl, d, _q) in triples:
        for h in HOURS:
            if solver.Value(slot[(cl, d, h)]):
                full_pat[(teacher, cl, subject, d, h)] = 1
    rc = _compute_rc(full_pat, teacher, lambda_duals, mu_t, profs)
    return (full_pat, rc) if rc < -eps else (None, rc)


def _pricing_subproblem_teacher_day(
    teacher: str, day: int, profs: dict, dc_value: dict,
    lambda_duals: dict, mu_t: float,
    *,
    time_limit: float = 5.0,
    workers: int = 2,
    locks: set | None = None,
    group_assignments: list | None = None,
    eps: float = 1e-6,
) -> tuple[dict | None, float]:
    """CP-SAT pricer for the teacher-day granularity.

    Optimises the (teacher, *, *, day, *) slice -- ALL of the
    teacher's cattedre on a single day. The teacher's lessons on
    OTHER days are greedy-placed first; this day is rebuilt from
    scratch by the CP-SAT model against the LP duals.

    When useful: teachers with strong day-level preferences
    (free_day candidates, max_consecutive constraints) -- the
    pricer can re-shape the (t, day) plan without affecting the
    rest of the week.
    """
    from ortools.sat.python import cp_model

    pairs_by_t = _profs_iter_with_groups(profs, group_assignments)
    pairs = pairs_by_t.get(teacher, [])
    if not pairs:
        return None, 0.0

    # Greedy-place EVERYTHING, then rip out (teacher, *, *, day, *).
    base_pat, occ_t, occ_c = _greedy_base_pattern(
        teacher, profs, dc_value,
        skip_classes=set(), locks=locks,
        group_assignments=group_assignments,
    )
    keys_to_drop = [k for k in base_pat.keys()
                    if k[0] == teacher and k[3] == day]
    for k in keys_to_drop:
        del base_pat[k]
        _, cl, _, d_, h_ = k
        occ_t.discard((teacher, d_, h_))
        occ_c.discard((cl, d_, h_))

    # Per-(class, subject) demand on this specific day.
    triples: list[tuple[str, str, int]] = []  # (cl, s, q)
    for (cl, s) in pairs:
        q = int(dc_value.get((teacher, cl, s, day), 0))
        if q > 0:
            triples.append((cl, s, q))
    if not triples:
        rc = _compute_rc(base_pat, teacher, lambda_duals, mu_t, profs)
        return (base_pat, rc) if rc < -eps else (None, rc)

    # Greedy WARM-START hint for the (t, *, *, day, *) slice.
    # CP-SAT is ALWAYS invoked.
    hint_set: set = set()  # (cl, s, h) tuples greedy chose
    _occ_t = set(occ_t)
    _occ_c = set(occ_c)
    for (cl, s, q) in triples:
        placed = 0
        for h in HOURS:
            if placed >= q:
                break
            if (teacher, day, h) in _occ_t:
                continue
            if (cl, day, h) in _occ_c:
                continue
            hint_set.add((cl, s, h))
            _occ_t.add((teacher, day, h))
            _occ_c.add((cl, day, h))
            placed += 1

    model = cp_model.CpModel()
    slot: dict[tuple, cp_model.IntVar] = {}
    for (cl, s, _q) in triples:
        for h in HOURS:
            v = model.NewBoolVar(f"slot_{teacher}_{cl}_{s}_{day}_{h}")
            # The OTHER teachers on this (cl, day, h) live in
            # _other_ patterns, so we DON'T lock those out here
            # (the master LP enforces cover, completion solves
            # remaining HARD overlaps). Only lock out conflicts
            # with THIS teacher's locks/greedy-base on this day.
            if (teacher, day, h) in occ_t:
                model.Add(v == 0)
            slot[(cl, s, h)] = v
            model.AddHint(v, 1 if (cl, s, h) in hint_set else 0)

    # Cattedra-hours equality per (cl, s).
    for (cl, s, q) in triples:
        model.Add(sum(slot[(cl, s, h)] for h in HOURS) == q)

    # Teacher no-overlap on (day, h): only one (cl, s) slot active.
    for h in HOURS:
        terms = [slot[(cl, s, h)]
                  for (cl, s, _q) in triples if (cl, s, h) in slot]
        seen = set()
        uniq = []
        for v in terms:
            if id(v) not in seen:
                seen.add(id(v))
                uniq.append(v)
        if uniq:
            model.Add(sum(uniq) <= 1)

    # Within-class no-overlap on (day, h): if t teaches multiple
    # subjects in same class, only one can land on the same hour.
    # (Cross-teacher class overlap is handled by master+completion.)
    classes_today = sorted({cl for (cl, _s, _q) in triples})
    for cl in classes_today:
        for h in HOURS:
            terms_cl = [slot[(cl_, s, h)]
                         for (cl_, s, _q) in triples
                         if cl_ == cl and (cl_, s, h) in slot]
            seen = set()
            uniq = []
            for v in terms_cl:
                if id(v) not in seen:
                    seen.add(id(v))
                    uniq.append(v)
            if uniq:
                model.Add(sum(uniq) <= 1)

    # Locks for (t, *, *, day, h).
    for (p, cl_l, s_l, d_l, h_l) in (locks or ()):
        if p != teacher or d_l != day:
            continue
        v = slot.get((cl_l, s_l, h_l))
        if v is not None:
            model.Add(v == 1)

    # Objective.
    obj_terms: list = []
    for (cl, s, _q) in triples:
        lam = float(lambda_duals.get((teacher, cl, s, day), 0.0))
        lam_int = int(round(lam * _SCALE))
        for h in HOURS:
            v = slot[(cl, s, h)]
            if lam_int != 0:
                obj_terms.append(-lam_int * v)
            if h == _SIXTH_HOUR:
                obj_terms.append(_PENALTY_SIXTH * v)
    if obj_terms:
        model.Minimize(sum(obj_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit)
    solver.parameters.num_search_workers = int(workers)
    solver.parameters.log_search_progress = False
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, 0.0

    full_pat = dict(base_pat)
    for (cl, s, _q) in triples:
        for h in HOURS:
            if solver.Value(slot[(cl, s, h)]):
                full_pat[(teacher, cl, s, day, h)] = 1
    rc = _compute_rc(full_pat, teacher, lambda_duals, mu_t, profs)
    return (full_pat, rc) if rc < -eps else (None, rc)


# ---------------- Master LP variant 2 (DW with overlaps) ----------------
#
# Used by BP for granularities whose columns span MULTIPLE teachers
# (class, class-day, day, curriculum). Each column is a partial
# pattern (any subset of (t, cl, s, d, h) slots), and the LP picks
# fractional weights subject to:
#   - cover: sum_col x[col] * placed_col(k) >= demand[k] for each
#     cattedra-day k = (t, cl, s, d).
#   - class no-overlap: sum_col x[col] * occupies_col(cl, d, h) <= 1
#     for each (cl, d, h).
#   - teacher no-overlap: sum_col x[col] * occupies_col(t, d, h) <= 1
#     for each (t, d, h).
# No "exactly one pattern per teacher" equality (variant 1) -- the
# overlap inequalities subsume it.
#
# Reduced cost for a partial pattern p (with the master2 duals
# lambda_cover, mu_class, mu_teacher all sign-flipped so positive
# <-> binding):
#
#     rc(p) = c(p) - sum_k lambda_cover[k] * placed_p(k)
#                  + sum_(cl,d,h) mu_class[(cl,d,h)] * occupies_p(cl,d,h)
#                  + sum_(t,d,h) mu_teacher[(t,d,h)] * occupies_p(t,d,h)
#
# A binding mu_class or mu_teacher pushes the pricer AWAY from
# slots in that bottleneck.


def _occupies_class_slot(col: dict, cl: str, d: int, h: int) -> int:
    for (_p, cc, _s, dd, hh), v in col.items():
        if v and cc == cl and dd == d and hh == h:
            return 1
    return 0


def _occupies_teacher_slot(col: dict, t: str, d: int, h: int) -> int:
    for (pp, _c, _s, dd, hh), v in col.items():
        if v and pp == t and dd == d and hh == h:
            return 1
    return 0


def _placed_in(col: dict, t: str, cl: str, s: str, d: int) -> int:
    return sum(1 for (pp, cc, ss, dd, _h), v in col.items()
               if v and pp == t and cc == cl and ss == s and dd == d)


def _solve_master_dw(
    columns: list[dict], dc_value: dict,
    *,
    return_extended: bool = False,
) -> tuple:
    """Master LP variant 2 (proper Dantzig-Wolfe).

    `columns` is a flat list of partial pattern dicts. The LP picks
    fractional weights x[col] in [0, 1] minimising sum c[col]*x[col]
    subject to cover (>=) + class-no-overlap (<=) + teacher-no-overlap
    (<=) inequalities.

    Returns (when return_extended=False):
      (lp_x, obj, lambda_cover_duals)
    Returns (when return_extended=True):
      (lp_x, obj, lambda_cover_duals, mu_class_duals, mu_teacher_duals,
       cover_keys, class_keys, teacher_keys)

    On infeasibility returns (None, +inf, {}, ...).
    """
    from scipy.optimize import linprog

    n = len(columns)
    if n == 0:
        if return_extended:
            return None, float("inf"), {}, {}, {}, [], [], []
        return None, float("inf"), {}

    pattern_costs = [_cost_of_pattern(c, {}) for c in columns]

    cover_keys = [k for k, v in dc_value.items()
                   if v > 0 and isinstance(k, tuple) and len(k) == 4]

    class_set: set = set()
    teacher_set: set = set()
    for col in columns:
        for (pp, cc, _s, dd, hh), v in col.items():
            if v:
                class_set.add((cc, dd, hh))
                teacher_set.add((pp, dd, hh))
    class_keys = sorted(class_set)
    teacher_keys = sorted(teacher_set)

    A_ub: list[list[float]] = []
    b_ub: list[float] = []

    # Cover (negated for >= demand).
    for k in cover_keys:
        (t, cl, s, d) = k
        row = [-float(_placed_in(columns[j], t, cl, s, d))
                for j in range(n)]
        A_ub.append(row)
        b_ub.append(-float(dc_value[k]))

    # Class no-overlap.
    for k in class_keys:
        (cl, d, h) = k
        row = [float(_occupies_class_slot(columns[j], cl, d, h))
                for j in range(n)]
        A_ub.append(row)
        b_ub.append(1.0)

    # Teacher no-overlap.
    for k in teacher_keys:
        (t, d, h) = k
        row = [float(_occupies_teacher_slot(columns[j], t, d, h))
                for j in range(n)]
        A_ub.append(row)
        b_ub.append(1.0)

    bounds = [(0.0, 1.0) for _ in range(n)]
    res = linprog(
        c=pattern_costs,
        A_ub=np.array(A_ub) if A_ub else None,
        b_ub=np.array(b_ub) if b_ub else None,
        bounds=bounds,
        method="highs",
    )
    if not res.success:
        if return_extended:
            return (None, float("inf"), {}, {}, {},
                    cover_keys, class_keys, teacher_keys)
        return None, float("inf"), {}

    lp_x = list(res.x)
    obj = float(res.fun)

    # Sign-flip all marginals so positive dual <-> binding constraint.
    lambda_cover: dict = {}
    mu_class: dict = {}
    mu_teacher: dict = {}
    if hasattr(res, "ineqlin") and res.ineqlin is not None:
        marg = list(res.ineqlin.marginals)
        n_cov = len(cover_keys)
        n_cl = len(class_keys)
        for i, k in enumerate(cover_keys):
            lambda_cover[k] = -float(marg[i])
        for i, k in enumerate(class_keys):
            mu_class[k] = -float(marg[n_cov + i])
        for i, k in enumerate(teacher_keys):
            mu_teacher[k] = -float(marg[n_cov + n_cl + i])

    if not return_extended:
        return lp_x, obj, lambda_cover
    return (lp_x, obj, lambda_cover, mu_class, mu_teacher,
            cover_keys, class_keys, teacher_keys)


def _compute_rc_dw(
    pattern: dict, lambda_cover: dict, mu_class: dict, mu_teacher: dict,
) -> float:
    """LP-side reduced cost for a partial pattern under master
    variant 2 (DW)."""
    soft = _cost_of_pattern(pattern, {})
    sum_lambda = 0.0
    placed_cov: dict = {}
    occ_class: set = set()
    occ_teacher: set = set()
    for (p, cl, s, d, h), v in pattern.items():
        if not v:
            continue
        placed_cov[(p, cl, s, d)] = placed_cov.get((p, cl, s, d), 0) + 1
        occ_class.add((cl, d, h))
        occ_teacher.add((p, d, h))
    for k, n in placed_cov.items():
        sum_lambda += float(lambda_cover.get(k, 0.0)) * n
    sum_mu_class = sum(float(mu_class.get(k, 0.0)) for k in occ_class)
    sum_mu_teacher = sum(float(mu_teacher.get(k, 0.0)) for k in occ_teacher)
    return soft - sum_lambda + sum_mu_class + sum_mu_teacher


# ---------------- Per-class CP-SAT pricer ----------------


def _classes_with_demand(profs: dict, dc_value: dict,
                          group_assignments: list | None
                          ) -> list[str]:
    """All class names that have positive demand in dc_value."""
    classes: set = set()
    for k, v in dc_value.items():
        if (v > 0 and isinstance(k, tuple) and len(k) == 4):
            classes.add(k[1])
    # Group classes (StudyGroup names) come from group_assignments.
    for ga in (group_assignments or []):
        classes.add(ga.get("group_name"))
    return sorted(c for c in classes if c)


def _teachers_for_class(class_name: str, profs: dict,
                         dc_value: dict,
                         group_assignments: list | None
                         ) -> list[tuple[str, str]]:
    """Return [(teacher, subject)] pairs that have positive demand
    in `class_name`."""
    pairs_by_t = _profs_iter_with_groups(profs, group_assignments)
    out: list[tuple[str, str]] = []
    for t, pairs in pairs_by_t.items():
        for (cl, s) in pairs:
            if cl != class_name:
                continue
            if any(dc_value.get((t, cl, s, d), 0) > 0 for d in DAYS):
                out.append((t, s))
    return out


def _pricing_subproblem_class(
    class_name: str, profs: dict, dc_value: dict,
    lambda_cover: dict, mu_class: dict, mu_teacher: dict,
    *,
    time_limit: float = 5.0,
    workers: int = 2,
    locks: set | None = None,
    group_assignments: list | None = None,
    eps: float = 1e-6,
) -> tuple[dict | None, float]:
    """CP-SAT pricer for the `class` granularity (master variant 2).

    Builds a partial pattern that schedules all the cattedre of
    `class_name` (covering every (t, cl=class_name, s, d) demand)
    in the (d, h) grid. The output is a MULTI-TEACHER column ready
    to be added to master_dw.

    CP-SAT is ALWAYS invoked. A greedy pass produces a feasible
    initial assignment that is fed to the solver via add_hint as a
    warm-start.

    Reduced cost minimisation (integer-scaled, SCALE=100):
      Minimize sum_(t,s,d,h) [-lam_cov*slot]
             + sum_(d,h) mu_cl_int * any_slot_at_(d,h)
             + sum_(t,d,h) mu_t_int * any_slot_at_(t,d,h)
             + PENALTY_SIXTH * sum_(slots at h=13) slot
    """
    from ortools.sat.python import cp_model

    pairs = _teachers_for_class(class_name, profs, dc_value,
                                 group_assignments)
    if not pairs:
        return None, 0.0

    # Build (t, s, d, q) demand list for this class.
    quads: list[tuple[str, str, int, int]] = []
    for (t, s) in pairs:
        for d in DAYS:
            q = int(dc_value.get((t, class_name, s, d), 0))
            if q > 0:
                quads.append((t, s, d, q))
    if not quads:
        return None, 0.0

    # Greedy hint: place each (t, s, d) in the first non-conflicting
    # (cl, d, h) and (t, d, h) slot. Since this is one class, the
    # "occupied class slot" set guards against multiple teachers
    # landing on the same (d, h) of class_name.
    hint_set: set = set()  # (t, s, d, h)
    occ_cl_local: set = set()  # (d, h) used by class
    occ_t_local: dict[str, set] = {}  # teacher -> set of (d, h)
    # Pre-place this class's locks (lock-in via CP-SAT).
    locks_in_class = [(p, cl_l, s_l, d_l, h_l)
                       for (p, cl_l, s_l, d_l, h_l) in (locks or ())
                       if cl_l == class_name]
    for (p, _cl_l, s_l, d_l, h_l) in locks_in_class:
        hint_set.add((p, s_l, d_l, h_l))
        occ_cl_local.add((d_l, h_l))
        occ_t_local.setdefault(p, set()).add((d_l, h_l))
    for (t, s, d, q) in quads:
        # Already-locked count for this cattedra-day.
        already = sum(1 for (p, _c, s_l, d_l, _h)
                       in [(x[0], None, x[2], x[3], x[4])
                            for x in locks_in_class]
                       if p == t and s_l == s and d_l == d)
        placed = already
        for h in HOURS:
            if placed >= q:
                break
            if (d, h) in occ_cl_local:
                continue
            if (d, h) in occ_t_local.get(t, set()):
                continue
            hint_set.add((t, s, d, h))
            occ_cl_local.add((d, h))
            occ_t_local.setdefault(t, set()).add((d, h))
            placed += 1

    # Build CP-SAT model.
    model = cp_model.CpModel()
    slot: dict[tuple, cp_model.IntVar] = {}
    # One BoolVar per (t, s, d, h); only declared for demanded triples.
    for (t, s, d, _q) in quads:
        for h in HOURS:
            v = model.NewBoolVar(f"slot_{t}_{class_name}_{s}_{d}_{h}")
            slot[(t, s, d, h)] = v
            model.AddHint(v, 1 if (t, s, d, h) in hint_set else 0)

    # Cattedra-hours equality per (t, s, d).
    for (t, s, d, q) in quads:
        model.Add(sum(slot[(t, s, d, h)] for h in HOURS) == q)

    # Class no-overlap: at most one (t, s) on the same (d, h).
    for d in DAYS:
        for h in HOURS:
            terms = [slot[(t, s, d, h)] for (t, s, d2, _q) in quads
                      if d2 == d if (t, s, d, h) in slot]
            seen = set()
            uniq = []
            for v in terms:
                if id(v) not in seen:
                    seen.add(id(v))
                    uniq.append(v)
            if uniq:
                model.Add(sum(uniq) <= 1)

    # Within-class teacher no-overlap (a single teacher with multiple
    # subjects in this class can't be in two slots at once).
    teachers_here = sorted({t for (t, _s, _d, _q) in quads})
    for t in teachers_here:
        for d in DAYS:
            for h in HOURS:
                terms = [slot[(t, s, d, h)]
                          for (tt, s, d2, _q) in quads
                          if tt == t and d2 == d
                             if (t, s, d, h) in slot]
                seen = set()
                uniq = []
                for v in terms:
                    if id(v) not in seen:
                        seen.add(id(v))
                        uniq.append(v)
                if uniq:
                    model.Add(sum(uniq) <= 1)

    # Locks on (*, class_name, *, *, *) force slot==1.
    for (p, _cl_l, s_l, d_l, h_l) in locks_in_class:
        v = slot.get((p, s_l, d_l, h_l))
        if v is not None:
            model.Add(v == 1)

    # Objective. For class no-overlap, the column DOES occupy
    # (cl, d, h) for any non-empty (d, h) -- we encode this with an
    # auxiliary OR boolvar. For teacher no-overlap, ditto per teacher.
    obj_terms: list = []
    # Cover reward (per (t, s, d), constant lambda across h).
    for (t, s, d, _q) in quads:
        lam = float(lambda_cover.get((t, class_name, s, d), 0.0))
        lam_int = int(round(lam * _SCALE))
        for h in HOURS:
            v = slot[(t, s, d, h)]
            if lam_int != 0:
                obj_terms.append(-lam_int * v)
            if h == _SIXTH_HOUR:
                obj_terms.append(_PENALTY_SIXTH * v)

    # Class no-overlap penalty: mu_class[(cl, d, h)] * any_slot_at(d, h).
    for d in DAYS:
        for h in HOURS:
            mu_cl = float(mu_class.get((class_name, d, h), 0.0))
            mu_int = int(round(mu_cl * _SCALE))
            if mu_int == 0:
                continue
            terms = [slot[(t, s, d, h)] for (t, s, d2, _q) in quads
                      if d2 == d if (t, s, d, h) in slot]
            seen = set()
            uniq = []
            for v in terms:
                if id(v) not in seen:
                    seen.add(id(v))
                    uniq.append(v)
            if uniq:
                # any_slot OR via an auxiliary BoolVar.
                any_v = model.NewBoolVar(
                    f"any_cl_{class_name}_{d}_{h}")
                model.Add(any_v <= sum(uniq))
                for u in uniq:
                    model.Add(any_v >= u)
                obj_terms.append(mu_int * any_v)

    # Teacher no-overlap penalty: mu_teacher[(t, d, h)] * any_slot_for_t_at(d, h).
    for t in teachers_here:
        for d in DAYS:
            for h in HOURS:
                mu_t = float(mu_teacher.get((t, d, h), 0.0))
                mu_int = int(round(mu_t * _SCALE))
                if mu_int == 0:
                    continue
                terms = [slot[(t, s, d, h)]
                          for (tt, s, d2, _q) in quads
                          if tt == t and d2 == d
                             if (t, s, d, h) in slot]
                seen = set()
                uniq = []
                for v in terms:
                    if id(v) not in seen:
                        seen.add(id(v))
                        uniq.append(v)
                if uniq:
                    any_v = model.NewBoolVar(
                        f"any_t_{t}_{d}_{h}")
                    model.Add(any_v <= sum(uniq))
                    for u in uniq:
                        model.Add(any_v >= u)
                    obj_terms.append(mu_int * any_v)

    if obj_terms:
        model.Minimize(sum(obj_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit)
    solver.parameters.num_search_workers = int(workers)
    solver.parameters.log_search_progress = False
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, 0.0

    column: dict = {}
    for (t, s, d, _q) in quads:
        for h in HOURS:
            if solver.Value(slot[(t, s, d, h)]):
                column[(t, class_name, s, d, h)] = 1

    rc = _compute_rc_dw(column, lambda_cover, mu_class, mu_teacher)
    return (column, rc) if rc < -eps else (None, rc)


def _pricing_subproblem_class_day(
    class_name: str, day: int, profs: dict, dc_value: dict,
    lambda_cover: dict, mu_class: dict, mu_teacher: dict,
    *,
    time_limit: float = 5.0,
    workers: int = 2,
    locks: set | None = None,
    group_assignments: list | None = None,
    eps: float = 1e-6,
) -> tuple[dict | None, float]:
    """CP-SAT pricer for the class-day granularity (master variant 2).

    Builds a partial pattern for ONE (class, day) cell: all the
    cattedre that need to land in `class_name` on `day`, scheduled
    against the LP duals. The output is a multi-teacher partial
    pattern (only the (*, class_name, *, day, *) entries).

    CP-SAT is ALWAYS invoked. Greedy provides a warm-start hint
    via add_hint.
    """
    from ortools.sat.python import cp_model

    pairs = _teachers_for_class(class_name, profs, dc_value,
                                 group_assignments)
    if not pairs:
        return None, 0.0

    quads: list[tuple[str, str, int]] = []  # (t, s, q_on_day)
    for (t, s) in pairs:
        q = int(dc_value.get((t, class_name, s, day), 0))
        if q > 0:
            quads.append((t, s, q))
    if not quads:
        return None, 0.0

    # Greedy WARM-START hint.
    hint_set: set = set()  # (t, s, h)
    occ_cl_h: set = set()  # h slots used in class on day
    occ_t_h: dict[str, set] = {}  # teacher -> set of h
    locks_match = [(p, cl_l, s_l, d_l, h_l)
                    for (p, cl_l, s_l, d_l, h_l) in (locks or ())
                    if cl_l == class_name and d_l == day]
    for (p, _cl, s_l, _d, h_l) in locks_match:
        hint_set.add((p, s_l, h_l))
        occ_cl_h.add(h_l)
        occ_t_h.setdefault(p, set()).add(h_l)
    for (t, s, q) in quads:
        already = sum(1 for (p, _c, sx, _d, _h) in locks_match
                       if p == t and sx == s)
        placed = already
        for h in HOURS:
            if placed >= q:
                break
            if h in occ_cl_h:
                continue
            if h in occ_t_h.get(t, set()):
                continue
            hint_set.add((t, s, h))
            occ_cl_h.add(h)
            occ_t_h.setdefault(t, set()).add(h)
            placed += 1

    model = cp_model.CpModel()
    slot: dict[tuple, cp_model.IntVar] = {}
    for (t, s, _q) in quads:
        for h in HOURS:
            v = model.NewBoolVar(
                f"slot_{t}_{class_name}_{s}_{day}_{h}")
            slot[(t, s, h)] = v
            model.AddHint(v, 1 if (t, s, h) in hint_set else 0)

    # Cattedra-hours-on-day equality.
    for (t, s, q) in quads:
        model.Add(sum(slot[(t, s, h)] for h in HOURS) == q)

    # Class no-overlap on this day.
    for h in HOURS:
        terms = [slot[(t, s, h)] for (t, s, _q) in quads
                  if (t, s, h) in slot]
        seen = set()
        uniq = []
        for v in terms:
            if id(v) not in seen:
                seen.add(id(v))
                uniq.append(v)
        if uniq:
            model.Add(sum(uniq) <= 1)

    # Within-class teacher no-overlap on this day.
    teachers_here = sorted({t for (t, _s, _q) in quads})
    for t in teachers_here:
        for h in HOURS:
            terms = [slot[(t, s, h)] for (tt, s, _q) in quads
                      if tt == t if (t, s, h) in slot]
            seen = set()
            uniq = []
            for v in terms:
                if id(v) not in seen:
                    seen.add(id(v))
                    uniq.append(v)
            if uniq:
                model.Add(sum(uniq) <= 1)

    # Locks (in-scope) forced.
    for (p, _cl, s_l, _d, h_l) in locks_match:
        v = slot.get((p, s_l, h_l))
        if v is not None:
            model.Add(v == 1)

    # Objective.
    obj_terms: list = []
    for (t, s, _q) in quads:
        lam = float(lambda_cover.get((t, class_name, s, day), 0.0))
        lam_int = int(round(lam * _SCALE))
        for h in HOURS:
            v = slot[(t, s, h)]
            if lam_int != 0:
                obj_terms.append(-lam_int * v)
            if h == _SIXTH_HOUR:
                obj_terms.append(_PENALTY_SIXTH * v)
    # Class no-overlap mu penalty.
    for h in HOURS:
        mu_cl = float(mu_class.get((class_name, day, h), 0.0))
        mu_int = int(round(mu_cl * _SCALE))
        if mu_int == 0:
            continue
        terms = [slot[(t, s, h)] for (t, s, _q) in quads
                  if (t, s, h) in slot]
        seen = set()
        uniq = []
        for v in terms:
            if id(v) not in seen:
                seen.add(id(v))
                uniq.append(v)
        if uniq:
            any_v = model.NewBoolVar(f"any_cl_{class_name}_{day}_{h}")
            model.Add(any_v <= sum(uniq))
            for u in uniq:
                model.Add(any_v >= u)
            obj_terms.append(mu_int * any_v)
    # Teacher no-overlap mu penalty.
    for t in teachers_here:
        for h in HOURS:
            mu_t = float(mu_teacher.get((t, day, h), 0.0))
            mu_int = int(round(mu_t * _SCALE))
            if mu_int == 0:
                continue
            terms = [slot[(t, s, h)] for (tt, s, _q) in quads
                      if tt == t if (t, s, h) in slot]
            seen = set()
            uniq = []
            for v in terms:
                if id(v) not in seen:
                    seen.add(id(v))
                    uniq.append(v)
            if uniq:
                any_v = model.NewBoolVar(f"any_t_{t}_{day}_{h}")
                model.Add(any_v <= sum(uniq))
                for u in uniq:
                    model.Add(any_v >= u)
                obj_terms.append(mu_int * any_v)

    if obj_terms:
        model.Minimize(sum(obj_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit)
    solver.parameters.num_search_workers = int(workers)
    solver.parameters.log_search_progress = False
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, 0.0

    column: dict = {}
    for (t, s, _q) in quads:
        for h in HOURS:
            if solver.Value(slot[(t, s, h)]):
                column[(t, class_name, s, day, h)] = 1

    rc = _compute_rc_dw(column, lambda_cover, mu_class, mu_teacher)
    return (column, rc) if rc < -eps else (None, rc)


def _pricing_subproblem_day(
    day: int, profs: dict, dc_value: dict,
    lambda_cover: dict, mu_class: dict, mu_teacher: dict,
    *,
    time_limit: float = 5.0,
    workers: int = 2,
    locks: set | None = None,
    group_assignments: list | None = None,
    eps: float = 1e-6,
) -> tuple[dict | None, float]:
    """CP-SAT pricer for the day granularity (master variant 2).

    Builds a partial pattern for ALL classes on ONE day -- the
    largest non-curriculum granularity. The output column places
    every (t, cl, s) cattedra-day with positive demand on `day`,
    optimised against the LP duals.

    CP-SAT is ALWAYS invoked. Greedy provides a warm-start hint.

    Reduced cost minimisation (integer-scaled, SCALE=100):
      Minimize sum_(t,cl,s,h) [-lam_int*slot]
             + mu_class_int * any_slot_at(cl, day, h)
             + mu_teacher_int * any_slot_at(t, day, h)
             + PENALTY_SIXTH * slot_at_h13
    """
    from ortools.sat.python import cp_model

    classes = _classes_with_demand(profs, dc_value, group_assignments)
    if not classes:
        return None, 0.0

    # Collect all (t, cl, s, q_on_day) demand quintuples.
    quads: list[tuple[str, str, str, int]] = []  # (t, cl, s, q)
    for cl in classes:
        for (t, s) in _teachers_for_class(cl, profs, dc_value,
                                            group_assignments):
            q = int(dc_value.get((t, cl, s, day), 0))
            if q > 0:
                quads.append((t, cl, s, q))
    if not quads:
        return None, 0.0

    # Greedy WARM-START: place each (t, cl, s) in the first
    # non-conflicting hour, respecting class no-overlap and
    # teacher no-overlap on this day.
    hint_set: set = set()  # (t, cl, s, h)
    occ_cl_h: dict[str, set] = {}  # class -> set of h used
    occ_t_h: dict[str, set] = {}   # teacher -> set of h used
    locks_match = [(p, cl_l, s_l, d_l, h_l)
                    for (p, cl_l, s_l, d_l, h_l) in (locks or ())
                    if d_l == day]
    for (p, cl_l, s_l, _d, h_l) in locks_match:
        hint_set.add((p, cl_l, s_l, h_l))
        occ_cl_h.setdefault(cl_l, set()).add(h_l)
        occ_t_h.setdefault(p, set()).add(h_l)
    for (t, cl, s, q) in quads:
        already = sum(1 for (p, cl_x, sx, _d, _h) in locks_match
                       if p == t and cl_x == cl and sx == s)
        placed = already
        for h in HOURS:
            if placed >= q:
                break
            if h in occ_cl_h.get(cl, set()):
                continue
            if h in occ_t_h.get(t, set()):
                continue
            hint_set.add((t, cl, s, h))
            occ_cl_h.setdefault(cl, set()).add(h)
            occ_t_h.setdefault(t, set()).add(h)
            placed += 1

    model = cp_model.CpModel()
    slot: dict[tuple, cp_model.IntVar] = {}
    for (t, cl, s, _q) in quads:
        for h in HOURS:
            v = model.NewBoolVar(f"slot_{t}_{cl}_{s}_{day}_{h}")
            slot[(t, cl, s, h)] = v
            model.AddHint(v, 1 if (t, cl, s, h) in hint_set else 0)

    # Cattedra-hours-on-day equality.
    for (t, cl, s, q) in quads:
        model.Add(sum(slot[(t, cl, s, h)] for h in HOURS) == q)

    # Class no-overlap on this day.
    classes_here = sorted({cl for (_t, cl, _s, _q) in quads})
    for cl in classes_here:
        for h in HOURS:
            terms = [slot[(t, cl, s, h)]
                      for (t, cl_x, s, _q) in quads
                      if cl_x == cl if (t, cl, s, h) in slot]
            seen = set()
            uniq = []
            for v in terms:
                if id(v) not in seen:
                    seen.add(id(v))
                    uniq.append(v)
            if uniq:
                model.Add(sum(uniq) <= 1)

    # Teacher no-overlap on this day.
    teachers_here = sorted({t for (t, _cl, _s, _q) in quads})
    for t in teachers_here:
        for h in HOURS:
            terms = [slot[(t, cl, s, h)]
                      for (tt, cl, s, _q) in quads
                      if tt == t if (t, cl, s, h) in slot]
            seen = set()
            uniq = []
            for v in terms:
                if id(v) not in seen:
                    seen.add(id(v))
                    uniq.append(v)
            if uniq:
                model.Add(sum(uniq) <= 1)

    # Locks (in-scope) forced.
    for (p, cl_l, s_l, _d, h_l) in locks_match:
        v = slot.get((p, cl_l, s_l, h_l))
        if v is not None:
            model.Add(v == 1)

    # Objective.
    obj_terms: list = []
    for (t, cl, s, _q) in quads:
        lam = float(lambda_cover.get((t, cl, s, day), 0.0))
        lam_int = int(round(lam * _SCALE))
        for h in HOURS:
            v = slot[(t, cl, s, h)]
            if lam_int != 0:
                obj_terms.append(-lam_int * v)
            if h == _SIXTH_HOUR:
                obj_terms.append(_PENALTY_SIXTH * v)
    # Class no-overlap mu penalty (per-class on this day).
    for cl in classes_here:
        for h in HOURS:
            mu_cl = float(mu_class.get((cl, day, h), 0.0))
            mu_int = int(round(mu_cl * _SCALE))
            if mu_int == 0:
                continue
            terms = [slot[(t, cl, s, h)]
                      for (t, cl_x, s, _q) in quads
                      if cl_x == cl if (t, cl, s, h) in slot]
            seen = set()
            uniq = []
            for v in terms:
                if id(v) not in seen:
                    seen.add(id(v))
                    uniq.append(v)
            if uniq:
                any_v = model.NewBoolVar(f"any_cl_{cl}_{day}_{h}")
                model.Add(any_v <= sum(uniq))
                for u in uniq:
                    model.Add(any_v >= u)
                obj_terms.append(mu_int * any_v)
    # Teacher no-overlap mu penalty (per-teacher on this day).
    for t in teachers_here:
        for h in HOURS:
            mu_t = float(mu_teacher.get((t, day, h), 0.0))
            mu_int = int(round(mu_t * _SCALE))
            if mu_int == 0:
                continue
            terms = [slot[(t, cl, s, h)]
                      for (tt, cl, s, _q) in quads
                      if tt == t if (t, cl, s, h) in slot]
            seen = set()
            uniq = []
            for v in terms:
                if id(v) not in seen:
                    seen.add(id(v))
                    uniq.append(v)
            if uniq:
                any_v = model.NewBoolVar(f"any_t_{t}_{day}_{h}")
                model.Add(any_v <= sum(uniq))
                for u in uniq:
                    model.Add(any_v >= u)
                obj_terms.append(mu_int * any_v)

    if obj_terms:
        model.Minimize(sum(obj_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit)
    solver.parameters.num_search_workers = int(workers)
    solver.parameters.log_search_progress = False
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, 0.0

    column: dict = {}
    for (t, cl, s, _q) in quads:
        for h in HOURS:
            if solver.Value(slot[(t, cl, s, h)]):
                column[(t, cl, s, day, h)] = 1

    rc = _compute_rc_dw(column, lambda_cover, mu_class, mu_teacher)
    return (column, rc) if rc < -eps else (None, rc)


def _pricing_subproblem_curriculum(
    curriculum_id: str, profs: dict, dc_value: dict,
    lambda_cover: dict, mu_class: dict, mu_teacher: dict,
    *,
    class_to_curriculum: dict[str, str] | None = None,
    time_limit: float = 5.0,
    workers: int = 2,
    locks: set | None = None,
    group_assignments: list | None = None,
    eps: float = 1e-6,
) -> tuple[dict | None, float]:
    """CP-SAT pricer for the curriculum granularity (master variant 2).

    Builds a partial pattern that schedules ALL the cattedre of the
    classes belonging to `curriculum_id` -- the natural granularity
    for Italian schools where `indirizzi` (Liceo Scientifico, Classico,
    Linguistico, ITIS Informatica, ...) form natural blocks of mostly-
    disjoint teacher pools (greco/latino solo nel classico, scienze
    applicate solo nello scientifico-applicate, ...).

    `class_to_curriculum` maps class_name -> curriculum_id. If the
    map is None or empty, the pricer treats ALL classes as a single
    cluster (degenerate fallback -- callers should provide a real
    map).

    CP-SAT is ALWAYS invoked. Greedy provides a warm-start hint.
    """
    from ortools.sat.python import cp_model

    all_classes = _classes_with_demand(profs, dc_value, group_assignments)
    if class_to_curriculum:
        classes = sorted([
            c for c in all_classes
            if class_to_curriculum.get(c) == curriculum_id
        ])
    else:
        classes = list(all_classes)
    if not classes:
        return None, 0.0

    # Collect demand quintuples (t, cl, s, d, q) for the curriculum's
    # classes.
    quints: list[tuple[str, str, str, int, int]] = []  # (t, cl, s, d, q)
    for cl in classes:
        for (t, s) in _teachers_for_class(cl, profs, dc_value,
                                            group_assignments):
            for d in DAYS:
                q = int(dc_value.get((t, cl, s, d), 0))
                if q > 0:
                    quints.append((t, cl, s, d, q))
    if not quints:
        return None, 0.0

    # Greedy WARM-START: place each (t, cl, s, d) sequentially in
    # the first non-conflicting (cl, d, h) and (t, d, h) slot.
    hint_set: set = set()  # (t, cl, s, d, h)
    occ_cl: dict[str, set] = {}  # class -> {(d, h)}
    occ_t: dict[str, set] = {}   # teacher -> {(d, h)}
    locks_match = [(p, cl_l, s_l, d_l, h_l)
                    for (p, cl_l, s_l, d_l, h_l) in (locks or ())
                    if cl_l in classes]
    for (p, cl_l, s_l, d_l, h_l) in locks_match:
        hint_set.add((p, cl_l, s_l, d_l, h_l))
        occ_cl.setdefault(cl_l, set()).add((d_l, h_l))
        occ_t.setdefault(p, set()).add((d_l, h_l))
    for (t, cl, s, d, q) in quints:
        already = sum(1 for (p, cl_x, sx, dx, _h) in locks_match
                       if p == t and cl_x == cl and sx == s and dx == d)
        placed = already
        for h in HOURS:
            if placed >= q:
                break
            if (d, h) in occ_cl.get(cl, set()):
                continue
            if (d, h) in occ_t.get(t, set()):
                continue
            hint_set.add((t, cl, s, d, h))
            occ_cl.setdefault(cl, set()).add((d, h))
            occ_t.setdefault(t, set()).add((d, h))
            placed += 1

    model = cp_model.CpModel()
    slot: dict[tuple, cp_model.IntVar] = {}
    for (t, cl, s, d, _q) in quints:
        for h in HOURS:
            v = model.NewBoolVar(f"slot_{t}_{cl}_{s}_{d}_{h}")
            slot[(t, cl, s, d, h)] = v
            model.AddHint(v, 1 if (t, cl, s, d, h) in hint_set else 0)

    # Cattedra-hours-on-day equality.
    for (t, cl, s, d, q) in quints:
        model.Add(sum(slot[(t, cl, s, d, h)] for h in HOURS) == q)

    # Class no-overlap (per cl, d, h).
    classes_here = sorted({cl for (_t, cl, _s, _d, _q) in quints})
    for cl in classes_here:
        for d in DAYS:
            for h in HOURS:
                terms = [slot[(t, cl, s, d, h)]
                          for (t, cl_x, s, d_x, _q) in quints
                          if cl_x == cl and d_x == d
                             if (t, cl, s, d, h) in slot]
                seen = set()
                uniq = []
                for v in terms:
                    if id(v) not in seen:
                        seen.add(id(v))
                        uniq.append(v)
                if uniq:
                    model.Add(sum(uniq) <= 1)

    # Teacher no-overlap (per t, d, h within the curriculum).
    teachers_here = sorted({t for (t, _cl, _s, _d, _q) in quints})
    for t in teachers_here:
        for d in DAYS:
            for h in HOURS:
                terms = [slot[(t, cl, s, d, h)]
                          for (tt, cl, s, d_x, _q) in quints
                          if tt == t and d_x == d
                             if (t, cl, s, d, h) in slot]
                seen = set()
                uniq = []
                for v in terms:
                    if id(v) not in seen:
                        seen.add(id(v))
                        uniq.append(v)
                if uniq:
                    model.Add(sum(uniq) <= 1)

    # Locks (in-scope) forced.
    for (p, cl_l, s_l, d_l, h_l) in locks_match:
        v = slot.get((p, cl_l, s_l, d_l, h_l))
        if v is not None:
            model.Add(v == 1)

    # Objective.
    obj_terms: list = []
    for (t, cl, s, d, _q) in quints:
        lam = float(lambda_cover.get((t, cl, s, d), 0.0))
        lam_int = int(round(lam * _SCALE))
        for h in HOURS:
            v = slot[(t, cl, s, d, h)]
            if lam_int != 0:
                obj_terms.append(-lam_int * v)
            if h == _SIXTH_HOUR:
                obj_terms.append(_PENALTY_SIXTH * v)

    # Class no-overlap mu penalty.
    for cl in classes_here:
        for d in DAYS:
            for h in HOURS:
                mu_cl = float(mu_class.get((cl, d, h), 0.0))
                mu_int = int(round(mu_cl * _SCALE))
                if mu_int == 0:
                    continue
                terms = [slot[(t, cl, s, d, h)]
                          for (t, cl_x, s, d_x, _q) in quints
                          if cl_x == cl and d_x == d
                             if (t, cl, s, d, h) in slot]
                seen = set()
                uniq = []
                for v in terms:
                    if id(v) not in seen:
                        seen.add(id(v))
                        uniq.append(v)
                if uniq:
                    any_v = model.NewBoolVar(f"any_cl_{cl}_{d}_{h}")
                    model.Add(any_v <= sum(uniq))
                    for u in uniq:
                        model.Add(any_v >= u)
                    obj_terms.append(mu_int * any_v)
    # Teacher no-overlap mu penalty.
    for t in teachers_here:
        for d in DAYS:
            for h in HOURS:
                mu_t = float(mu_teacher.get((t, d, h), 0.0))
                mu_int = int(round(mu_t * _SCALE))
                if mu_int == 0:
                    continue
                terms = [slot[(t, cl, s, d, h)]
                          for (tt, cl, s, d_x, _q) in quints
                          if tt == t and d_x == d
                             if (t, cl, s, d, h) in slot]
                seen = set()
                uniq = []
                for v in terms:
                    if id(v) not in seen:
                        seen.add(id(v))
                        uniq.append(v)
                if uniq:
                    any_v = model.NewBoolVar(f"any_t_{t}_{d}_{h}")
                    model.Add(any_v <= sum(uniq))
                    for u in uniq:
                        model.Add(any_v >= u)
                    obj_terms.append(mu_int * any_v)

    if obj_terms:
        model.Minimize(sum(obj_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit)
    solver.parameters.num_search_workers = int(workers)
    solver.parameters.log_search_progress = False
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, 0.0

    column: dict = {}
    for (t, cl, s, d, _q) in quints:
        for h in HOURS:
            if solver.Value(slot[(t, cl, s, d, h)]):
                column[(t, cl, s, d, h)] = 1

    rc = _compute_rc_dw(column, lambda_cover, mu_class, mu_teacher)
    return (column, rc) if rc < -eps else (None, rc)


# ---------------- BP loop: dispatcher + driver ----------------

# Module-level context for the curriculum pricer. The BP loop sets
# this to a {class_name -> curriculum_id} dict before invoking the
# enumerator/dispatcher, then clears it. This avoids bloating every
# helper signature for a parameter only used by one granularity.
_CLASS_TO_CURRICULUM_CTX: dict = {"map": None}


_BP_GRANULARITIES = (
    "teacher-class",
    "teacher-class-subject",
    "teacher-subject",
    "teacher-day",
    "class",
    "class-day",
    "day",
    "curriculum",
)

# Granularities whose columns are MULTI-teacher partial patterns
# and therefore require master variant 2 (DW with overlap ineqs).
_BP_GRANULARITIES_DW = ("class", "class-day", "day", "curriculum")


def _enumerate_pricing_keys(granularity: str, profs: dict,
                             dc_value: dict,
                             group_assignments: list | None
                             ) -> list:
    """Return the list of pricing keys for the chosen granularity.
    The BP loop calls _solve_pricing once per key and accepts the
    returned column when its reduced cost is < -eps.
    """
    pairs_by_t = _profs_iter_with_groups(profs, group_assignments)
    if granularity == "teacher-class":
        out = []
        for t, pairs in pairs_by_t.items():
            for cl in sorted({c for (c, _s) in pairs}):
                if any(dc_value.get((t, cl, s, d), 0) > 0
                        for (cc, s) in pairs if cc == cl
                        for d in DAYS):
                    out.append((t, cl))
        return sorted(out)
    if granularity == "teacher-class-subject":
        out = []
        for t, pairs in pairs_by_t.items():
            for (cl, s) in pairs:
                if any(dc_value.get((t, cl, s, d), 0) > 0
                        for d in DAYS):
                    out.append((t, cl, s))
        return sorted(out)
    if granularity == "teacher-subject":
        out = []
        for t, pairs in pairs_by_t.items():
            subjects = sorted({s for (_cl, s) in pairs})
            for s in subjects:
                if any(dc_value.get((t, cl, s, d), 0) > 0
                        for (cc, ss) in pairs if ss == s
                        for cl in [cc]
                        for d in DAYS):
                    out.append((t, s))
        return sorted(out)
    if granularity == "teacher-day":
        out = []
        for t, pairs in pairs_by_t.items():
            for d in DAYS:
                if any(dc_value.get((t, cl, s, d), 0) > 0
                        for (cl, s) in pairs):
                    out.append((t, d))
        return sorted(out)
    if granularity == "class":
        return _classes_with_demand(profs, dc_value, group_assignments)
    if granularity == "class-day":
        out = []
        classes = _classes_with_demand(profs, dc_value, group_assignments)
        for cl in classes:
            for d in DAYS:
                if any(dc_value.get((t, cl, s, d), 0) > 0
                        for (t, s) in _teachers_for_class(
                            cl, profs, dc_value, group_assignments)):
                    out.append((cl, d))
        return sorted(out)
    if granularity == "day":
        return list(DAYS)
    if granularity == "curriculum":
        # If we have class_to_curriculum mapping, return distinct
        # curriculum IDs that have at least one class with demand.
        # Otherwise fall back to a single "_all" pseudo-curriculum.
        # The mapping is threaded by the BP loop via the global
        # _class_to_curriculum parameter (see _run_branch_and_price_dw).
        c2c = _CLASS_TO_CURRICULUM_CTX.get("map") or {}
        if c2c:
            classes = _classes_with_demand(profs, dc_value, group_assignments)
            cur_ids = sorted({c2c[c] for c in classes
                                if c in c2c})
            return cur_ids
        return ["_all"]
    raise NotImplementedError(
        f"granularity {granularity!r} pricing not yet implemented")


def _solve_pricing(granularity: str, key,
                    profs: dict, dc_value: dict,
                    lambda_duals: dict, mu_duals: dict,
                    *,
                    time_limit: float = 5.0,
                    workers: int = 2,
                    locks: set | None = None,
                    group_assignments: list | None = None,
                    eps: float = 1e-6,
                    ) -> tuple[dict | None, float]:
    """Dispatch a pricing call to the right per-granularity solver."""
    if granularity == "teacher-class":
        teacher, class_name = key
        mu_t = float(mu_duals.get(teacher, 0.0))
        return _pricing_subproblem_teacher_class(
            teacher, class_name, profs, dc_value,
            lambda_duals, mu_t,
            time_limit=time_limit, workers=workers,
            locks=locks, group_assignments=group_assignments,
            eps=eps,
        )
    if granularity == "teacher-class-subject":
        teacher, class_name, subject = key
        mu_t = float(mu_duals.get(teacher, 0.0))
        return _pricing_subproblem_teacher_class_subject(
            teacher, class_name, subject, profs, dc_value,
            lambda_duals, mu_t,
            time_limit=time_limit, workers=workers,
            locks=locks, group_assignments=group_assignments,
            eps=eps,
        )
    if granularity == "teacher-subject":
        teacher, subject = key
        mu_t = float(mu_duals.get(teacher, 0.0))
        return _pricing_subproblem_teacher_subject(
            teacher, subject, profs, dc_value,
            lambda_duals, mu_t,
            time_limit=time_limit, workers=workers,
            locks=locks, group_assignments=group_assignments,
            eps=eps,
        )
    if granularity == "teacher-day":
        teacher, day = key
        mu_t = float(mu_duals.get(teacher, 0.0))
        return _pricing_subproblem_teacher_day(
            teacher, day, profs, dc_value,
            lambda_duals, mu_t,
            time_limit=time_limit, workers=workers,
            locks=locks, group_assignments=group_assignments,
            eps=eps,
        )
    raise NotImplementedError(
        f"_solve_pricing: granularity {granularity!r} not implemented")


def _solve_pricing_dw(granularity: str, key,
                      profs: dict, dc_value: dict,
                      lambda_cover: dict, mu_class: dict,
                      mu_teacher: dict,
                      *,
                      time_limit: float = 5.0,
                      workers: int = 2,
                      locks: set | None = None,
                      group_assignments: list | None = None,
                      eps: float = 1e-6,
                      ) -> tuple[dict | None, float]:
    """Dispatch a master-variant-2 (DW) pricing call. Used by BP for
    granularities whose columns span multiple teachers."""
    if granularity == "class":
        class_name = key
        return _pricing_subproblem_class(
            class_name, profs, dc_value,
            lambda_cover, mu_class, mu_teacher,
            time_limit=time_limit, workers=workers,
            locks=locks, group_assignments=group_assignments,
            eps=eps,
        )
    if granularity == "class-day":
        class_name, day = key
        return _pricing_subproblem_class_day(
            class_name, day, profs, dc_value,
            lambda_cover, mu_class, mu_teacher,
            time_limit=time_limit, workers=workers,
            locks=locks, group_assignments=group_assignments,
            eps=eps,
        )
    if granularity == "day":
        day = key
        return _pricing_subproblem_day(
            day, profs, dc_value,
            lambda_cover, mu_class, mu_teacher,
            time_limit=time_limit, workers=workers,
            locks=locks, group_assignments=group_assignments,
            eps=eps,
        )
    if granularity == "curriculum":
        curriculum_id = key
        return _pricing_subproblem_curriculum(
            curriculum_id, profs, dc_value,
            lambda_cover, mu_class, mu_teacher,
            class_to_curriculum=_CLASS_TO_CURRICULUM_CTX.get("map"),
            time_limit=time_limit, workers=workers,
            locks=locks, group_assignments=group_assignments,
            eps=eps,
        )
    raise NotImplementedError(
        f"_solve_pricing_dw: granularity {granularity!r} not implemented")


def _run_branch_and_price(
    patterns: dict, profs: dict, dc_value: dict,
    *,
    granularity: str,
    bp_max_iterations: int,
    pricer_time_limit: float,
    pricer_workers: int,
    locks: set | None,
    group_assignments: list | None,
    time_budget_s: float,
    t0: float,
    eps: float = 1e-6,
    log: bool = True,
) -> tuple[dict, float, dict[str, int], dict]:
    """Real Branch-and-Price loop (no Ryan-Foster yet -- next
    commit). Iteratively:
      1. Solve master LP with extended duals.
      2. For each pricing key (per the chosen granularity), call
         the matching CP-SAT pricer and append improving columns.
      3. Repeat until no improving column or budget exhausted.

    Returns (patterns_updated, best_obj, best_selection, info_extras).
    The patterns dict is mutated in place AND returned.
    """
    info: dict[str, Any] = {
        "bp_iterations_done": 0,
        "bp_columns_added_total": 0,
        "bp_lp_obj_per_iter": [],
        "bp_min_rc_per_iter": [],
        "bp_terminated_reason": "",
    }

    sel, obj, lam, mu, _x, _cols = _solve_master(
        patterns, profs, dc_value, return_extended=True)
    if sel is None:
        info["bp_terminated_reason"] = "master_infeasible_at_entry"
        return patterns, float("inf"), {}, info
    best_obj = float(obj)
    best_selection = dict(sel)
    info["bp_lp_obj_per_iter"].append(best_obj)

    for it in range(1, bp_max_iterations + 1):
        if time.time() - t0 > time_budget_s:
            info["bp_terminated_reason"] = "time_budget"
            break
        try:
            keys = _enumerate_pricing_keys(
                granularity, profs, dc_value, group_assignments)
        except NotImplementedError as e:
            info["bp_terminated_reason"] = (
                f"granularity_not_implemented:{granularity}")
            if log:
                print(f"[CG.BP] {e}")
            break

        added = 0
        min_rc = 0.0
        for key in keys:
            if time.time() - t0 > time_budget_s:
                break
            try:
                pat, rc = _solve_pricing(
                    granularity, key, profs, dc_value, lam, mu,
                    time_limit=pricer_time_limit,
                    workers=pricer_workers,
                    locks=locks,
                    group_assignments=group_assignments,
                    eps=eps,
                )
            except NotImplementedError:
                info["bp_terminated_reason"] = (
                    f"granularity_not_implemented:{granularity}")
                break
            if rc < min_rc:
                min_rc = rc
            if pat is None:
                continue
            # The pricer always emits a single-teacher pattern;
            # find the teacher and append.
            teachers_in_pat = {k[0] for k in pat.keys()}
            if len(teachers_in_pat) != 1:
                # Defensive: skip multi-teacher columns until master
                # variant 2 lands.
                continue
            tname = next(iter(teachers_in_pat))
            existing = patterns.setdefault(tname, [])
            if pat not in existing:
                existing.append(pat)
                added += 1
        info["bp_iterations_done"] = it
        info["bp_columns_added_total"] += added
        info["bp_min_rc_per_iter"].append(min_rc)

        if added == 0:
            info["bp_terminated_reason"] = "no_improving_column"
            break

        sel_it, obj_it, lam_it, mu_it, _x, _cols = _solve_master(
            patterns, profs, dc_value, return_extended=True)
        if sel_it is None:
            info["bp_terminated_reason"] = (
                f"master_infeasible_at_iter_{it}")
            break
        info["bp_lp_obj_per_iter"].append(float(obj_it))
        if obj_it < best_obj - eps:
            best_obj = float(obj_it)
            best_selection = dict(sel_it)
            lam, mu = lam_it, mu_it
            if log:
                print(f"[CG.BP iter {it}] obj -> {best_obj:.1f}, "
                      f"+{added} cols, min_rc={min_rc:.3f}")
        else:
            lam, mu = lam_it, mu_it
            if log:
                print(f"[CG.BP iter {it}] plateau ({obj_it:.1f}), "
                      f"+{added} cols, min_rc={min_rc:.3f}")
            if min_rc > -10.0 * eps:
                info["bp_terminated_reason"] = "rc_plateau"
                break

    if not info["bp_terminated_reason"]:
        info["bp_terminated_reason"] = "max_iterations"
    return patterns, best_obj, best_selection, info


# ---------------- Ryan-Foster branching (DW path) ----------------
#
# After the BP-DW loop converges to LP optimum, the fractional
# weights x[col] can leave the LP solution non-integer. The
# integer recovery via greedy set-packing may give a much worse
# objective than the LP. Ryan-Foster branching closes the gap by
# picking a pair of "elements" (slots in our case) that are
# covered "fractionally together" by some columns, then exploring
# two branches:
#   - together: any selected column must cover BOTH or NEITHER
#                of the pair. Columns covering exactly one are
#                removed from the pool for this branch.
#   - apart:    no selected column covers BOTH. Columns covering
#                both are removed from the pool for this branch.
#
# Achterberg-style pair scoring: for a pair (i, j), let
#   s(i, j) = sum_(p covers both i and j) x[p]
# The "most fractional" pair maximises s(i, j) * (1 - s(i, j)),
# which peaks at s = 0.5 (the LP is most divided on whether to
# cover both).


def _achterberg_pair_score(
    columns: list[dict], lp_x: list[float],
) -> tuple | None:
    """Find the most fractional class-slot pair (i, j) in a DW LP
    solution. Returns ((cl, d1, h1), (cl, d2, h2), score) or None
    if no fractional pair exists (LP is already integer-tight).

    Pairs are restricted to slots within the SAME class: branching
    on cross-class pairs is much weaker because most columns don't
    interact across classes.
    """
    eps = 1e-6
    # Per-column class-slot incidence; only columns with x > 0.
    col_slots: list[tuple[float, set]] = []
    for j, col in enumerate(columns):
        x = float(lp_x[j]) if j < len(lp_x) else 0.0
        if x <= eps:
            continue
        slots = set()
        for (_p, cl, _s, d, h), v in col.items():
            if v:
                slots.add((cl, d, h))
        col_slots.append((x, slots))

    # Aggregate pair-cover sums (only same-class pairs).
    pair_sum: dict[tuple, float] = {}
    for x, slots in col_slots:
        slist = sorted(slots)
        n = len(slist)
        for i in range(n):
            for k in range(i + 1, n):
                a, b = slist[i], slist[k]
                if a[0] != b[0]:
                    continue  # not same class
                pair_sum[(a, b)] = pair_sum.get((a, b), 0.0) + x

    # Achterberg-style score: s * (1 - s).
    best = None
    for (a, b), s in pair_sum.items():
        if s <= eps or s >= 1 - eps:
            continue
        score = s * (1 - s)
        if best is None or score > best[2]:
            best = (a, b, score)
    return best


def _filter_columns_together(
    columns: list[dict],
    item_a: tuple, item_b: tuple,
) -> list[dict]:
    """Keep columns that cover BOTH or NEITHER of (item_a, item_b).
    item_a, item_b are (cl, d, h) tuples."""
    out = []
    for col in columns:
        slots = set()
        for (_p, cl, _s, d, h), v in col.items():
            if v:
                slots.add((cl, d, h))
        ca = item_a in slots
        cb = item_b in slots
        if ca == cb:  # both true OR both false
            out.append(col)
    return out


def _filter_columns_apart(
    columns: list[dict],
    item_a: tuple, item_b: tuple,
) -> list[dict]:
    """Keep columns that do NOT cover both (item_a, item_b)."""
    out = []
    for col in columns:
        slots = set()
        for (_p, cl, _s, d, h), v in col.items():
            if v:
                slots.add((cl, d, h))
        if not (item_a in slots and item_b in slots):
            out.append(col)
    return out


def _ryan_foster_branch_dw(
    columns: list[dict], lp_x: list[float], profs: dict,
    dc_value: dict,
    *,
    log: bool = True,
) -> tuple[dict | None, dict]:
    """One level of Ryan-Foster branching on the DW LP. After the
    BP loop converges, find the most fractional class-slot pair
    (Achterberg score), explore two branches (together / apart),
    pick the better integer recovery.

    Kept for backward compatibility / unit tests; the production
    BP path uses `_run_ryan_foster_tree` (full recursive
    branch-and-bound tree).

    Returns (sol_dict, branch_info) -- sol_dict is the better
    integer-feasible solution from the two branches, or None if
    neither produced anything HARD-feasible.
    """
    info: dict[str, Any] = {
        "rf_pair": None,
        "rf_score": None,
        "rf_together_n_cols": 0,
        "rf_apart_n_cols": 0,
        "rf_together_obj": None,
        "rf_apart_obj": None,
    }
    pair = _achterberg_pair_score(columns, lp_x)
    if pair is None:
        info["rf_terminated_reason"] = "lp_already_integer"
        return None, info
    item_a, item_b, score = pair
    info["rf_pair"] = (item_a, item_b)
    info["rf_score"] = float(score)

    # Branch 1: together
    cols_t = _filter_columns_together(columns, item_a, item_b)
    info["rf_together_n_cols"] = len(cols_t)
    sol_t = None
    if cols_t:
        res_t = _solve_master_dw(cols_t, dc_value)
        if res_t[0] is not None:
            lp_x_t, obj_t, _lam = res_t
            sol_t = _integer_recover_dw(cols_t, lp_x_t, dc_value)
            info["rf_together_obj"] = float(obj_t)

    # Branch 2: apart
    cols_a = _filter_columns_apart(columns, item_a, item_b)
    info["rf_apart_n_cols"] = len(cols_a)
    sol_a = None
    if cols_a:
        res_a = _solve_master_dw(cols_a, dc_value)
        if res_a[0] is not None:
            lp_x_a, obj_a, _lam = res_a
            sol_a = _integer_recover_dw(cols_a, lp_x_a, dc_value)
            info["rf_apart_obj"] = float(obj_a)

    # Pick the better HARD-feasible solution.
    candidates = []
    for sol, label in ((sol_t, "together"), (sol_a, "apart")):
        if not sol:
            continue
        if not meta.is_hard_feasible(sol, profs, verbose=False):
            continue
        v, _ = meta.compute_soft(sol, profs)
        candidates.append((float(v), sol, label))
    if not candidates:
        info["rf_terminated_reason"] = "no_feasible_branch"
        return None, info
    candidates.sort(key=lambda x: x[0])
    best = candidates[0]
    info["rf_chosen_branch"] = best[2]
    info["rf_chosen_obj"] = best[0]
    if log:
        print(f"[CG.BP-DW.RF] pair={item_a} ~ {item_b}, "
              f"score={score:.3f}, "
              f"together_obj={info['rf_together_obj']}, "
              f"apart_obj={info['rf_apart_obj']}, "
              f"chose '{best[2]}' (soft={best[0]:.1f})")
    return best[1], info


def _run_ryan_foster_tree(
    initial_columns: list[dict], profs: dict, dc_value: dict,
    *,
    max_depth: int = 20,
    max_nodes: int = 1000,
    time_budget_s: float = 60.0,
    t0: float | None = None,
    eps: float = 1e-6,
    log: bool = True,
) -> tuple[dict | None, dict]:
    """Full recursive Ryan-Foster tree on the DW master LP.

    Best-first node exploration: priority queue ordered by LP bound
    (lower = explore first, since we minimise). Each node holds:
      - column pool (subset of `initial_columns` after the branch
        constraints applied)
      - depth in the branching tree
    At each node:
      1. Solve master variant 2 LP -> (lp_x, lp_obj, duals).
      2. If lp_obj >= incumbent: prune (bound-prune).
      3. Try greedy set-packing integer recovery; if HARD-feasible
         and beats incumbent -> update incumbent.
      4. If LP is integer (Achterberg pair score = None) -> done
         exploring this node.
      5. Otherwise pick the most-fractional class-slot pair (i, j)
         and spawn two child nodes:
            - together: columns must cover BOTH or NEITHER of i, j
            - apart:    no column covers BOTH
         Each child is queued only if its LP bound is < incumbent.

    Termination conditions (any one ends the tree):
      - Queue empty (proven optimal under the column pool).
      - max_nodes nodes explored.
      - max_depth reached on every leaf.
      - time_budget_s exhausted.

    Returns (incumbent_sol, info) -- incumbent_sol is the best
    HARD-feasible integer solution found, or None if the tree found
    nothing better than the root LP.
    """
    import heapq

    if t0 is None:
        t0 = time.time()
    info: dict[str, Any] = {
        "rf_tree_nodes_explored": 0,
        "rf_tree_nodes_pruned": 0,
        "rf_tree_nodes_infeasible": 0,
        "rf_tree_max_depth_reached": 0,
        "rf_tree_incumbent_obj": None,
        "rf_tree_incumbents_found": 0,
        "rf_tree_terminated_reason": "",
    }

    # Initial LP solve at root.
    res = _solve_master_dw(initial_columns, dc_value)
    if res[0] is None:
        info["rf_tree_terminated_reason"] = "root_infeasible"
        return None, info

    incumbent_sol = None
    incumbent_obj = float("inf")

    # Priority queue: (lp_bound, counter, columns, depth).
    # `counter` breaks ties so heapq doesn't try to compare lists.
    counter = 0
    pq: list = [(float(res[1]), counter, list(initial_columns), 0)]

    while pq:
        if time.time() - t0 > time_budget_s:
            info["rf_tree_terminated_reason"] = "time_budget"
            break
        if info["rf_tree_nodes_explored"] >= max_nodes:
            info["rf_tree_terminated_reason"] = "max_nodes"
            break

        node_lb, _ctr, node_cols, depth = heapq.heappop(pq)
        info["rf_tree_nodes_explored"] += 1
        info["rf_tree_max_depth_reached"] = max(
            info["rf_tree_max_depth_reached"], depth)

        # Bound-prune: a node whose LP bound already exceeds the
        # incumbent cannot produce a strictly better integer sol.
        if node_lb >= incumbent_obj - eps:
            info["rf_tree_nodes_pruned"] += 1
            continue

        # Re-solve master at this node (the queued bound came from a
        # previous solve; an updated solve gives current duals + x).
        node_res = _solve_master_dw(node_cols, dc_value)
        if node_res[0] is None:
            info["rf_tree_nodes_infeasible"] += 1
            continue
        lp_x, lp_obj, _lam = node_res

        # Greedy set-packing integer recovery at this node.
        rec_sol = _integer_recover_dw(node_cols, lp_x, dc_value)
        if rec_sol and meta.is_hard_feasible(rec_sol, profs, verbose=False):
            v, _ = meta.compute_soft(rec_sol, profs)
            if float(v) < incumbent_obj - eps:
                incumbent_obj = float(v)
                incumbent_sol = rec_sol
                info["rf_tree_incumbents_found"] += 1
                if log:
                    print(f"[RF tree] depth={depth} new incumbent "
                          f"obj={incumbent_obj:.1f} "
                          f"(node lp_obj={lp_obj:.1f})")

        # Don't branch deeper than max_depth.
        if depth >= max_depth:
            continue

        # Find a fractional class-slot pair to branch on.
        pair = _achterberg_pair_score(node_cols, lp_x)
        if pair is None:
            continue  # LP integer at this node -> nothing to branch on
        item_a, item_b, score = pair

        for child_cols, label in (
            (_filter_columns_together(node_cols, item_a, item_b), "tog"),
            (_filter_columns_apart(node_cols, item_a, item_b), "apt"),
        ):
            if not child_cols:
                continue
            if time.time() - t0 > time_budget_s:
                break
            child_res = _solve_master_dw(child_cols, dc_value)
            if child_res[0] is None:
                info["rf_tree_nodes_infeasible"] += 1
                continue
            child_lb = float(child_res[1])
            if child_lb >= incumbent_obj - eps:
                info["rf_tree_nodes_pruned"] += 1
                continue
            counter += 1
            heapq.heappush(
                pq, (child_lb, counter, child_cols, depth + 1))

    if not info["rf_tree_terminated_reason"]:
        info["rf_tree_terminated_reason"] = "queue_exhausted"
    info["rf_tree_incumbent_obj"] = (
        incumbent_obj if incumbent_obj != float("inf") else None)
    if log:
        print(f"[RF tree] terminated: {info['rf_tree_terminated_reason']}, "
              f"explored={info['rf_tree_nodes_explored']}, "
              f"pruned={info['rf_tree_nodes_pruned']}, "
              f"infeasible={info['rf_tree_nodes_infeasible']}, "
              f"max_depth={info['rf_tree_max_depth_reached']}, "
              f"incumbent={info['rf_tree_incumbent_obj']}")
    return incumbent_sol, info


def _run_branch_and_price_dw(
    columns_initial: list[dict], profs: dict, dc_value: dict,
    *,
    granularity: str,
    bp_max_iterations: int,
    pricer_time_limit: float,
    pricer_workers: int,
    locks: set | None,
    group_assignments: list | None,
    time_budget_s: float,
    t0: float,
    eps: float = 1e-6,
    log: bool = True,
) -> tuple[list[dict], list[float], dict]:
    """Branch-and-price loop using master variant 2 (DW) for
    granularities whose columns span multiple teachers (class,
    class-day, day, curriculum).

    `columns_initial` is the seed pool (e.g. the union of all
    teacher-week patterns from the iterative-diversified primal
    heuristic, each treated as a partial pattern).

    Returns (columns, lp_x, info) -- the final column pool and
    fractional LP weights. Integer recovery is the caller's job.
    """
    info: dict[str, Any] = {
        "bp_iterations_done": 0,
        "bp_columns_added_total": 0,
        "bp_lp_obj_per_iter": [],
        "bp_min_rc_per_iter": [],
        "bp_terminated_reason": "",
    }
    columns = list(columns_initial)
    lp_x = []

    res = _solve_master_dw(columns, dc_value, return_extended=True)
    if res[0] is None:
        info["bp_terminated_reason"] = "master_dw_infeasible_at_entry"
        return columns, lp_x, info
    lp_x, best_obj, lam, mu_cl, mu_t, _ck, _clk, _tk = res
    info["bp_lp_obj_per_iter"].append(best_obj)

    for it in range(1, bp_max_iterations + 1):
        if time.time() - t0 > time_budget_s:
            info["bp_terminated_reason"] = "time_budget"
            break
        try:
            keys = _enumerate_pricing_keys(
                granularity, profs, dc_value, group_assignments)
        except NotImplementedError as e:
            info["bp_terminated_reason"] = (
                f"granularity_not_implemented:{granularity}")
            if log:
                print(f"[CG.BP-DW] {e}")
            break

        added = 0
        min_rc = 0.0
        for key in keys:
            if time.time() - t0 > time_budget_s:
                break
            try:
                col, rc = _solve_pricing_dw(
                    granularity, key, profs, dc_value,
                    lam, mu_cl, mu_t,
                    time_limit=pricer_time_limit,
                    workers=pricer_workers,
                    locks=locks,
                    group_assignments=group_assignments,
                    eps=eps,
                )
            except NotImplementedError:
                info["bp_terminated_reason"] = (
                    f"granularity_not_implemented:{granularity}")
                break
            if rc < min_rc:
                min_rc = rc
            if col is None:
                continue
            if col not in columns:
                columns.append(col)
                added += 1
        info["bp_iterations_done"] = it
        info["bp_columns_added_total"] += added
        info["bp_min_rc_per_iter"].append(min_rc)

        if added == 0:
            info["bp_terminated_reason"] = "no_improving_column"
            break

        res = _solve_master_dw(columns, dc_value, return_extended=True)
        if res[0] is None:
            info["bp_terminated_reason"] = (
                f"master_dw_infeasible_at_iter_{it}")
            break
        lp_x, obj, lam, mu_cl, mu_t, _ck, _clk, _tk = res
        info["bp_lp_obj_per_iter"].append(float(obj))
        if obj < best_obj - eps:
            best_obj = float(obj)
            if log:
                print(f"[CG.BP-DW iter {it}] obj -> {best_obj:.1f}, "
                      f"+{added} cols, min_rc={min_rc:.3f}")
        else:
            if log:
                print(f"[CG.BP-DW iter {it}] plateau ({obj:.1f}), "
                      f"+{added} cols, min_rc={min_rc:.3f}")
            if min_rc > -10.0 * eps:
                info["bp_terminated_reason"] = "rc_plateau"
                break

    if not info["bp_terminated_reason"]:
        info["bp_terminated_reason"] = "max_iterations"
    return columns, lp_x, info


def _integer_recover_dw(columns: list[dict], lp_x: list[float],
                         dc_value: dict
                         ) -> dict:
    """Greedy set-packing integer recovery from a fractional master2
    LP solution. Pick columns in descending order of x[col]; accept
    a column only if it doesn't violate class no-overlap or teacher
    no-overlap. Stop when cover is met or all columns exhausted.
    Return the assembled solution dict.
    """
    order = sorted(range(len(columns)),
                    key=lambda i: -float(lp_x[i] if i < len(lp_x) else 0.0))
    used_cl: set = set()  # (cl, d, h)
    used_t: set = set()   # (t, d, h)
    sol: dict = {}
    for i in order:
        col = columns[i]
        # Check no-overlap for this column.
        col_cl: set = set()
        col_t: set = set()
        ok = True
        for (p, cl, _s, d, h), v in col.items():
            if not v:
                continue
            if (cl, d, h) in used_cl or (cl, d, h) in col_cl:
                ok = False
                break
            if (p, d, h) in used_t or (p, d, h) in col_t:
                ok = False
                break
            col_cl.add((cl, d, h))
            col_t.add((p, d, h))
        if not ok:
            continue
        used_cl.update(col_cl)
        used_t.update(col_t)
        for k, v in col.items():
            if v:
                sol[k] = max(sol.get(k, 0), int(v))
    return sol


# ---------------- Top-level driver ----------------


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
                          branching_strategy: str = "ryan_foster",
                          bp_max_iterations: int = 8,
                          pricer_time_limit: float = 5.0,
                          pricer_workers: int = 2,
                          class_to_curriculum: dict | None = None,
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

    # Step 3b (real Branch-and-Price): if mode in {"branch-and-price",
    # "auto"} and the chosen granularity has a CP-SAT pricer, run
    # the BP loop using the iterative-diversified output as the
    # primal warm-start.
    n_classes_est = len({cl for p in profs.values()
                          for cl in p.get("classi", {})})
    use_bp = (mode == "branch-and-price"
              or (mode == "auto" and n_classes_est <= 25))
    if (use_bp and granularity in _BP_GRANULARITIES_DW
            and time.time() - t0 < time_budget_s):
        # DW path (master variant 2): for class / class-day / day /
        # curriculum granularities. Columns are multi-teacher partial
        # patterns; integer recovery is greedy set-packing.
        if log:
            print(f"[CG.BP-DW] mode={mode}, granularity={granularity}: "
                  f"running master-2 branch-and-price loop "
                  f"({n_classes_est} classes)")
        # Seed the variant-2 column pool with the per-teacher
        # patterns from the iterative-diversified phase (each is
        # a valid partial pattern under variant 2).
        seed_columns: list[dict] = []
        for _t, plist in patterns.items():
            for pat in plist:
                if pat not in seed_columns:
                    seed_columns.append(pat)
        # Thread class_to_curriculum into the dispatcher context for
        # the curriculum pricer.
        _CLASS_TO_CURRICULUM_CTX["map"] = class_to_curriculum
        try:
            dw_columns, dw_lp_x, dw_info = _run_branch_and_price_dw(
                seed_columns, profs, dc_value,
                granularity=granularity,
                bp_max_iterations=bp_max_iterations,
                pricer_time_limit=pricer_time_limit,
                pricer_workers=pricer_workers,
                locks=locks,
                group_assignments=group_assignments,
                time_budget_s=time_budget_s,
                t0=t0,
                log=log,
            )
        finally:
            _CLASS_TO_CURRICULUM_CTX["map"] = None
        info.update({k: v for k, v in dw_info.items()
                      if k.startswith("bp_")})
        info["iterations_done"] += int(dw_info.get(
            "bp_iterations_done", 0))
        info["bp_dw_n_columns"] = len(dw_columns)
        # Integer recovery via greedy set-packing.
        dw_sol = _integer_recover_dw(dw_columns, dw_lp_x, dc_value)
        if dw_sol and meta.is_hard_feasible(dw_sol, profs,
                                              verbose=False):
            v_dw, _m_dw = meta.compute_soft(dw_sol, profs)
            if log:
                print(f"[CG.BP-DW] integer-recovered HARD-feasible "
                      f"sol with soft={v_dw:.1f}")
            info["bp_dw_integer_obj"] = float(v_dw)
            info["bp_dw_integer_feasible"] = True
            sol_dw_override = dw_sol
            info["feasible_after_assembly"] = True
        else:
            info["bp_dw_integer_feasible"] = False
            sol_dw_override = None

        # Ryan-Foster branching: full recursive tree (best-first
        # node exploration, LP-bound pruning, max_depth/max_nodes
        # caps). If any node's integer recovery produces a better
        # HARD-feasible solution than the unbranched DW-greedy
        # recovery, adopt it.
        if (branching_strategy == "ryan_foster"
                and time.time() - t0 < time_budget_s):
            rf_sol, rf_info = _run_ryan_foster_tree(
                dw_columns, profs, dc_value,
                time_budget_s=time_budget_s,
                t0=t0,
                log=log,
            )
            info.update({k: v for k, v in rf_info.items()
                          if k.startswith("rf_")})
            if rf_sol is not None:
                rf_v, _ = meta.compute_soft(rf_sol, profs)
                cur_v = (info.get("bp_dw_integer_obj")
                          if sol_dw_override else float("inf"))
                if cur_v is None:
                    cur_v = float("inf")
                if rf_v < cur_v - 1e-6:
                    if log:
                        print(f"[CG.BP-DW.RF] adopting RF tree sol "
                              f"(soft={rf_v:.1f} vs {cur_v:.1f})")
                    sol_dw_override = rf_sol
                    info["bp_dw_integer_obj"] = float(rf_v)
                    info["bp_dw_integer_feasible"] = True
                    info["feasible_after_assembly"] = True
        # If DW didn't yield a feasible integer sol, keep
        # variant-1's selection for the standard recovery path.
    elif (use_bp and granularity in _BP_GRANULARITIES
            and time.time() - t0 < time_budget_s):
        if log:
            print(f"[CG.BP] mode={mode}, granularity={granularity}: "
                  f"running real branch-and-price loop "
                  f"({n_classes_est} classes)")
        patterns, bp_obj, bp_selection, bp_info = _run_branch_and_price(
            patterns, profs, dc_value,
            granularity=granularity,
            bp_max_iterations=bp_max_iterations,
            pricer_time_limit=pricer_time_limit,
            pricer_workers=pricer_workers,
            locks=locks,
            group_assignments=group_assignments,
            time_budget_s=time_budget_s,
            t0=t0,
            log=log,
        )
        info.update({f"bp_{k.removeprefix('bp_')}": v
                      for k, v in bp_info.items()
                      if k.startswith("bp_")})
        info["iterations_done"] += int(bp_info.get(
            "bp_iterations_done", 0))
        if bp_obj < best_obj - 1e-6 and bp_selection:
            best_obj = bp_obj
            best_selection = dict(bp_selection)
            best_patterns = {k: list(v) for k, v in patterns.items()}
            if log:
                print(f"[CG.BP] BP loop improved obj to {best_obj:.1f}")
        info["n_patterns_total_final"] = sum(
            len(v) for v in best_patterns.values())
        info["master_obj_final"] = (
            best_obj if best_obj != float("inf") else None)
        sol_dw_override = None
    elif use_bp and granularity not in _BP_GRANULARITIES + _BP_GRANULARITIES_DW:
        # Mode requested BP but granularity has no pricer yet ->
        # iterative-diversified is the de-facto pricer for that
        # granularity (matches user intent for granularity=teacher).
        info["warnings"].append(
            f"granularity={granularity!r} has no CP-SAT pricer in "
            f"this commit; iterative-diversified results stand. "
            f"BP pricers wired so far: {list(_BP_GRANULARITIES)}.")

    # Step 4: integer recovery. The DW path may have produced its
    # own HARD-feasible integer sol via greedy set-packing -- if so,
    # use it directly. Otherwise fall back to the variant-1
    # per-teacher selection assembly.
    if locals().get("sol_dw_override") is not None:
        sol = locals()["sol_dw_override"]
    else:
        sol = {}
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
