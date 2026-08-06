"""Shared Stage A / B / C orchestrator for cluster-based decompositions.

The original `decomposition_spectral_v2.py` defines:

  stage_a_bridges(day, profs, bridges, triples, dc_value, time, workers)
  stage_b_cluster_internals(cluster, day, profs, bridges, triples,
                            dc_value, bridges_solution, time, workers)
  stage_c_ricucitura(day, profs, bridges, triples, dc_value,
                     bridge_solution, fixed_internals, time, workers)
  solve_monolithic_day(day, profs, triples, dc_value, time, workers)

These functions are agnostic to *how* clusters and bridges were
computed -- they operate on the input set of bridge teachers
and on the partition of classes. So the Stage A/B/C loop can be
reused verbatim by any partition-producing strategy: spectral
(already wired in `decomposition_spectral_v2.main`), per-curriculum,
METIS-k-way, or future custom partitions.

This module exposes a single function `run_partitioned_pipeline`
that takes a precomputed (labels, classes, bridges) tuple plus
the standard CP-SAT timing budgets, and runs the day-wise loop:

    for each day d:
        1. Stage A: schedule the bridge teachers' lessons in d
        2. Stage B: schedule each cluster's internals in d, with
                    the bridges fixed
        3. Stage C: if any cluster failed, re-do the failed clusters
                    after fixing the successful ones (ricucitura)
        4. Monolithic fallback: if Stage C still fails, solve the
                    whole day in one CP-SAT pass

Returns the full solution dict, the per-day timings and the list of
failed days (those where even the monolithic fallback could not find
a feasible orario).
"""
from __future__ import annotations

import time
from collections import defaultdict
from typing import Iterable

import numpy as np

import cpsat_v2_timetable as cv2  # type: ignore
import decomposition_spectral_v2 as dec  # type: ignore

DAYS = cv2.DAYS


