"""Temporal / curriculum / METIS decomposition runners.

Thin wrappers around engine/decomposition_*.py that snapshot locks,
feed native-lock + coteach + plessi context, persist the solution,
and optionally finish with ALNS.
"""
from __future__ import annotations

import os
import pickle
import sys

from .. import engine_io, models
from ..db import SessionLocal
from ..engine_paths import get_engine_dir
from ..run_manager import create_run, start_thread, update_run
from ..workspace import _run_workspace
from .hard_check import _hard_check_ctx_fresh, _load_dsl_hard_expressions
from .preflight import (
    _apply_locked_classrooms,
    _locked_day_count_from_snapshot,
    _locked_slots_by_day,
    _preflight_lock_check,
    _read_locked_lessons,
)


def _engine_scripts_dir() -> str:
    return str(get_engine_dir() / "scripts")


def run_decomposition_temporal(*, time_a: float = 60.0,
                               time_day: float = 30.0,
                               n_workers: int | None = None,
                               cpsat_workers_per_day: int = 2,
                               parallel: bool = True,
                               enforce_no_holes: bool = True,
                               run_alns: bool = False,
                               alns_budget_s: float = 300.0,
                               alns_T0: float = 5.0,
                               alns_alpha: float = 0.995) -> int:
    """Async run that orchestrates the temporal decomposition pipeline:

      1) master CP-SAT pre-distribution (cv2.solve_phase_a)
      2) ProcessPoolExecutor over the 6 days with cv2.solve_phase_b_for_day
      3) (optional) ALNS finishing on top of the ricucitura

    The work is delegated to engine/decomposition_temporal.py
    so the same code path is shared by the CLI and by the REST
    endpoint.
    """
    params = dict(time_a=time_a, time_day=time_day, n_workers=n_workers,
                  cpsat_workers_per_day=cpsat_workers_per_day,
                  parallel=parallel, enforce_no_holes=enforce_no_holes,
                  run_alns=run_alns, alns_budget_s=alns_budget_s,
                  alns_T0=alns_T0, alns_alpha=alns_alpha)
    _preflight_lock_check()
    run_id = create_run(
        "decomposition_temporal",
        "Decomposizione temporale (master + 6 day-solver paralleli)",
        None, params)

    def target(rid: int):
        with SessionLocal() as db:
            locked_snap = _read_locked_lessons(db)
            profs = engine_io.profs_dict_from_db(db)
        if not profs:
            raise RuntimeError(
                "Nessun assegnamento prof->classe; esegui prima "
                "Phase A (step 2)."
            )
        ws = _run_workspace(rid)
        profs_pkl = os.path.join(ws, "profs.pkl")
        with open(profs_pkl, "wb") as f:
            pickle.dump(profs, f)

        # Lazy import: engine/ contains the orchestrator
        exp_dir = _engine_scripts_dir()
        if exp_dir not in sys.path:
  # (harmless: engine_paths.ensure_engine_on_path() already handles this — audit A2)
            sys.path.insert(0, exp_dir)
        import decomposition_temporal as dec_t  # type: ignore

        update_run(rid, progress=0.05)
        print("[temporal] starting pipeline")
        # Native locks: feed both Phase A floor and per-day slot
        # constraints to the orchestrator. ALNS receives them too
        # (see step 5 below).
        locked_dc = _locked_day_count_from_snapshot(locked_snap)
        locked_by_day = _locked_slots_by_day(locked_snap)
        with SessionLocal() as _db_co:
            coteach_groups = engine_io.coteach_groups_for_solver(_db_co)
            group_assignments = engine_io.group_assignments_for_solver(
                _db_co)
            # 08b + 34 for the temporal decomposition (per-day, all classes).
            import cpsat_v2_timetable as cv2  # type: ignore
            _t_class_flags = engine_io.class_flags_from_db(_db_co)
            _t_special_room = cv2.build_special_room_ctx(_db_co)
            _t_cdl = engine_io.class_day_load_allowed_from_db(_db_co)
            _t_cfd = engine_io.class_free_days_from_db(_db_co)
            support_assignments = engine_io.support_assignments_from_db(_db_co)
            parallel_groups = engine_io.parallel_groups_for_solver(_db_co)
            _t_plessi = cv2.build_plessi_ctx(_db_co)
            # Audit H6: HARD DSL rules the CP compiler cannot emit; threaded
            # into each per-day solve's verify + no-good gate.
            _t_dsl_hard = _load_dsl_hard_expressions(_db_co)
        if locked_snap:
            print(f"[temporal] native lock path: {len(locked_snap)} "
                  f"locked lessons fed to solver")
        if coteach_groups:
            print(f"[temporal] {len(coteach_groups)} coteach groups "
                  f"fed to solver")
        if group_assignments:
            print(f"[temporal] {len(group_assignments)} group "
                  f"assignments fed to solver")
        result = dec_t.run_temporal_pipeline(
            profs_pkl,
            parallel=parallel,
            n_workers=n_workers,
            time_a=time_a,
            time_day=time_day,
            day_timeout=time_day * 6,   # generous wall cap
            cpsat_workers_per_day=cpsat_workers_per_day,
            enforce_no_holes=enforce_no_holes,
            log_progress=True,
            out_path=os.path.join(ws, "solution.pkl"),
            dc_out_path=os.path.join(ws, "dc.pkl"),
            locked_day_count=locked_dc or None,
            locked_by_day=locked_by_day or None,
            coteach_groups=coteach_groups or None,
            group_assignments=group_assignments or None,
            special_room_ctx=_t_special_room,
            class_flags=_t_class_flags,
            class_day_load_allowed=_t_cdl,
            class_free_days=_t_cfd,
            support_assignments=support_assignments or None,
            parallel_groups=parallel_groups or None,
            plessi_ctx=_t_plessi,
            dsl_hard_expressions=_t_dsl_hard,
        )
        update_run(rid, progress=0.85)

        full_solution = result["full_solution"]
        timings = result["timings"]
        failed_days = result["failed_days"]
        status = result["status"]

        import metaheuristics as meta  # type: ignore
        v0, m0 = meta.compute_soft(full_solution, profs)
        hard_ctx = _hard_check_ctx_fresh()
        feasible = meta.is_hard_feasible(full_solution, profs, verbose=False,
                                         **hard_ctx)
        print(f"[temporal] HARD feasible: {feasible}, SOFT obj={v0:.1f}")

        # Step 5: ALNS finishing stage (optional, sequential on the
        # ricucita solution). ALNS is lock-aware after Atom 5: locked
        # keys are passed via `locks=` and the destroy operators
        # never free them.
        if run_alns and feasible:
            print(f"[temporal] step 5: ALNS finishing for "
                  f"{alns_budget_s:.0f}s")
            try:
                import alns as alns_mod  # type: ignore
                dc_value = result["dc_value"]
                alns_locks = {(d["teacher_name"], d["class_name"],
                                d["subject"], int(d["day"]),
                                int(d["hour"]))
                               for d in locked_snap
                               if d.get("day") is not None
                                  and d.get("hour") is not None
                               } or None
                refined, _hist = alns_mod.run_alns(
                    full_solution, profs, dc_value, alns_budget_s,
                    log=False, workers=cpsat_workers_per_day,
                    T0=alns_T0, alpha=alns_alpha,
                    locks=alns_locks,
                )
                v1, m1 = meta.compute_soft(refined, profs)
                if meta.is_hard_feasible(refined, profs, verbose=False,
                                         **hard_ctx) \
                        and v1 <= v0:
                    print(f"[temporal] ALNS improved {v0:.1f} -> {v1:.1f}")
                    full_solution = refined
                    v0, m0 = v1, m1
                else:
                    print("[temporal] ALNS dropped (no improvement or "
                          "infeasible)")
            except Exception as e:
                print(f"[temporal] ALNS stage failed: {e}")

        # Persist the final solution
        with SessionLocal() as db:
            sid = engine_io.import_solution_into_db(
                db, full_solution,
                name=f"Temporal decomposition run {rid}",
                kind="phase_b_temporal",
                obj_value=float(v0),
                metrics={**m0, "feasible": feasible,
                         "master_s": round(timings["master"], 1),
                         "days_total_s": round(timings["days_total"], 1),
                         "days_max_s": round(timings["days_max"], 1),
                         "n_workers": result["n_workers"],
                         "parallel": result["parallel"],
                         "failed_days": failed_days,
                         "status": status},
                make_active=feasible,
            )
            # Native-lock path: solver placed the lessons; only
            # re-apply classroom_name + cotaught_with attributes.
            n_touched = _apply_locked_classrooms(db, sid, locked_snap)
            if n_touched:
                db.commit()
                print(f"[temporal] re-applied classroom on "
                      f"{n_touched} locked lessons (native path)")

        update_run(rid, progress=1.0,
                   metrics={"feasible": feasible,
                            "obj": float(v0),
                            "master_s": round(timings["master"], 1),
                            "days_total_s": round(timings["days_total"], 1),
                            "days_max_s": round(timings["days_max"], 1),
                            "n_workers": result["n_workers"],
                            "parallel": result["parallel"],
                            "failed_days": failed_days,
                            "status": status,
                            "solution_id": sid})

    start_thread(run_id, target)
    return run_id


