r"""Lagrangian relaxation with subgradient ascent (genuine decomposition).

What is dualized
----------------
The timetable is decomposed into class clusters (spectral / curriculum /
metis -- the caller supplies ``classes_clusters``). Solving each cluster
INDEPENDENTLY per day is not globally valid because a **bridge teacher**
(one who teaches classes in more than one cluster) could be placed in the
same ``(day, hour)`` by two different clusters -- a physical double-booking.
That cross-cluster teacher no-overlap is the coupling we RELAX:

    for every bridge teacher t and slot (d, h):
        sum over clusters of  busy_k[t, d, h]  <=  1          (capacity 1)

Each such constraint is dualized with a multiplier ``lambda[t, h] >= 0`` and
PRICED into every cluster's per-day objective: a cluster that occupies a
contended hour with a bridge teacher pays ``lambda[t, h]``. The per-cluster
subproblem is the real Phase B day solver
(``cpsat_v2_timetable.solve_phase_b_for_day``) with the penalty hook
``lagrangian_penalties=`` -- so the multipliers GENUINELY steer where the
teacher's (dc_value-fixed) hours land, away from collisions.

Subgradient ascent
------------------
    usage[t, h]      = sum_k busy_k[t, h]          (over cluster solutions)
    g[t, h]          = usage[t, h] - 1             (constraint violation)
    lambda[t, h]     = max(0, lambda[t, h] + alpha_k * g[t, h])
    alpha_k          = alpha_0 / (1 + k)           (diminishing step)

When ``usage <= 1`` for every bridge slot on a day, the assembled day is a
valid, collision-free timetable. The Lagrangian **dual bound** each iteration
is ``sum_k (cluster objective incl. lambda terms) - sum_{t,h} lambda[t,h]``,
a lower bound on the optimal soft cost subject to the coupling; the best
(max) bound over the ascent is reported.

Primal / safety contract
------------------------
This entry point is invoked as a post-processor on an active solution
(``sol``), so it never regresses: it reconstructs the week per cluster per
day, and RETURNS the reconstruction ONLY if every day converged
collision-free, it is HARD-feasible (``is_hard_feasible``, full cross-day
check), it preserves all ``locks``, and its soft cost is no worse than the
input. Otherwise the input ``sol`` is returned unchanged. Cases the plain
bridge-teacher relaxation does not model (inter-class ``group_assignments``,
group-target sostegno) degrade to a documented no-op. Every cluster solve
receives ``locks`` (native per-day pins), the coteach / parallel / support
context sliced to its classes, and any ``dsl_hard_expressions`` gate.
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
import cpsat_v2_timetable as cv2  # type: ignore  # noqa: E402
import metaheuristics as meta  # type: ignore  # noqa: E402


def _all_classes(profs: dict) -> list[str]:
    return sorted({c for p in profs.values() for c in (p.get("classi") or {})})


def _normalize_clusters(classes_clusters, all_classes) -> dict[int, set[str]]:
    """Coerce the caller's clustering into ``{cid: set(classes)}`` covering
    every class (any class missing from the supplied partition lands in its
    own trailing cluster, so no cattedra is silently dropped)."""
    clusters = {int(k): set(v) for k, v in dict(classes_clusters).items() if v}
    covered = set().union(*clusters.values()) if clusters else set()
    missing = set(all_classes) - covered
    if missing:
        nxt = (max(clusters) + 1) if clusters else 0
        clusters[nxt] = missing
    return clusters


def _bridge_teachers(profs: dict, class_to_cid: dict[str, int]) -> set[str]:
    """Teachers whose cattedre span more than one cluster."""
    out: set[str] = set()
    for t, info in profs.items():
        cids = {class_to_cid[c] for c in (info.get("classi") or {})
                if c in class_to_cid}
        if len(cids) >= 2:
            out.add(t)
    return out


def _cluster_profs(profs: dict, cluster_classes: set[str]) -> dict:
    """Project ``profs`` onto one cluster's classes (teachers with no class
    in the cluster are dropped; per-teacher scalars are preserved)."""
    sub: dict = {}
    for t, info in profs.items():
        cl_in = {c: v for c, v in (info.get("classi") or {}).items()
                 if c in cluster_classes}
        if not cl_in:
            continue
        new_info = dict(info)
        new_info["classi"] = cl_in
        sub[t] = new_info
    return sub


def run_lagrangian(sol: dict, profs: dict, dc_value: dict,
                   *, time_budget_s: float = 60.0,
                   max_iter: int = 8,
                   tolerance: float = 1e-2,
                   alpha_0: float = 100.0,
                   classes_clusters: dict[int, set[str]] | None = None,
                   log: bool = True,
                   locks: set | None = None,
                   coteach_groups=None,
                   support_assignments=None,
                   parallel_groups=None,
                   group_assignments=None,
                   class_flags=None,
                   special_room_ctx=None,
                   total_room_capacity=None,
                   db=None,
                   dsl_hard_expressions=None,
                   soft_rules=None) -> tuple[dict, dict]:
    """Genuine Lagrangian relaxation of the cross-cluster bridge coupling.

    Returns ``(best_sol, info)``. ``best_sol`` is the reconstructed week when
    it converges collision-free, is HARD-feasible, preserves ``locks`` and is
    no worse than ``sol``; otherwise ``sol`` unchanged. ``info`` carries the
    ascent trajectory (``iterations``), the best dual bound (``dual_bound``),
    the converged days and any ``warnings``.
    """
    t0 = time.time()
    info: dict[str, Any] = {
        "kind": "lagrangian",
        "max_iter": max_iter,
        "tolerance": tolerance,
        "alpha_0": alpha_0,
        "n_bridges": 0,
        "iterations": [],
        "converged_days": [],
        "dual_bound": None,
        "primal_soft": None,
        "accepted": False,
        "mode": None,
        "duration_s": None,
        "warnings": [],
    }

    def _finish(result_sol):
        info["duration_s"] = time.time() - t0
        if log:
            print(f"[Lagrangian] mode={info['mode']} "
                  f"bridges={info['n_bridges']} "
                  f"converged_days={info['converged_days']} "
                  f"accepted={info['accepted']} "
                  f"dual_bound={info['dual_bound']} "
                  f"in {info['duration_s']:.1f}s")
        return result_sol, info

    # --- degradation guards: return the input unchanged (never regress) ---
    if not classes_clusters:
        info["mode"] = "noop_no_clusters"
        info["warnings"].append(
            "nessun clustering fornito: rilassazione triviale, sol invariata")
        return _finish(sol)

    # Inter-class StudyGroups couple classes through a teacher that carries
    # NO per-class cattedra; slicing them per cluster would need the group's
    # class membership reconstructed. Out of scope for the bridge relaxation
    # -> honest no-op (the input already schedules them).
    if group_assignments or any(
            (sa or {}).get("is_group_target")
            for sa in (support_assignments or [])):
        info["mode"] = "noop_groups"
        info["warnings"].append(
            "group_assignments/gruppo-sostegno presenti: coupling inter-classe "
            "non dualizzato, sol invariata")
        return _finish(sol)

    all_classes = _all_classes(profs)
    clusters = _normalize_clusters(classes_clusters, all_classes)
    class_to_cid = {c: cid for cid, cs in clusters.items() for c in cs}
    bridges = _bridge_teachers(profs, class_to_cid)
    info["n_bridges"] = len(bridges)

    if len(clusters) < 2 or not bridges:
        info["mode"] = "noop_no_bridges"
        info["warnings"].append(
            "nessun bridge inter-cluster: rilassazione triviale, sol invariata")
        return _finish(sol)

    if locks:
        n_locked_bridge = sum(1 for k in locks if k and k[0] in bridges)
        if n_locked_bridge:
            info["warnings"].append(
                f"{n_locked_bridge} locked slots on bridge teachers are "
                f"pinned natively in their cluster (the subgradient sees them "
                f"as fixed capacity, not movable violations)")

    # HARD-check context reused for the final feasibility gate.
    hard_ctx = dict(
        coteach_groups=coteach_groups,
        support_assignments=support_assignments,
        parallel_groups=parallel_groups,
        group_assignments=group_assignments,
        class_flags=class_flags,
        special_room_ctx=special_room_ctx,
        dsl_hard_expressions=dsl_hard_expressions,
        db=db,
    )

    best_sol = meta.deepcopy_sol(sol)
    best_val, _ = meta.compute_soft(best_sol, profs, soft_rules=soft_rules)

    # Static per-cluster indices (built once; only lambda changes per iter).
    cluster_static: dict[int, tuple] = {}
    for cid, cs in clusters.items():
        profs_sub = _cluster_profs(profs, cs)
        if not profs_sub:
            continue
        classes_c, triples_c, class_profs_c = cv2.build_indices(profs_sub)
        cluster_static[cid] = (profs_sub, classes_c, triples_c, class_profs_c,
                               cs)

    DAYS, HOURS = cv2.DAYS, cv2.HOURS
    n_days = max(1, len(DAYS))
    # Two cluster passes per iteration (independent solve for the dual +
    # sequential recovery for the primal), so budget the per-solve limit
    # accordingly.
    per_solve_time = max(1.0, min(30.0,
                                  time_budget_s / (n_days * max(1, max_iter) * 2)))
    _RECOVER_BIG = 1_000_000.0

    def _solve_cluster(cid, d, penalties):
        profs_sub, classes_c, triples_c, class_profs_c, cs = cluster_static[cid]
        locked_day = None
        if locks:
            locked_day = [
                (p, cl, s, h) for (p, cl, s, dd, h) in locks
                if dd == d and cl in cs
            ] or None
        ct = [g for g in (coteach_groups or []) if g.get("class_name") in cs]
        pl = [g for g in (parallel_groups or []) if g.get("class_name") in cs]
        su = [g for g in (support_assignments or []) if g.get("class_name") in cs]
        return cv2.solve_phase_b_for_day(
            d, profs_sub, classes_c, triples_c, class_profs_c, dc_value,
            time_limit=per_solve_time, workers=4, log=False,
            locked_slots_for_day=locked_day,
            coteach_groups=ct or None, support_assignments=su or None,
            parallel_groups=pl or None, class_flags=class_flags,
            special_room_ctx=special_room_ctx,
            total_room_capacity=total_room_capacity,
            via_dsl=bool(dsl_hard_expressions),
            dsl_hard_expressions=dsl_hard_expressions,
            return_objective=True, lagrangian_penalties=penalties)

    def _bridge_usage(sols):
        usage: dict[tuple[str, int], int] = defaultdict(int)
        for out in sols:
            seen: set[tuple[str, int]] = set()   # per-cluster: single-booked
            for (p, _cl, _s, _dd, h), v in out.items():
                if v and p in bridges and (p, h) not in seen:
                    seen.add((p, h))
                    usage[(p, h)] += 1
        return usage

    def _recover_primal(d, base_pen):
        """Sequential (Gauss-Seidel) primal recovery: solve clusters in turn,
        each strongly penalized (``_RECOVER_BIG``) from re-using a bridge
        slot an earlier cluster already took this day. Since a bridge
        teacher's total day hours fit the day (Phase A bounds prof-day load
        <= slots), later clusters CAN dodge, yielding a collision-free
        assembly in one pass -- robust where pure subgradient oscillates on
        symmetric instances. Returns the merged day, or ``None`` if a cluster
        is infeasible or a clash is unavoidable."""
        used: dict[tuple[str, int], int] = defaultdict(int)
        merged: dict = {}
        for cid in sorted(cluster_static):
            pen = dict(base_pen)
            for (t, h), c in used.items():
                if c:
                    pen[(t, h)] = pen.get((t, h), 0.0) + _RECOVER_BIG * c
            out, _st, _ob = _solve_cluster(cid, d, pen)
            if out is None:
                return None
            for (p, cl, s, dd, h), v in out.items():
                if v:
                    merged[(p, cl, s, dd, h)] = 1
                    if p in bridges:
                        used[(p, h)] += 1
        if any(c > 1 for c in used.values()):
            return None
        return merged

    info["mode"] = "lagrangian"
    assembled_days: dict[int, dict] = {}
    best_dual = None

    for d in DAYS:
        if time.time() - t0 > time_budget_s:
            info["warnings"].append(f"time budget esaurito prima del giorno {d}")
            break
        lam: dict[tuple[str, int], float] = {}
        for k in range(max(1, int(max_iter))):
            penalties = {kk: vv for kk, vv in lam.items() if vv > 0}

            # (A) Independent subproblems -> genuine subgradient + dual bound.
            indep: list[dict] = []
            dual = 0.0
            feasible_all = True
            for cid in sorted(cluster_static):
                out, _st, obj = _solve_cluster(cid, d, penalties)
                if out is None:
                    feasible_all = False
                    break
                indep.append(out)
                dual += float(obj or 0)
            if not feasible_all:
                info["warnings"].append(
                    f"giorno {d}: cluster infeasible all'iterazione {k}")
                break

            # Lagrangian dual bound: subtract lambda * capacity (1 per slot).
            dual -= sum(penalties.values())
            if best_dual is None or dual > best_dual:
                best_dual = dual

            usage = _bridge_usage(indep)
            collisions = {kk: c for kk, c in usage.items() if c > 1}

            alpha_k = alpha_0 / (1.0 + k)
            max_change = 0.0
            for t in bridges:
                for h in HOURS:
                    g = usage.get((t, h), 0) - 1
                    old = lam.get((t, h), 0.0)
                    new = max(0.0, old + alpha_k * g)
                    if new != old:
                        max_change = max(max_change, abs(new - old))
                        if new == 0.0:
                            lam.pop((t, h), None)
                        else:
                            lam[(t, h)] = new
            info["iterations"].append({
                "day": int(d),
                "k": int(k),
                "alpha_k": alpha_k,
                "lambda_max": max(lam.values()) if lam else 0.0,
                "lambda_change": max_change,
                "n_collisions": len(collisions),
                "dual_bound": dual,
            })

            # (B) Primal. If the independent solve is already collision-free
            # it IS the primal; otherwise recover one sequentially.
            if not collisions:
                merged = {}
                for out in indep:
                    for kk, v in out.items():
                        if v:
                            merged[kk] = 1
                assembled_days[int(d)] = merged
                info["converged_days"].append(int(d))
                break
            recovered = _recover_primal(d, penalties)
            if recovered is not None:
                assembled_days[int(d)] = recovered
                info["converged_days"].append(int(d))
                break
            if time.time() - t0 > time_budget_s:
                break

    info["dual_bound"] = best_dual

    # Accept the reconstruction ONLY if every day converged collision-free.
    if len(info["converged_days"]) == len(DAYS):
        candidate: dict = {}
        for d in DAYS:
            candidate.update(assembled_days[int(d)])
        locks_ok = all(candidate.get(k) == 1 for k in (locks or set()))
        feasible = meta.is_hard_feasible(candidate, profs, verbose=False,
                                         **hard_ctx)
        cand_val, _ = meta.compute_soft(candidate, profs, soft_rules=soft_rules)
        info["primal_soft"] = cand_val
        if locks_ok and feasible and cand_val <= best_val:
            info["accepted"] = True
            return _finish(candidate)
        if not locks_ok:
            info["warnings"].append(
                "ricostruzione scartata: non preserva tutti i lock")
        elif not feasible:
            info["warnings"].append(
                "ricostruzione scartata: non HARD-feasible (vincoli cross-day)")
        else:
            info["warnings"].append(
                f"ricostruzione scartata: soft {cand_val} > input {best_val}")
    else:
        info["warnings"].append(
            f"{len(info['converged_days'])}/{len(DAYS)} giorni convergenti: "
            "sol invariata")

    return _finish(best_sol)