def run_partitioned_pipeline(
    profs: dict,
    labels: np.ndarray,
    classes: list[str],
    bridges: set[str],
    *,
    time_a: float = 60.0,
    time_bridges: float = 30.0,
    time_cluster: float = 30.0,
    time_ricucitura: float = 60.0,
    time_mono: float = 120.0,
    workers: int = 8,
    log: bool = False,
    dc_value: dict | None = None,
    locked_day_count: dict | None = None,
    locked_by_day: dict | None = None,
    coteach_groups: list | None = None,
    support_assignments: list | None = None,
    parallel_groups: list | None = None,
    group_assignments: list | None = None,
    class_day_load_allowed: dict | None = None,
    class_free_days: dict | None = None,
    special_room_ctx=None,
    total_room_capacity=None,
    plessi_ctx=None,
    dsl_hard_expressions: list | None = None,
):
    """Run the canonical Stage A/B/C/monolithic loop on a precomputed
    cluster partition.

    `dsl_hard_expressions` (audit H6): when non-empty, HARD DSL rules the
    CP compiler cannot emit are present. The per-cluster stages (A/B/C)
    only ever see a class subset, so they cannot enforce a global DSL
    rule; the whole loop is therefore forced onto the monolithic per-day
    path (like the groups/special-room cases) and the expressions are
    threaded into `solve_monolithic_day`'s verify + no-good gate.

    Parameters
    ----------
    profs : dict
        Output of Phase A (teacher -> classi -> subject -> ore).
    labels : np.ndarray, shape (n_classes,)
        Cluster id (0..k-1) for each class, in the same order as
        `classes`.
    classes : list[str]
        Sorted list of class names.
    bridges : set[str]
        Names of teachers that span multiple clusters and must be
        scheduled first (Stage A) so each cluster knows when the
        bridge is busy.
    time_a, time_bridges, time_cluster, time_ricucitura, time_mono :
        CP-SAT time budgets per stage. `time_a` is the master
        Phase A budget (skipped if `dc_value` is supplied).
    workers : int
        CP-SAT search workers.
    log : bool
        If True, emit progress lines on stdout.
    dc_value : dict, optional
        Pre-computed per-day distribution. If None, this function
        runs `cv2.solve_phase_a` first.

    Returns
    -------
    dict with keys:
        full_solution     : dict (p,cl,subj,d,h) -> 0/1
        dc_value          : dict (p,cl,subj,d) -> int
        failed_days       : list[int]
        timings           : dict {master, days_total, days_per_day}
        cluster_sizes     : dict {cluster_id: size}
        bridges_count     : int
        status            : 'ok' | 'partial' | 'master_failed'
    """
    n_classes = len(classes)
    if n_classes == 0:
        return {
            "full_solution": {}, "dc_value": dc_value or {},
            "failed_days": list(DAYS), "timings": {
                "master": 0.0, "days_total": 0.0, "days_per_day": {}},
            "cluster_sizes": {}, "bridges_count": 0,
            "status": "master_failed",
        }

    # Build per-cluster class set
    cl_to_label = dict(zip(classes, labels.astype(int).tolist()))
    classes_per_cluster: dict[int, set] = defaultdict(set)
    for c, lbl in cl_to_label.items():
        classes_per_cluster[lbl].add(c)
    cluster_sizes = {k: len(s) for k, s in classes_per_cluster.items()}

    if log:
        print(f"[loop] partition: {len(cluster_sizes)} cluster, "
              f"sizes={cluster_sizes}, bridges={len(bridges)}/{len(profs)}")

    # ---- Master CP-SAT (Phase A internal) ----
    classes_v, triples, class_profs = cv2.build_indices(profs)
    t0 = time.time()
    if dc_value is None:
        if log:
            print(f"[loop] master CP-SAT (time_limit={time_a}s)")
        dc_value = cv2.solve_phase_a(
            profs, classes_v, triples, class_profs,
            time_limit=time_a, workers=workers, log=False,
            locked_day_count=locked_day_count,
            coteach_groups=coteach_groups,
            support_assignments=support_assignments,
            parallel_groups=parallel_groups,
            group_assignments=group_assignments,
            class_day_load_allowed=class_day_load_allowed,
            class_free_days=class_free_days,
            special_room_ctx=special_room_ctx,
        )
    elapsed_master = time.time() - t0

    # ---- Per-day Stage A/B/C/monolithic ----
    full_solution: dict = {}
    failed_days: list[int] = []
    days_per_day: dict[int, float] = {}
    days_t0 = time.time()
    bridges_set = set(bridges)

    # Task C3: when group_assignments are present, the spectral
    # stages (A bridges / B cluster / C ricucitura) don't model the
    # group_slot vars and would silently drop the group hours. Force
    # the monolithic per-day path for the whole loop -- still benefits
    # from the cached `dc_value` master, just skips the stages.
    #
    # Same for special-room (gym/lab) capacity: it is a GLOBAL per-(day,
    # hour) cap over ALL classes, which the per-cluster stages cannot see
    # (verified: metis put 7 classes in a 6-slot palestra hour, and
    # is_hard_feasible then rejected the whole timetable). The monolithic
    # per-day solve sees every class that day, so force it when a
    # special-room ctx is present, exactly like the groups case.
    # Audit H9/H10/H7: the per-cluster stages (A/B/C) model NONE of coteach,
    # sostegno, intra-class parallel, or plessi commuting either -- disjoint
    # class subsets can't see a shared teacher's compresenza, a support shadow,
    # or a global plesso rule. Force the monolithic per-day path (which does
    # model them, via solve_monolithic_day) whenever any is present, exactly
    # like the groups/special-room cases.
    force_mono_for_groups = (
        bool(group_assignments) or bool(special_room_ctx)
        or bool(total_room_capacity)
        or bool(coteach_groups) or bool(support_assignments)
        or bool(parallel_groups) or bool(plessi_ctx)
        or bool(dsl_hard_expressions))

    for d in DAYS:
        t = time.time()
        locks_d = (locked_by_day or {}).get(d, None)
        if force_mono_for_groups:
            mono_out, _ = dec.solve_monolithic_day(
                d, profs, triples, dc_value, time_mono, workers,
                locked_slots_for_day=locks_d,
                coteach_groups=coteach_groups,
                support_assignments=support_assignments,
                parallel_groups=parallel_groups,
                group_assignments=group_assignments,
                special_room_ctx=special_room_ctx,
                total_room_capacity=total_room_capacity,
                plessi_ctx=plessi_ctx,
                dsl_hard_expressions=dsl_hard_expressions,
            )
            if mono_out is None:
                failed_days.append(d)
                days_per_day[d] = time.time() - t
                if log:
                    print(f"[loop]   day {d} MONO (groups) failed in "
                          f"{days_per_day[d]:.1f}s")
                continue
            full_solution.update(mono_out)
            days_per_day[d] = time.time() - t
            if log:
                print(f"[loop]   day {d} via MONO (groups path) in "
                      f"{days_per_day[d]:.1f}s")
            continue
        # Stage A: bridges first
        bridges_out, _ = dec.stage_a_bridges(
            d, profs, bridges_set, triples, dc_value,
            time_bridges, workers,
            locked_slots_for_day=locks_d,
        )
        if bridges_out is None:
            # Bridges infeasible: try monolithic for this day
            mono_out, _ = dec.solve_monolithic_day(
                d, profs, triples, dc_value, time_mono, workers,
                locked_slots_for_day=locks_d,
                coteach_groups=coteach_groups,
                support_assignments=support_assignments,
                parallel_groups=parallel_groups,
                group_assignments=group_assignments,
                special_room_ctx=special_room_ctx,
                total_room_capacity=total_room_capacity,
                plessi_ctx=plessi_ctx,
                dsl_hard_expressions=dsl_hard_expressions,
            )
            if mono_out is None:
                failed_days.append(d)
                days_per_day[d] = time.time() - t
                if log:
                    print(f"[loop]   day {d} BRIDGES+MONO failed in "
                          f"{days_per_day[d]:.1f}s")
                continue
            full_solution.update(mono_out)
            days_per_day[d] = time.time() - t
            if log:
                print(f"[loop]   day {d} via MONO fallback in "
                      f"{days_per_day[d]:.1f}s")
            continue

        # Stage B: each cluster's internals, with bridges fixed
        cluster_solutions: dict[int, dict] = {}
        b_failed: set[int] = set()
        for k_id in sorted(classes_per_cluster,
                           key=lambda kk: -len(classes_per_cluster[kk])):
            cl_set = classes_per_cluster[k_id]
            if not cl_set:
                continue
            out, _ = dec.stage_b_cluster_internals(
                cl_set, d, profs, bridges_set, triples, dc_value,
                bridges_out, time_cluster, workers,
                locked_slots_for_day=locks_d,
            )
            if out is None:
                b_failed.add(k_id)
            else:
                cluster_solutions[k_id] = out

        if b_failed:
            # Stage C: ricucitura. Fix the successful clusters,
            # re-solve the failed ones together.
            fixed: dict = dict(bridges_out)
            for kk, out in cluster_solutions.items():
                if kk not in b_failed:
                    fixed.update(out)
            ricuc_out, _ = dec.stage_c_ricucitura(
                d, profs, bridges_set, triples, dc_value,
                fixed, time_ricucitura, workers,
                locked_slots_for_day=locks_d,
            )
            if ricuc_out is None:
                # Stage D: monolithic fallback for the whole day
                mono_out, _ = dec.solve_monolithic_day(
                    d, profs, triples, dc_value, time_mono, workers,
                    locked_slots_for_day=locks_d,
                    coteach_groups=coteach_groups,
                    support_assignments=support_assignments,
                    parallel_groups=parallel_groups,
                    group_assignments=group_assignments,
                    special_room_ctx=special_room_ctx,
                    total_room_capacity=total_room_capacity,
                    plessi_ctx=plessi_ctx,
                    dsl_hard_expressions=dsl_hard_expressions,
                )
                if mono_out is None:
                    failed_days.append(d)
                    days_per_day[d] = time.time() - t
                    if log:
                        print(f"[loop]   day {d} STAGE-C+MONO failed in "
                              f"{days_per_day[d]:.1f}s")
                    continue
                full_solution.update(mono_out)
                days_per_day[d] = time.time() - t
                if log:
                    print(f"[loop]   day {d} via MONO fallback (after "
                          f"Stage C) in {days_per_day[d]:.1f}s")
                continue
            full_solution.update(ricuc_out)
        else:
            full_solution.update(bridges_out)
            for out in cluster_solutions.values():
                full_solution.update(out)

        days_per_day[d] = time.time() - t
        if log:
            occ = sum(1 for k_id in cluster_solutions
                       for v in cluster_solutions[k_id].values() if v == 1)
            print(f"[loop]   day {d} ok in {days_per_day[d]:.1f}s "
                  f"({len(cluster_solutions)} cluster ok, "
                  f"{len(b_failed)} ricuc'd)")

    elapsed_days_total = time.time() - days_t0
    status = "ok" if not failed_days else \
             "partial" if full_solution else "master_failed"

    return {
        "full_solution": full_solution,
        "dc_value": dc_value,
        "failed_days": sorted(failed_days),
        "timings": {
            "master": elapsed_master,
            "days_total": elapsed_days_total,
            "days_per_day": days_per_day,
        },
        "cluster_sizes": cluster_sizes,
        "bridges_count": len(bridges_set),
        "status": status,
    }