# ----------------------------------------------------------------------
# DECOMPOSITION: per-curriculum
# ----------------------------------------------------------------------

def run_decomposition_curriculum(*, time_a: float = 60.0,
                                 time_bridges: float = 30.0,
                                 time_per_cluster: float = 30.0,
                                 time_ricucitura: float = 60.0,
                                 time_mono: float = 120.0,
                                 workers: int = 8,
                                 manual_groupings: dict | None = None,
                                 min_cluster_size: int = 3,
                                 run_alns: bool = False,
                                 alns_budget_s: float = 300.0) -> int:
    """Async run that partitions classes by curriculum_id, runs Stage
    A/B/C/monolithic loop, optionally chains ALNS finishing."""
    params = dict(time_a=time_a, time_bridges=time_bridges,
                  time_per_cluster=time_per_cluster,
                  time_ricucitura=time_ricucitura, time_mono=time_mono,
                  workers=workers, manual_groupings=manual_groupings,
                  min_cluster_size=min_cluster_size,
                  run_alns=run_alns, alns_budget_s=alns_budget_s)
    _preflight_lock_check()
    run_id = create_run(
        "decomposition_curriculum",
        "Decomposizione per curriculum (Stage A/B/C + opzionale ALNS)",
        None, params)

    def target(rid: int):
        with SessionLocal() as db:
            locked_snap = _read_locked_lessons(db)
            profs = engine_io.profs_dict_from_db(db)
            cls_to_curr = {}
            for c in db.query(models.SchoolClass).all():
                if c.curriculum_id is not None:
                    cur = db.query(models.Curriculum).filter_by(
                        id=c.curriculum_id).first()
                    cls_to_curr[c.name] = (cur.name if cur
                                           else "cur_" + str(c.curriculum_id))
                else:
                    cls_to_curr[c.name] = "_unknown"
        if not profs:
            raise RuntimeError("Nessun assegnamento prof->classe.")

        exp_dir = _engine_scripts_dir()
        if exp_dir not in sys.path:
  # (harmless: engine_paths.ensure_engine_on_path() already handles this — audit A2)
            sys.path.insert(0, exp_dir)
        import decomposition_curriculum as dec_c  # type: ignore
        auto = dec_c.auto_group_small_curricula(
            cls_to_curr, min_classes=min_cluster_size)
        manual = dict(auto)
        if manual_groupings:
            manual.update(manual_groupings)

        update_run(rid, progress=0.05)
        locked_dc = _locked_day_count_from_snapshot(locked_snap) or None
        locked_by_day = _locked_slots_by_day(locked_snap) or None
        with SessionLocal() as _db_co:
            coteach_groups = engine_io.coteach_groups_for_solver(_db_co)
            support_assignments = engine_io.support_assignments_from_db(
                _db_co)
            parallel_groups = engine_io.parallel_groups_for_solver(_db_co)
            group_assignments = engine_io.group_assignments_for_solver(
                _db_co)
            class_day_load_allowed = (
                engine_io.class_day_load_allowed_from_db(_db_co))
            # Biennio free-day rotation (class_free_days): reserving the empty
            # day per class in the DAY-COUNT is exactly what lets more classes
            # than rooms coexist (they take turns being off). Without it the
            # per-day solve over-fills the rooms on tight days and goes
            # INFEASIBLE. The temporal path already passes it; the curriculum /
            # metis paths dropped it -- found via the 90-class decomposition
            # failing on several days until the rotation was reinstated.
            class_free_days = engine_io.class_free_days_from_db(_db_co)
            import cpsat_v2_timetable as _cv2  # type: ignore
            _special_room = _cv2.build_special_room_ctx(_db_co)
            _plessi = _cv2.build_plessi_ctx(_db_co)
            # Audit H6: HARD DSL rules the CP compiler cannot emit force the
            # monolithic per-day path + verify/no-good gate (see metis).
            _curr_dsl_hard = _load_dsl_hard_expressions(_db_co)
        if locked_snap:
            print(f"[curriculum] native lock path: {len(locked_snap)} "
                  f"locked lessons fed to solver")
        if coteach_groups:
            print(f"[curriculum] {len(coteach_groups)} coteach groups")
        if group_assignments:
            print(f"[curriculum] {len(group_assignments)} group "
                  f"assignments (forced mono per-day)")
        result = dec_c.solve_with_curriculum_decomposition(
            profs, cls_to_curr, manual,
            time_a=time_a, time_bridges=time_bridges,
            time_per_cluster=time_per_cluster,
            time_ricucitura=time_ricucitura, time_mono=time_mono,
            workers=workers, log=True,
            locked_day_count=locked_dc,
            locked_by_day=locked_by_day,
            coteach_groups=coteach_groups or None,
            support_assignments=support_assignments or None,
            parallel_groups=parallel_groups or None,
            group_assignments=group_assignments or None,
            class_day_load_allowed=class_day_load_allowed,
            class_free_days=class_free_days,
            special_room_ctx=_special_room,
            plessi_ctx=_plessi,
            dsl_hard_expressions=_curr_dsl_hard,
        )
        update_run(rid, progress=0.85)
        full_solution = result["full_solution"]
        timings = result["timings"]
        failed_days = result["failed_days"]
        status = result["status"]

        import metaheuristics as meta  # type: ignore
        v0, m0 = meta.compute_soft(full_solution, profs)
        hard_ctx = _hard_check_ctx_fresh()
        feasible = meta.is_hard_feasible(full_solution, profs, verbose=False,
                                         **hard_ctx)

        if run_alns and feasible:
            try:
                import alns as alns_mod  # type: ignore
                alns_locks = {(d["teacher_name"], d["class_name"],
                                d["subject"], int(d["day"]),
                                int(d["hour"]))
                               for d in locked_snap
                               if d.get("day") is not None
                                  and d.get("hour") is not None
                               } or None
                refined, _ = alns_mod.run_alns(
                    full_solution, profs, result["dc_value"],
                    alns_budget_s, log=False, workers=2,
                    locks=alns_locks)
                v1, m1 = meta.compute_soft(refined, profs)
                if (meta.is_hard_feasible(refined, profs, verbose=False,
                                          **hard_ctx)
                        and v1 <= v0):
                    full_solution, v0, m0 = refined, v1, m1
            except Exception as e:
                print("[curriculum] ALNS skipped: " + str(e))

        with SessionLocal() as db:
            sid = engine_io.import_solution_into_db(
                db, full_solution,
                name="Curriculum decomposition run " + str(rid),
                kind="phase_b_curriculum",
                obj_value=float(v0),
                metrics={**m0, "feasible": feasible,
                         "master_s": round(timings["master"], 1),
                         "days_total_s": round(timings["days_total"], 1),
                         "cluster_sizes": result["cluster_sizes"],
                         "bridges_count": result["bridges_count"],
                         "failed_days": failed_days, "status": status},
                make_active=feasible,
            )
            n_touched = _apply_locked_classrooms(db, sid, locked_snap)
            if n_touched:
                db.commit()
                print(f"[curriculum] re-applied classroom on "
                      f"{n_touched} locked lessons (native path)")
        update_run(rid, progress=1.0,
                   metrics={"feasible": feasible, "obj": float(v0),
                            "master_s": round(timings["master"], 1),
                            "days_total_s": round(timings["days_total"], 1),
                            "cluster_sizes": result["cluster_sizes"],
                            "bridges_count": result["bridges_count"],
                            "failed_days": failed_days,
                            "status": status, "solution_id": sid})

    start_thread(run_id, target)
    return run_id


