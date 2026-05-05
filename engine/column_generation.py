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
# Each non-teacher granularity has its own CP-SAT sub-pricer. The
# pricer output is always a full TEACHER-WEEK pattern (dict
# {(t, cl, s, d, h): 1}) compatible with the existing master LP
# (variant 1, "exactly one pattern per teacher" equality + cover
# inequalities). The granularity controls *which slice* of the
# teacher's week the CP-SAT optimises against the master's duals;
# the rest of the week is greedy-placed first and treated as
# locked by the CP-SAT model.
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

    # Pre-place this teacher's locks (they are non-negotiable).
    locks_for_t = [(cl_l, s_l, d_l, h_l)
                    for (p, cl_l, s_l, d_l, h_l) in locks
                    if p == teacher]
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


# ---------------- BP loop: dispatcher + driver ----------------

_BP_GRANULARITIES = (
    "teacher-class",
    # Pricers for additional granularities arrive in subsequent
    # commits (steps 3b-3h):
    #   teacher-class-subject, teacher-subject, teacher-day,
    #   class, class-day, day, curriculum.
)


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
    raise NotImplementedError(
        f"_solve_pricing: granularity {granularity!r} not implemented")


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

    # Step 3b (real Branch-and-Price): if mode in {"branch-and-price",
    # "auto"} and the chosen granularity has a CP-SAT pricer, run
    # the BP loop using the iterative-diversified output as the
    # primal warm-start.
    n_classes_est = len({cl for p in profs.values()
                          for cl in p.get("classi", {})})
    use_bp = (mode == "branch-and-price"
              or (mode == "auto" and n_classes_est <= 25))
    if (use_bp and granularity in _BP_GRANULARITIES
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
    elif use_bp and granularity not in _BP_GRANULARITIES:
        # Mode requested BP but granularity has no pricer yet ->
        # iterative-diversified is the de-facto pricer for that
        # granularity (matches user intent for granularity=teacher).
        info["warnings"].append(
            f"granularity={granularity!r} has no CP-SAT pricer in "
            f"this commit; iterative-diversified results stand. "
            f"BP pricers wired so far: {list(_BP_GRANULARITIES)}.")

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