# ----------------------------------------------------------------------
# DECOMPOSITION: METIS k-way
# ----------------------------------------------------------------------

def run_decomposition_metis(*, time_a: float = 60.0,
                            time_bridges: float = 30.0,
                            time_per_cluster: float = 30.0,
                            time_ricucitura: float = 60.0,
                            time_mono: float = 120.0,
                            workers: int = 8,
                            k: int | None = None,
                            imbalance: float = 1.05,
                            run_alns: bool = False,
                            alns_budget_s: float = 300.0) -> int:
    """Async run that partitions classes via pymetis k-way (or pure-
    Python fallback) + Stage A/B/C/monolithic loop."""
    params = dict(time_a=time_a, time_bridges=time_bridges,
                  time_per_cluster=time_per_cluster,
                  time_ricucitura=time_ricucitura, time_mono=time_mono,
                  workers=workers, k=k, imbalance=imbalance,
                  run_alns=run_alns, alns_budget_s=alns_budget_s)
    _preflight_lock_check()
    run_id = create_run(
        "decomposition_metis",
        "Decomposizione METIS k-way",
        None, params)

    def target(rid: int):
        with SessionLocal() as db:
            locked_snap = _read_locked_lessons(db)
            profs = engine_io.profs_dict_from_db(db)
        if not profs:
            raise RuntimeError("Nessun assegnamento prof->classe.")

        exp_dir = _engine_scripts_dir()
        if exp_dir not in sys.path:
  # (harmless: engine_paths.ensure_engine_on_path() already handles this — audit A2)
            sys.path.insert(0, exp_dir)
        import decomposition_metis as dec_m  # type: ignore
        if not dec_m._has_pymetis():
            print("[metis] pymetis non disponibile, uso fallback "
                  "Python balanced k-way (qualita' equivalente per "
                  "n < 200 classi).")

        update_run(rid, progress=0.05)
        locked_dc = _locked_day_count_from_snapshot(locked_snap) or None
        locked_by_day = _locked_slots_by_day(locked_snap) or None
        with SessionLocal() as _db_co:
            coteach_groups = engine_io.coteach_groups_for_solver(_db_co)
            support_assignments = engine_io.support_assignments_from_db(
                _db_co)
            parallel_groups = engine_io.parallel_groups_for_solver(_db_co)
            group_assignments = engine_io.group_assignments_for_solver(
                _db_co)
            class_day_load_allowed = (
                engine_io.class_day_load_allowed_from_db(_db_co))
            # Biennio free-day rotation (class_free_days): reserving the empty
            # day per class in the DAY-COUNT is exactly what lets more classes
            # than rooms coexist (they take turns being off). Without it the
            # per-day solve over-fills the rooms on tight days and goes
            # INFEASIBLE. The temporal path already passes it; the curriculum /
            # metis paths dropped it -- found via the 90-class decomposition
            # failing on several days until the rotation was reinstated.
            class_free_days = engine_io.class_free_days_from_db(_db_co)
            import cpsat_v2_timetable as _cv2  # type: ignore
            _special_room = _cv2.build_special_room_ctx(_db_co)
            _plessi = _cv2.build_plessi_ctx(_db_co)
            # Audit H6: HARD DSL rules the CP compiler cannot emit. When
            # present, the loop is forced onto the monolithic per-day path
            # and each day is verify + no-good refined against them.
            _metis_dsl_hard = _load_dsl_hard_expressions(_db_co)
        if locked_snap:
            print(f"[metis] native lock path: {len(locked_snap)} "
                  f"locked lessons fed to solver")
        if coteach_groups:
            print(f"[metis] {len(coteach_groups)} coteach groups")
        if group_assignments:
            print(f"[metis] {len(group_assignments)} group "
                  f"assignments (forced mono per-day)")
        result = dec_m.solve_with_metis_decomposition(
            profs, k=k, imbalance=imbalance,
            time_a=time_a, time_bridges=time_bridges,
            time_per_cluster=time_per_cluster,
            time_ricucitura=time_ricucitura, time_mono=time_mono,
            workers=workers, log=True,
            locked_day_count=locked_dc,
            locked_by_day=locked_by_day,
            coteach_groups=coteach_groups or None,
            support_assignments=support_assignments or None,
            parallel_groups=parallel_groups or None,
            group_assignments=group_assignments or None,
            class_day_load_allowed=class_day_load_allowed,
            class_free_days=class_free_days,
            special_room_ctx=_special_room,
            plessi_ctx=_plessi,
            dsl_hard_expressions=_metis_dsl_hard,
        )
        update_run(rid, progress=0.85)
        full_solution = result["full_solution"]
        timings = result["timings"]
        failed_days = result["failed_days"]
        status = result["status"]

        import metaheuristics as meta  # type: ignore
        v0, m0 = meta.compute_soft(full_solution, profs)
        hard_ctx = _hard_check_ctx_fresh()
        feasible = meta.is_hard_feasible(full_solution, profs, verbose=False,
                                         **hard_ctx)

        if run_alns and feasible:
            try:
                import alns as alns_mod  # type: ignore
                alns_locks = {(d["teacher_name"], d["class_name"],
                                d["subject"], int(d["day"]),
                                int(d["hour"]))
                               for d in locked_snap
                               if d.get("day") is not None
                                  and d.get("hour") is not None
                               } or None
                refined, _ = alns_mod.run_alns(
                    full_solution, profs, result["dc_value"],
                    alns_budget_s, log=False, workers=2,
                    locks=alns_locks)
                v1, m1 = meta.compute_soft(refined, profs)
                if (meta.is_hard_feasible(refined, profs, verbose=False,
                                          **hard_ctx)
                        and v1 <= v0):
                    full_solution, v0, m0 = refined, v1, m1
            except Exception as e:
                print("[metis] ALNS skipped: " + str(e))

        with SessionLocal() as db:
            sid = engine_io.import_solution_into_db(
                db, full_solution,
                name="METIS decomposition run " + str(rid),
                kind="phase_b_metis",
                obj_value=float(v0),
                metrics={**m0, "feasible": feasible,
                         "master_s": round(timings["master"], 1),
                         "days_total_s": round(timings["days_total"], 1),
                         "cluster_sizes": result["cluster_sizes"],
                         "bridges_count": result["bridges_count"],
                         "failed_days": failed_days, "status": status},
                make_active=feasible,
            )
            n_touched = _apply_locked_classrooms(db, sid, locked_snap)
            if n_touched:
                db.commit()
                print(f"[metis] re-applied classroom on "
                      f"{n_touched} locked lessons (native path)")
        update_run(rid, progress=1.0,
                   metrics={"feasible": feasible, "obj": float(v0),
                            "master_s": round(timings["master"], 1),
                            "days_total_s": round(timings["days_total"], 1),
                            "cluster_sizes": result["cluster_sizes"],
                            "bridges_count": result["bridges_count"],
                            "failed_days": failed_days,
                            "status": status, "solution_id": sid})

    start_thread(run_id, target)
    return run_id
