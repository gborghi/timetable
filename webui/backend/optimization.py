"""High-level wrappers that turn DB state into engine-friendly inputs,
invoke the engine/ functions, and persist the results back to the DB.

Each public function returns the run_id; the actual work runs in a thread
managed by run_manager."""
from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import pickle
import random
import sys
import threading
import time
from collections import defaultdict
from typing import Any

# This import has to come BEFORE the engine modules:
from . import engine_paths  # noqa: F401  (sys.path side effect)

from sqlalchemy.orm import Session

from . import engine_io, models
from .db import SessionLocal
from .run_manager import (
    create_run,
    get_buffer,
    start_thread,
    update_run,
    capture_stdout,
)

DAYS = list(range(1, 7))
HOURS = list(range(8, 14))


def _runs_dir() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.normpath(os.path.join(here, "..", "data", "runs"))
    os.makedirs(out, exist_ok=True)
    return out


def _run_workspace(run_id: int) -> str:
    p = os.path.join(_runs_dir(), str(run_id))
    os.makedirs(p, exist_ok=True)
    return p


# ----------------------------------------------------------------------
# Step 1: mock generation
# ----------------------------------------------------------------------


def _set_app_state(db, key: str, value: str) -> None:
    """Upsert a key/value pair in the AppState singleton table. Used to
    track e.g. the last imported school profile so the UI can default
    its labels to the right name."""
    row = db.query(models.AppState).filter(
        models.AppState.key == key
    ).first()
    if row is None:
        db.add(models.AppState(key=key, value=str(value)))
    else:
        row.value = str(value)
    db.commit()


def get_app_state(db, key: str, default: str = "") -> str:
    row = db.query(models.AppState).filter(
        models.AppState.key == key
    ).first()
    return row.value if row else default


def run_mock_generation(profile: str, mode: str, margin: float,
                        custom_curricula: dict[str, int] | None,
                        base_max_hours: int) -> int:
    """Spawn a mock-school generation run using big_mock_school's API."""
    params = dict(profile=profile, mode=mode, margin=margin,
                  custom_curricula=custom_curricula,
                  base_max_hours=base_max_hours)
    run_id = create_run("mock", f"Mock {profile}", profile, params)

    def target(rid: int):
        import big_mock_school as bms  # type: ignore
        import mock_classes2 as mc  # type: ignore

        if profile == "custom" and custom_curricula:
            print(f"[mock] custom curricula: {custom_curricula}")
            curricula, _, _ = mc.generate_curriculum_subjects()
            cconcorsodict, cconcorso_list, cconcorsopersubject = (
                mc.generate_subject_groups()
            )
            school_classes = mc.create_school_classes_with_curriculum(
                curricula, curriculaclasses=custom_curricula
            )
            hours_needed = mc.calculate_teachers_needed(school_classes)
            if mode == "tight":
                teachers = bms.generate_tight_teachers(
                    hours_needed, mc.day_weights,
                    cconcorsopersubject, cconcorso_list,
                    margin=margin, base_max_hours=base_max_hours,
                )
            elif mode == "legacy":
                teachers = mc.generate_required_teachers(
                    hours_needed, mc.day_weights,
                    cconcorsopersubject, cconcorso_list,
                )
            else:
                teachers = bms.generate_aggregated_teachers(
                    hours_needed, mc.day_weights,
                    cconcorsopersubject, cconcorso_list,
                    margin=margin, base_max_hours=base_max_hours,
                )
            classes_dump = []
            for cl in school_classes:
                classes_dump.append({
                    "name": cl.name, "year": cl.year,
                    "section": cl.section,
                    "curriculum": cl.curriculum,
                    "subjects": dict(cl.subjects),
                })
            teachers_dump = []
            for t in teachers:
                teachers_dump.append({
                    "name": t.name, "group": t.subject_group.name,
                    "max_hours": t.max_hours,
                    "free_day": t.free_day,
                    "weights": dict(t.weights),
                })
            data = {
                "profile": "custom",
                "classes": classes_dump,
                "teachers": teachers_dump,
                "cconcorsopersubject": dict(
                    (k, dict(v)) for k, v in cconcorsopersubject.items()
                ),
                "curriculum_scores": dict(mc.curriculum_scores),
            }
        else:
            data = bms.build_dataset(profile, mode=mode, margin=margin)

        ws = _run_workspace(rid)
        out_path = os.path.join(ws, "school.pkl")
        with open(out_path, "wb") as f:
            pickle.dump(data, f)
        print(f"[mock] saved school dump to {out_path}")
        # Push into DB (replace mode)
        with SessionLocal() as db:
            engine_io.import_school_into_db(db, data, replace=True)
            n_classes = db.query(models.SchoolClass).count()
            n_teachers = db.query(models.Teacher).count()
            # Track which profile is currently in DB so the Workflow
            # tab + Runs tab can show the right name.
            _set_app_state(db, "last_profile", profile)
        update_run(rid, progress=1.0, metrics={
            "classes": n_classes, "teachers": n_teachers,
        })
        print(f"[mock] DB now has {n_classes} classes and "
              f"{n_teachers} teachers")

    start_thread(run_id, target)
    return run_id


# ----------------------------------------------------------------------
# Import a pre-existing engine/scripts/ pickle (small/big/medium/...)
# ----------------------------------------------------------------------


def import_engine_profile(profile: str, use_optimized: bool,
                               *,
                               import_curricula: bool = True,
                               import_classrooms: bool = True,
                               import_students: bool = True,
                               students_seed: int = 42) -> int:
    params = dict(profile=profile, use_optimized=use_optimized,
                  import_curricula=import_curricula,
                  import_classrooms=import_classrooms,
                  import_students=import_students)
    run_id = create_run("import", f"Import {profile}", profile, params)
    here = os.path.dirname(os.path.abspath(__file__))
    engine_scripts_dir = os.path.normpath(
        os.path.join(here, "..", "..", "engine", "scripts")
    )

    def target(rid: int):
        school_pkl = os.path.join(engine_scripts_dir, f"school_{profile}.pkl")
        profs_pkl = os.path.join(engine_scripts_dir, f"profs_{profile}.pkl")
        sol_optimized = os.path.join(
            engine_scripts_dir, f"solution_timetable_{profile}_optimized.pkl"
        )
        sol_decomposed = os.path.join(
            engine_scripts_dir, f"solution_timetable_{profile}_decomposed.pkl"
        )
        sol_plain = os.path.join(
            engine_scripts_dir, f"solution_timetable_{profile}.pkl"
        )
        # MEGA pipeline (run_mega_pipeline.py) emits non-canonical
        # filenames: solution_mega_temporal_alns.pkl is the post-ALNS
        # polished result (the equivalent of *_optimized.pkl), and
        # solution_temporal_mega.pkl is the pre-ALNS temporal-decomposed
        # result (the equivalent of *_decomposed.pkl). Honour these as
        # additional fallbacks before giving up.
        sol_alt_optimized = os.path.join(
            engine_scripts_dir, f"solution_{profile}_temporal_alns.pkl"
        )
        sol_alt_decomposed = os.path.join(
            engine_scripts_dir, f"solution_temporal_{profile}.pkl"
        )
        if not os.path.exists(school_pkl):
            raise FileNotFoundError(
                f"school_{profile}.pkl not found in engine/scripts/"
            )
        with open(school_pkl, "rb") as f:
            school = pickle.load(f)
        print(f"[import] loaded {school_pkl}: "
              f"{len(school.get('classes', []))} classes, "
              f"{len(school.get('teachers', []))} teachers")
        with SessionLocal() as db:
            engine_io.import_school_into_db(db, school, replace=True)
            _set_app_state(db, "last_profile", profile)

        # ---------- Pool data: curricula / classrooms / students ----------
        if import_curricula:
            from . import seed_curricula
            try:
                seed_curricula.seed(force=False)
                # link curriculum_id on classes by matching the legacy
                # curriculum string column
                with SessionLocal() as db:
                    codes_map = {c.code: c.id
                                 for c in db.query(models.Curriculum).all()}
                    linked = 0
                    for cl in db.query(models.SchoolClass).all():
                        if cl.curriculum and cl.curriculum_id is None:
                            cid = codes_map.get(cl.curriculum)
                            if cid is not None:
                                cl.curriculum_id = cid
                                linked += 1
                    db.commit()
                print(f"[import] curricula seeded; {linked} classes linked")
            except Exception as e:
                print(f"[import] curricula seed skipped: {e}")

        if import_classrooms:
            try:
                summary = auto_generate_classrooms(overrides=None)
                print(f"[import] classrooms generated: "
                      f"{summary.get('created', 0)} rooms "
                      f"(school size {summary.get('n_classes', 0)})")
            except Exception as e:
                print(f"[import] classroom generation skipped: {e}")

        if import_students:
            from . import mock_students
            try:
                with SessionLocal() as db:
                    rep = mock_students.generate_students_for_db(
                        db, seed=int(students_seed), force=True,
                    )
                print(f"[import] students generated: "
                      f"{rep.get('n_inserted', 0)} students in "
                      f"{rep.get('n_classes_populated', 0)} classes")
            except Exception as e:
                print(f"[import] student generation skipped: {e}")
        # -----------------------------------------------------------------

        if os.path.exists(profs_pkl):
            with open(profs_pkl, "rb") as f:
                profs = pickle.load(f)
            print(f"[import] loaded {profs_pkl}: {len(profs)} teachers")
            with SessionLocal() as db:
                n = engine_io.import_profs_into_db(db, profs)
                print(f"[import] {n} assignments imported")
        sol_path = None
        if use_optimized and os.path.exists(sol_optimized):
            sol_path = sol_optimized
        elif use_optimized and os.path.exists(sol_alt_optimized):
            sol_path = sol_alt_optimized
        elif os.path.exists(sol_decomposed):
            sol_path = sol_decomposed
        elif os.path.exists(sol_alt_decomposed):
            sol_path = sol_alt_decomposed
        elif os.path.exists(sol_plain):
            sol_path = sol_plain
        if sol_path:
            with open(sol_path, "rb") as f:
                sol = pickle.load(f)
            print(f"[import] loaded {sol_path}: {len(sol)} cells")
            with SessionLocal() as db:
                profs_db = engine_io.profs_dict_from_db(db)
            try:
                import metaheuristics as meta  # type: ignore
                v, m = meta.compute_soft(sol, profs_db)
            except Exception:
                v, m = 0.0, {}
            with SessionLocal() as db:
                sid = engine_io.import_solution_into_db(
                    db, sol,
                    name=f"Imported {profile} ({os.path.basename(sol_path)})",
                    kind="imported",
                    obj_value=float(v),
                    metrics=m,
                    make_active=True,
                )
                update_run(rid, solution_id=sid, obj_value=float(v),
                           metrics=m)
                print(f"[import] solution stored as id={sid}, "
                      f"obj={v}, metrics={m}")
        update_run(rid, progress=1.0)

    start_thread(run_id, target)
    return run_id


# ----------------------------------------------------------------------
# Step 2: assignment (cpsat_v2_assignment)
# ----------------------------------------------------------------------


def run_assignment(time_limit_s: float, workers: int, log: bool,
                   criterion: str = "balance_weight",
                   custom_expression: str | None = None) -> int:
    """Phase A. When `criterion="custom"` and `custom_expression` is
    set, the DSL-driven solver is used; otherwise we look up the
    preset by key and run the same DSL pipeline with the preset's
    expression. The legacy `cpsat_v2_assignment.solve_assignment`
    code path is kept as a no-criterion fallback (criterion="legacy")
    for compatibility with old callers."""
    params = dict(time_limit_s=time_limit_s, workers=workers, log=log,
                  criterion=criterion,
                  custom_expression=custom_expression)
    run_id = create_run(
        "assignment",
        f"Assegnazione docenti->classi ({criterion})",
        None, params,
    )

    def target(rid: int):
        with SessionLocal() as db:
            data = engine_io.school_dict_from_db(db)
        if not data["classes"] or not data["teachers"]:
            raise RuntimeError("DB vuoto: importa o genera una scuola.")

        if criterion == "legacy":
            import cpsat_v2_assignment as ca  # type: ignore
            cattedre, _solver, status = ca.solve_assignment(
                data, time_limit_s=time_limit_s,
                workers=workers, log=log,
            )
            metrics = {"status": str(status)}
        else:
            from .utils import objective_dsl
            if criterion == "custom":
                expr = (custom_expression or "").strip()
                if not expr:
                    raise RuntimeError(
                        "criterion=custom richiede custom_expression"
                    )
            else:
                preset = objective_dsl.get_preset(criterion)
                if preset is None:
                    raise RuntimeError(
                        f"Preset Phase A sconosciuto: {criterion!r}. "
                        f"Disponibili: "
                        f"{[p[0] for p in objective_dsl.PRESETS]}"
                    )
                expr = preset[3]
            print(f"[assign] criterion={criterion}, expression:\n  {expr}")

            import cpsat_assignment_dsl as ca_dsl  # type: ignore
            cattedre, _solver, status, dsl_metrics = (
                ca_dsl.solve_assignment_dsl(
                    data, expr,
                    time_limit_s=time_limit_s, workers=workers, log=log,
                )
            )
            metrics = {"status": str(status), **dsl_metrics}

        ws = _run_workspace(rid)
        with open(os.path.join(ws, "cattedre.pkl"), "wb") as f:
            pickle.dump(cattedre, f)
        with SessionLocal() as db:
            n = engine_io.import_assignments_into_db(db, cattedre)
        print(f"[assign] saved {n} assignments to DB")
        metrics["assignments"] = n
        update_run(rid, progress=1.0, metrics=metrics)

    start_thread(run_id, target)
    return run_id


# ----------------------------------------------------------------------
# Manual override of an assignment with HARD validation
# ----------------------------------------------------------------------


def manual_assignment(db: Session, class_name: str, subject: str,
                      teacher_name: str, locked: bool = True
                      ) -> tuple[bool, str, models.Assignment | None]:
    cl = db.query(models.SchoolClass).filter(
        models.SchoolClass.name == class_name
    ).first()
    if cl is None:
        return False, f"Classe {class_name} inesistente", None
    csubj = db.query(models.ClassSubject).filter(
        models.ClassSubject.class_id == cl.id,
        models.ClassSubject.subject == subject,
    ).first()
    if csubj is None:
        return (False,
                f"La classe {class_name} non ha la materia {subject}",
                None)
    t = db.query(models.Teacher).filter(
        models.Teacher.name == teacher_name
    ).first()
    if t is None:
        return False, f"Docente {teacher_name} inesistente", None
    # subject compatibility
    teacher_subjects = {ts.subject for ts in t.subjects}
    if teacher_subjects and subject not in teacher_subjects:
        return (False,
                f"Il docente {teacher_name} non insegna {subject}",
                None)
    # cattedra capacity check
    other_assigns = db.query(models.Assignment).filter(
        models.Assignment.teacher_id == t.id,
    ).all()
    used = sum(a.hours for a in other_assigns
               if not (a.class_id == cl.id and a.subject == subject))
    new_total = used + csubj.hours_per_week
    if new_total > t.max_hours:
        return (False,
                f"Sforamento ore-cattedra: {new_total} > {t.max_hours}",
                None)
    # Replace existing
    existing = db.query(models.Assignment).filter(
        models.Assignment.class_id == cl.id,
        models.Assignment.subject == subject,
    ).first()
    if existing is not None:
        existing.teacher_id = t.id
        existing.hours = csubj.hours_per_week
        existing.locked = locked
        new = existing
    else:
        new = models.Assignment(
            class_id=cl.id, teacher_id=t.id,
            subject=subject, hours=csubj.hours_per_week,
            locked=locked,
        )
        db.add(new)
    db.commit()
    return True, "ok", new


# ----------------------------------------------------------------------
# Step 3: Phase B (decomposed) — uses decomposition_spectral_v2
# ----------------------------------------------------------------------


def run_phase_b(k: int, time_a: float, time_bridges: float,
                time_cluster: float, time_ricucitura: float,
                time_mono: float, workers: int, log: bool,
                use_decomposition: bool = True,
                optimize_rooms: bool = False,
                rooms_time_limit_s: float = 30.0,
                rooms_prefer_home: bool = True) -> int:
    params = dict(k=k, time_a=time_a, time_bridges=time_bridges,
                  time_cluster=time_cluster, time_ricucitura=time_ricucitura,
                  time_mono=time_mono, workers=workers, log=log,
                  use_decomposition=use_decomposition,
                  optimize_rooms=optimize_rooms,
                  rooms_time_limit_s=rooms_time_limit_s,
                  rooms_prefer_home=rooms_prefer_home)
    _preflight_lock_check()
    run_id = create_run("phase_b", "Schedulazione orario", None, params)

    def target(rid: int):
        # Read locked Lessons BEFORE running anything. The native-lock
        # CP-SAT path (monolithic only for now) feeds them to the
        # solver as constraints; the decomposed path still relies on
        # snapshot/restore -- see TODO below.
        with SessionLocal() as db:
            locked_snap = _snapshot_locked_lessons(db)
            profs = engine_io.profs_dict_from_db(db)
            coteach_groups = engine_io.coteach_groups_for_solver(db)
            support_assignments = engine_io.support_assignments_from_db(db)
            potenziamento_assignments = (
                engine_io.potenziamento_assignments_from_db(db))
        if locked_snap:
            print(f"[phaseB] {len(locked_snap)} locked lessons "
                  f"({'native CP-SAT' if not use_decomposition else 'snapshot/restore'} path)")
        if coteach_groups:
            print(f"[phaseB] {len(coteach_groups)} coteach groups "
                  f"(shared mode)")
        if support_assignments:
            print(f"[phaseB] {len(support_assignments)} support "
                  f"(sostegno) assignments")
        if potenziamento_assignments:
            print(f"[phaseB] {len(potenziamento_assignments)} "
                  f"potenziamento assignments")
        if not profs:
            raise RuntimeError(
                "Nessun assegnamento prof->classe; esegui prima "
                "l'assegnazione (step 2)."
            )
        ws = _run_workspace(rid)
        with open(os.path.join(ws, "profs.pkl"), "wb") as f:
            pickle.dump(profs, f)

        import cpsat_v2_timetable as cv2  # type: ignore
        import metaheuristics as meta  # type: ignore
        classes, triples, class_profs = cv2.build_indices(profs)
        print(f"[phaseB] {len(profs)} profs, {len(classes)} classes, "
              f"{len(triples)} triples")
        update_run(rid, progress=0.05)
        # Phase A inside the timetable: day_count. Native locks are
        # passed both on the monolithic and on the decomposed path
        # (decomposed forwards them to the 4 stages below).
        locked_dc = _locked_day_count_from_snapshot(locked_snap)
        locked_by_day = _locked_slots_by_day(locked_snap)
        dc_value = cv2.solve_phase_a(
            profs, classes, triples, class_profs,
            time_limit=time_a, workers=workers, log=log,
            locked_day_count=locked_dc or None,
            coteach_groups=coteach_groups or None,
            support_assignments=support_assignments or None,
            potenziamento_assignments=potenziamento_assignments or None,
        )
        with open(os.path.join(ws, "phase_a_dc.pkl"), "wb") as f:
            pickle.dump(dc_value, f)
        update_run(rid, progress=0.20)

        full_solution: dict = {}
        if use_decomposition and len(classes) >= 8:
            import decomposition_spectral_v2 as dec  # type: ignore
            M, classes_v, _ = dec.build_adjacency(profs)
            labels, _ = dec.spectral_cluster(M, k)
            bridges, cl_to_label = dec.find_bridges(profs, classes_v, labels)
            classes_per_cluster: dict[int, set] = defaultdict(set)
            for c, lbl in cl_to_label.items():
                classes_per_cluster[lbl].add(c)
            print(f"[phaseB] cluster sizes="
                  f"{ {int(c): len(s) for c, s in classes_per_cluster.items()} }, "
                  f"bridges={len(bridges)}/{len(profs)}")
            bridges_set = set(bridges.keys())
            bridge_solutions: dict[int, dict] = {}
            a_failed = []
            for di, d in enumerate(DAYS):
                out, status = dec.stage_a_bridges(
                    d, profs, bridges_set, triples, dc_value,
                    time_bridges, workers,
                    locked_slots_for_day=locked_by_day.get(d) or None,
                )
                if out is None:
                    a_failed.append(d)
                else:
                    bridge_solutions[d] = out
                # Stage A spans 0.20 -> 0.40 of the run.
                update_run(rid,
                           progress=0.20 + 0.20 * (di + 1) / max(len(DAYS), 1))
            cluster_solutions: dict[tuple[int, int], dict] = {}
            b_failed: dict[int, set] = defaultdict(set)
            for di, d in enumerate(DAYS):
                if d not in bridge_solutions:
                    continue
                for k_id in sorted(classes_per_cluster,
                                    key=lambda kk: -len(classes_per_cluster[kk])):
                    cl_set = classes_per_cluster[k_id]
                    if not cl_set:
                        continue
                    out, status = dec.stage_b_cluster_internals(
                        cl_set, d, profs, bridges_set, triples, dc_value,
                        bridge_solutions[d], time_cluster, workers,
                        locked_slots_for_day=locked_by_day.get(d) or None,
                    )
                    if out is None:
                        b_failed[d].add(k_id)
                    else:
                        cluster_solutions[(k_id, d)] = out
                # Stage B spans 0.40 -> 0.80 of the run.
                update_run(rid,
                           progress=0.40 + 0.40 * (di + 1) / max(len(DAYS), 1))
            for d in DAYS:
                if d in bridge_solutions:
                    full_solution.update(bridge_solutions[d])
                for k_id in classes_per_cluster:
                    if (k_id, d) in cluster_solutions:
                        full_solution.update(cluster_solutions[(k_id, d)])
            days_C = sorted(set(b_failed.keys()) | set(a_failed))
            c_failed = []
            n_C = max(len(days_C), 1)
            for ci, d in enumerate(days_C):
                succ = {}
                for k_id in classes_per_cluster:
                    if k_id in b_failed.get(d, set()):
                        continue
                    if (k_id, d) in cluster_solutions:
                        succ.update(cluster_solutions[(k_id, d)])
                out, status = dec.stage_c_ricucitura(
                    d, profs, bridges_set, triples, dc_value, succ,
                    time_ricucitura, workers,
                    locked_slots_for_day=locked_by_day.get(d) or None,
                )
                if out is None:
                    c_failed.append(d)
                else:
                    full_solution = {
                        kk: vv for kk, vv in full_solution.items()
                        if kk[3] != d
                    }
                    full_solution.update(out)
                # Stage C ricucitura spans 0.80 -> 0.90 of the run.
                update_run(rid, progress=0.80 + 0.10 * (ci + 1) / n_C)
            for d in c_failed:
                out, status = dec.solve_monolithic_day(
                    d, profs, triples, dc_value,
                    time_mono, workers,
                    locked_slots_for_day=locked_by_day.get(d) or None,
                )
                if out is not None:
                    full_solution = {
                        kk: vv for kk, vv in full_solution.items()
                        if kk[3] != d
                    }
                    full_solution.update(out)
        else:
            # monolithic per day -- native locks + coteach + sostegno
            for d in DAYS:
                out, status = cv2.solve_phase_b_for_day(
                    d, profs, classes, triples, class_profs, dc_value,
                    time_limit=time_mono, workers=workers, log=log,
                    locked_slots_for_day=locked_by_day.get(d, []),
                    coteach_groups=coteach_groups or None,
                    support_assignments=support_assignments or None,
                )
                if out is None and locked_by_day.get(d):
                    raise RuntimeError(
                        f"Phase B (giorno {d}) INFEASIBLE: i lock di "
                        f"quel giorno sono incompatibili con i vincoli "
                        f"correnti. Rimuovi o adatta lock e ritenta."
                    )
                if out is not None:
                    full_solution.update(out)

        with open(os.path.join(ws, "solution.pkl"), "wb") as f:
            pickle.dump(full_solution, f)

        v, m = meta.compute_soft(full_solution, profs)
        feasible = meta.is_hard_feasible(full_solution, profs, verbose=False)
        with SessionLocal() as db:
            sid = engine_io.import_solution_into_db(
                db, full_solution,
                name=f"Phase B run {rid}",
                kind="phase_b",
                obj_value=float(v),
                metrics={**m, "feasible": feasible},
                make_active=True,
            )
            # Native-lock path (both monolithic and decomposed):
            # the solver placed the locked lessons; we only re-apply
            # classroom_name + cotaught_with attributes.
            n_touched = _apply_locked_classrooms(db, sid, locked_snap)
            if n_touched:
                db.commit()
                print(f"[phaseB] re-applied classroom on "
                      f"{n_touched} locked lessons (native path)")
        rooms_metrics: dict[str, Any] = {}
        if optimize_rooms:
            update_run(rid, progress=0.95)
            print("[phaseB] running joint classroom-assignment step")
            try:
                rooms_metrics = _apply_rooms_to_solution(
                    sid, time_limit_s=rooms_time_limit_s,
                    workers=workers, prefer_home=rooms_prefer_home,
                    log_prefix="phaseB.rooms", log=False,
                )
            except Exception as e:  # noqa: BLE001
                print(f"[phaseB] rooms step failed: {e}")
                rooms_metrics = {"rooms_error": str(e)}
        update_run(rid, solution_id=sid, obj_value=float(v),
                   metrics={**m, "feasible": feasible, **rooms_metrics},
                   progress=1.0)
        print(f"[phaseB] solution id={sid} obj={v} metrics={m} rooms={rooms_metrics}")

    start_thread(run_id, target)
    return run_id


# ----------------------------------------------------------------------
# Step 4-7: metaheuristic stages on top of the active solution
# ----------------------------------------------------------------------


def _load_phase_a_dc(profs: dict) -> dict:
    """Compute Phase A (day_count) lazily if not cached."""
    import cpsat_v2_timetable as cv2  # type: ignore
    classes, triples, class_profs = cv2.build_indices(profs)
    return cv2.solve_phase_a(
        profs, classes, triples, class_profs,
        time_limit=30, workers=4, log=False,
    )


def _restore_dc_from_solution(sol: dict) -> dict:
    """Derive day_count from an already-feasible solution.
    dc[(p,cl,subj,d)] = sum over h of sol[(p,cl,subj,d,h)]."""
    out: dict = defaultdict(int)
    for k, v in sol.items():
        if v != 1:
            continue
        p, cl, subj, d, h = k
        out[(p, cl, subj, d)] += 1
    return dict(out)


def run_meta(stage: str, budget_s: float, workers: int, log: bool,
             *, n_cycles: int = 3, ts_budget_per_cycle: float = 20.0,
             sa_T0: float = 10.0, sa_alpha: float = 0.995,
             tabu_size: int = 80,
             optimize_rooms: bool = False,
             rooms_time_limit_s: float = 30.0,
             rooms_prefer_home: bool = True,
             alns_T0: float = 5.0,
             alns_alpha: float = 0.995,
             alns_destroy: list[str] | None = None,
             alns_repair: list[str] | None = None,
             vns_neighbourhoods: list[str] | None = None,
             lagrangian_max_iter: int = 8,
             lagrangian_tolerance: float = 1e-2,
             lagrangian_alpha_0: float = 1.0) -> int:
    params = dict(stage=stage, budget_s=budget_s, workers=workers, log=log,
                  n_cycles=n_cycles,
                  ts_budget_per_cycle=ts_budget_per_cycle,
                  sa_T0=sa_T0, sa_alpha=sa_alpha,
                  tabu_size=tabu_size,
                  optimize_rooms=optimize_rooms,
                  rooms_time_limit_s=rooms_time_limit_s,
                  rooms_prefer_home=rooms_prefer_home,
                  alns_T0=alns_T0, alns_alpha=alns_alpha,
                  alns_destroy=alns_destroy,
                  alns_repair=alns_repair,
                  vns_neighbourhoods=vns_neighbourhoods,
                  lagrangian_max_iter=lagrangian_max_iter,
                  lagrangian_tolerance=lagrangian_tolerance,
                  lagrangian_alpha_0=lagrangian_alpha_0)
    _preflight_lock_check()
    run_id = create_run(stage, f"{stage.upper()} on active solution",
                        None, params)

    def target(rid: int):
        import metaheuristics as meta  # type: ignore
        import decomposition_spectral_v2 as dec  # type: ignore
        with SessionLocal() as db:
            locked_snap = _snapshot_locked_lessons(db)
            profs = engine_io.profs_dict_from_db(db)
            active = engine_io.get_active_solution(db)
            if active is None:
                raise RuntimeError("Nessuna soluzione attiva; esegui prima "
                                   "Phase B o importa un pickle.")
            sol = engine_io.lessons_to_solution_dict(db, active.id)
        # Native locks for the meta stage: the locked lesson keys
        # are passed to every algorithm via `locks=` so atomic
        # moves never disturb them.
        locks_set = {(d["teacher_name"], d["class_name"], d["subject"],
                      int(d["day"]), int(d["hour"]))
                     for d in locked_snap
                     if d.get("day") is not None
                        and d.get("hour") is not None} or None
        if locks_set:
            print(f"[{stage}] native lock path: "
                  f"{len(locks_set)} locked keys forbidden to moves")
        if not meta.is_hard_feasible(sol, profs, verbose=False):
            print("[meta] WARNING: la soluzione iniziale viola gli HARD")
        dc_value = _restore_dc_from_solution(sol)
        # Cluster classi per LNS/ILS
        try:
            M, classes_v, _ = dec.build_adjacency(profs)
            labels, _ = dec.spectral_cluster(M, max(2, min(4, len(classes_v) // 5)))
            cc: dict[int, set] = defaultdict(set)
            for i, c in enumerate(classes_v):
                cc[int(labels[i])].add(c)
            classes_clusters = dict(cc)
        except Exception:
            classes_clusters = None
        # Estimate the wallclock budget for the progress ticker. ILS
        # runs n_cycles internally, each consuming ts_budget_per_cycle.
        if stage == "ils":
            budget_estimate = max(budget_s, n_cycles * ts_budget_per_cycle)
        else:
            budget_estimate = budget_s
        update_run(rid, progress=0.05)
        # Telemetry: a top-level collector for the whole stage; the
        # individual algorithm modules are oblivious to it -- we
        # snapshot only the entry / exit objective. A future
        # iteration can plumb the collector deeper (per-iteration
        # samples) without breaking this code path.
        from .utils import telemetry as tel
        with _progress_ticker(rid, budget_estimate, start=0.05,
                                end=0.95), \
              tel.collector(rid, phase=f"stage_{stage}") as _tcol:
            init_v, init_m = meta.compute_soft(sol, profs)
            _tcol.sample(step=0, objective_value=float(init_v),
                          hard_violations_count=0,
                          placed_lessons_count=sum(int(v) for v in
                                                    sol.values()))
            if stage == "lns":
                new_sol, _hist = meta.run_lns(
                    sol, profs, dc_value, budget_s,
                    classes_clusters=classes_clusters,
                    log=log, workers=workers, locks=locks_set,
                )
            elif stage == "sa":
                new_sol = meta.run_sa(
                    sol, profs, dc_value, budget_s,
                    T0=sa_T0, alpha=sa_alpha, log=log,
                    locks=locks_set,
                )
            elif stage == "ts":
                new_sol = meta.run_tabu(
                    sol, profs, dc_value, budget_s,
                    tabu_size=tabu_size, log=log, locks=locks_set,
                )
            elif stage == "ils":
                new_sol = meta.run_ils(
                    sol, profs, dc_value, budget_s,
                    classes_clusters=classes_clusters,
                    ts_budget_per_cycle=ts_budget_per_cycle,
                    n_cycles=n_cycles, log=log, locks=locks_set,
                )
            elif stage == "alns":
                import alns as alns_mod  # type: ignore
                new_sol, _hist = alns_mod.run_alns(
                    sol, profs, dc_value, budget_s,
                    classes_clusters=classes_clusters,
                    log=log, workers=workers,
                    T0=alns_T0, alpha=alns_alpha,
                    enabled_destroy=alns_destroy,
                    enabled_repair=alns_repair,
                    locks=locks_set,
                )
            elif stage == "vns":
                import vns as vns_mod  # type: ignore
                new_sol, _hist = vns_mod.run_vns(
                    sol, profs, dc_value, budget_s,
                    log=log,
                    enabled_neighbourhoods=vns_neighbourhoods,
                    locks=locks_set,
                )
            elif stage == "lagrangian":
                import lagrangian as lag_mod  # type: ignore
                new_sol, _info = lag_mod.run_lagrangian(
                    sol, profs, dc_value,
                    time_budget_s=budget_s,
                    max_iter=lagrangian_max_iter,
                    tolerance=lagrangian_tolerance,
                    alpha_0=lagrangian_alpha_0,
                    classes_clusters=classes_clusters,
                    log=log, locks=locks_set,
                )
            else:
                raise RuntimeError(f"Unknown stage {stage}")

            # Final telemetry sample
            final_v, _ = meta.compute_soft(new_sol, profs)
            _tcol.sample(step=1, objective_value=float(final_v),
                          hard_violations_count=0,
                          placed_lessons_count=sum(int(v) for v in
                                                    new_sol.values()),
                          improvement=float(init_v - final_v))

        v, m = meta.compute_soft(new_sol, profs)
        feasible = meta.is_hard_feasible(new_sol, profs, verbose=False)
        with SessionLocal() as db:
            sid = engine_io.import_solution_into_db(
                db, new_sol,
                name=f"{stage.upper()} run {rid}",
                kind=stage,
                obj_value=float(v),
                metrics={**m, "feasible": feasible},
                make_active=True,
            )
            # Native-lock path: the meta runners honoured the locks
            # via `locks=`; only re-apply classroom_name / cotaught_with.
            n_touched = _apply_locked_classrooms(db, sid, locked_snap)
            if n_touched:
                db.commit()
                print(f"[{stage}] re-applied classroom on "
                      f"{n_touched} locked lessons (native path)")
        rooms_metrics: dict[str, Any] = {}
        if optimize_rooms:
            update_run(rid, progress=0.95)
            try:
                rooms_metrics = _apply_rooms_to_solution(
                    sid, time_limit_s=rooms_time_limit_s,
                    workers=workers, prefer_home=rooms_prefer_home,
                    log_prefix=f"{stage}.rooms", log=False,
                )
            except Exception as e:  # noqa: BLE001
                print(f"[{stage}] rooms step failed: {e}")
                rooms_metrics = {"rooms_error": str(e)}
        update_run(rid, solution_id=sid, obj_value=float(v),
                   metrics={**m, "feasible": feasible, **rooms_metrics},
                   progress=1.0)
        print(f"[{stage}] solution id={sid} obj={v} metrics={m} rooms={rooms_metrics}")

    start_thread(run_id, target)
    return run_id


# ----------------------------------------------------------------------
# Diagnostics / specialised stages (Hall, Column Generation)
# ----------------------------------------------------------------------


def run_hall_check(*, n_samples: int = 256,
                   teacher_max_hours: int = 18) -> dict[str, Any]:
    """Synchronous Hall's theorem pre-check. Returns the diagnostic
    dict directly (no run_id thread): the operation is < 100 ms even
    on superhuge schools so a sync API is fine.

    Kept for back-compat. New code should prefer
    `run_diag_hall_check` which spawns an async run consistent with
    the other diagnostics.
    """
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..",
                                     "engine", "scripts"))
    from diagnostics import hall_check as hc  # type: ignore
    with SessionLocal() as db:
        return hc.hall_check_from_db(
            db, n_samples=n_samples,
            teacher_max_hours=teacher_max_hours,
        )


def run_diag_hall_check(*, n_samples: int = 256,
                         teacher_max_hours: int = 18) -> int:
    """Async Hall pre-check: same algorithm as `run_hall_check` but
    spawned as a run (kind='diag_hall'). Used by the /diagnostics
    tab so the result lands in /runs alongside the other
    diagnostics."""
    sys.path.insert(0, os.path.join(
        os.path.dirname(__file__), "..", "..", "engine",
    ))

    def _go() -> dict:
        from diagnostics import hall_check as hc  # type: ignore
        with SessionLocal() as db:
            return hc.hall_check_from_db(
                db, n_samples=n_samples,
                teacher_max_hours=teacher_max_hours,
            )
    return run_diagnostic_async(
        "diag_hall",
        f"Hall pre-check (N={n_samples})",
        _go,
    )


def run_diagnostic_async(kind: str, label: str,
                          producer: "callable[[], dict]") -> int:
    """Generic helper: spawn a /runs entry whose target() invokes
    `producer()` (a 0-arg function returning a JSON-serializable
    diagnostic result) and stores the result in `metrics`. The
    front-end polls /api/optimize/runs/{id} and, on done, reads
    `metrics` (which `serialize_run` already exposes).

    Used by Monte Carlo / bipartite / correlations / distributions:
    these can take seconds-to-tens-of-seconds, so they are no
    longer surfaced as sync endpoints.
    """
    params = {"kind": kind, "label": label}
    rid = create_run(kind, label, None, params)

    def target(rid_inner: int):
        update_run(rid_inner, progress=0.05)
        result = producer()
        update_run(rid_inner, progress=0.95,
                    metrics=result if isinstance(result, dict)
                            else {"result": result})

    start_thread(rid, target)
    return rid


def run_diag_montecarlo(*, n_samples: int = 100,
                         seed: int = 0) -> int:
    sys.path.insert(0, os.path.join(
        os.path.dirname(__file__), "..", "..", "engine",
    ))

    def _go() -> dict:
        from diagnostics import montecarlo_sensitivity as mc  # type: ignore
        with SessionLocal() as db:
            return mc.run_montecarlo_from_db(
                db, n_samples=n_samples, seed=seed,
            )
    return run_diagnostic_async(
        "diag_montecarlo",
        f"Sensitivity Monte Carlo (N={n_samples})",
        _go,
    )


def run_diag_bipartite(*, mode: str = "classes") -> int:
    sys.path.insert(0, os.path.join(
        os.path.dirname(__file__), "..", "..", "engine",
    ))

    def _go() -> dict:
        from diagnostics import bipartite_analysis as ba  # type: ignore
        with SessionLocal() as db:
            return ba.analyze_from_db(db, mode=mode)
    return run_diagnostic_async(
        "diag_bipartite",
        f"Analisi bipartito ({mode})",
        _go,
    )


def run_diag_correlations(*, models_spec: list[dict] | None = None
                           ) -> int:
    sys.path.insert(0, os.path.join(
        os.path.dirname(__file__), "..", "..", "engine",
    ))

    def _go() -> dict:
        from diagnostics import correlations as co  # type: ignore
        with SessionLocal() as db:
            return co.run_from_db(db, models_spec=models_spec)
    label = "Correlazioni e regressioni"
    if models_spec:
        label += f" ({len(models_spec)} modell{'i' if len(models_spec) != 1 else 'o'} custom)"
    return run_diagnostic_async(
        "diag_correlations",
        label,
        _go,
    )


def run_diag_distributions(*, spec: dict | None = None) -> int:
    sys.path.insert(0, os.path.join(
        os.path.dirname(__file__), "..", "..", "engine",
    ))

    def _go() -> dict:
        from diagnostics import distributions as ds  # type: ignore
        with SessionLocal() as db:
            return ds.run_from_db(db, spec=spec)
    label = "Distribuzioni e goodness-of-fit"
    if spec and spec.get("include"):
        label += f" ({len(spec['include'])} sel)"
    return run_diagnostic_async(
        "diag_distributions",
        label,
        _go,
    )


def _suggest_cg_granularity(n_classes: int) -> str:
    """Heuristic for the 'auto' granularity option.

    < 30 classes  -> 'teacher' (small schools, the catalog is
                     small enough that per-teacher patterns
                     enumerate the search effectively).
    30-80 classes -> 'class' (medium schools, per-class patterns
                     scale better while teacher catalogs explode).
    > 80 classes  -> 'curriculum' (large schools with structured
                     indirizzi: most teachers stay within an
                     indirizzo, the bridge teachers are few).
    The 'day' granularity is rarely the best option for BnP, but
    remains selectable for experimentation.
    """
    if n_classes < 30:
        return "teacher"
    if n_classes <= 80:
        return "class"
    return "curriculum"


def run_column_generation(*, time_budget_s: float = 60.0,
                          patterns_per_teacher: int = 3,
                          granularity: str = "auto",
                          branching_strategy: str = "ryan_foster",
                          max_iterations: int = 5,
                          parallel: bool = True,
                          log: bool = True) -> int:
    """Async Column Generation pass. Behaves like an alternative
    Phase-B: starts from the active assignment (Phase A), produces
    a HARD-feasible weekly schedule via the iterative master LP +
    pattern enrichment + day-by-day completion fallback. Saved as
    a new Solution with kind='cg'.

    The `granularity`, `branching_strategy`, `max_iterations` and
    `parallel` parameters are accepted from the UI. Today the
    only fully-wired path corresponds to granularity='teacher';
    'class', 'day' and 'curriculum' (per-indirizzo) are accepted
    but mapped to 'teacher' with a log warning until the full BnP
    refactor lands. 'auto' is resolved server-side from the
    number of classes in the active school.
    """
    params = dict(time_budget_s=time_budget_s,
                  patterns_per_teacher=patterns_per_teacher,
                  granularity=granularity,
                  branching_strategy=branching_strategy,
                  max_iterations=max_iterations,
                  parallel=parallel,
                  log=log)
    # Resolve 'auto' immediately so the run row records the
    # concrete decision.
    if granularity == "auto":
        with SessionLocal() as db:
            n_cls = db.query(models.SchoolClass).count()
        suggested = _suggest_cg_granularity(n_cls)
        print(f"[cg] granularity='auto' resolved to "
              f"'{suggested}' (n_classes={n_cls})")
        params["granularity_resolved"] = suggested
        granularity = suggested
    if granularity not in (
            "teacher", "class", "day", "curriculum"):
        print(f"[cg] WARNING: granularity={granularity!r} non "
              f"riconosciuta; uso 'teacher'")
        granularity = "teacher"
    if granularity != "teacher":
        print(f"[cg] WARNING: granularity={granularity!r} accetta "
              f"il run ma il sub-CP-SAT corrispondente non e' "
              f"ancora implementato (vedi roadmap in "
              f"docs/optimization_strategies.md). Eseguo la "
              f"variante iterative-diversified per docente.")
    if branching_strategy not in ("variable", "ryan_foster"):
        print(f"[cg] WARNING: branching_strategy={branching_strategy!r} "
              f"non riconosciuta")
    _preflight_lock_check()
    rid = create_run("cg", "Column Generation alternative Phase B",
                      None, params)

    def target(rid_inner: int):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__),
                                          "..", "..", "engine", "scripts"))
        import metaheuristics as meta  # type: ignore
        import column_generation as cg  # type: ignore
        with SessionLocal() as db:
            locked_snap = _snapshot_locked_lessons(db)
            profs = engine_io.profs_dict_from_db(db)
            coteach_groups = engine_io.coteach_groups_for_solver(db)
            active = engine_io.get_active_solution(db)
            if active is None:
                raise RuntimeError("Phase B alternativa via Column "
                                    "Generation richiede una soluzione "
                                    "attiva (Phase A) come baseline.")
            sol = engine_io.lessons_to_solution_dict(db, active.id)
        dc_value = _restore_dc_from_solution(sol)
        # Native locks: pattern generation pre-places them, completion
        # solver gets per-day locks, master LP coverage stays valid.
        cg_locks = {(d["teacher_name"], d["class_name"],
                      d["subject"], int(d["day"]), int(d["hour"]))
                     for d in locked_snap
                     if d.get("day") is not None
                        and d.get("hour") is not None} or None
        cg_locked_by_day = _locked_slots_by_day(locked_snap) or None
        if cg_locks:
            print(f"[cg] native lock path: {len(cg_locks)} locked "
                  f"keys pre-placed in patterns; completion solver "
                  f"receives per-day constraint set.")
        update_run(rid_inner, progress=0.1)
        with _progress_ticker(rid_inner, time_budget_s,
                               start=0.1, end=0.95):
            new_sol, info = cg.run_column_generation(
                profs, dc_value,
                time_budget_s=time_budget_s,
                patterns_per_teacher=patterns_per_teacher,
                max_iterations=max_iterations,
                log=log,
                locks=cg_locks,
                locked_by_day=cg_locked_by_day,
                coteach_groups=coteach_groups or None,
            )
        if new_sol is None or not info.get("feasible_after_assembly"):
            update_run(rid_inner, progress=1.0,
                        metrics={**info, "feasible": False},
                        error="CG skeleton non ha trovato una "
                              "soluzione feasible (vedi warnings)")
            return
        v, m = meta.compute_soft(new_sol, profs)
        with SessionLocal() as db:
            sid = engine_io.import_solution_into_db(
                db, new_sol,
                name=f"CG run {rid_inner}",
                kind="cg",
                obj_value=float(v),
                metrics={**m, **info, "feasible": True},
                make_active=True,
            )
            n_touched = _apply_locked_classrooms(db, sid, locked_snap)
            if n_touched:
                db.commit()
                print(f"[cg] re-applied classroom on "
                      f"{n_touched} locked lessons (native path)")
        update_run(rid_inner, solution_id=sid, obj_value=float(v),
                    metrics={**m, **info, "feasible": True},
                    progress=1.0)
        print(f"[cg] solution id={sid} obj={v}")

    start_thread(rid, target)
    return rid


# ----------------------------------------------------------------------
# Step 8: full pipeline
# ----------------------------------------------------------------------


def run_full_pipeline(profile: str,
                      steps: list[str],
                      time_assign: float,
                      phase_b_kwargs: dict[str, Any],
                      budget_lns: float, budget_sa: float,
                      budget_ts: float, budget_ils: float,
                      workers: int = 8,
                      meta_optimize_rooms: bool = False,
                      meta_rooms_time_limit_s: float = 30.0,
                      meta_rooms_prefer_home: bool = True) -> int:
    """User-defined pipeline.

    `steps` is an ordered list whose entries are taken from
    {"phase_a", "phase_b", "lns", "sa", "ts", "ils", "rooms"}; only
    the listed steps run, in the listed order. Each Phase B / meta
    step honours its own `optimize_rooms` flag (carried inside
    `phase_b_kwargs` for Phase B; via `meta_optimize_rooms` for the
    four meta steps which share one toggle on the frontend)."""
    params = dict(profile=profile, steps=list(steps),
                  time_assign=time_assign,
                  phase_b=phase_b_kwargs,
                  budget_lns=budget_lns, budget_sa=budget_sa,
                  budget_ts=budget_ts, budget_ils=budget_ils,
                  workers=workers,
                  meta_optimize_rooms=meta_optimize_rooms,
                  meta_rooms_time_limit_s=meta_rooms_time_limit_s,
                  meta_rooms_prefer_home=meta_rooms_prefer_home)
    _preflight_lock_check()
    run_id = create_run("full", f"Full pipeline ({profile})", profile, params)

    def target(rid: int):
        import cpsat_v2_assignment as ca  # type: ignore
        import cpsat_v2_timetable as cv2  # type: ignore
        import decomposition_spectral_v2 as dec  # type: ignore
        import metaheuristics as meta  # type: ignore

        # Sanitize the steps list. Unknown keys are silently dropped;
        # an empty list is a no-op (still creates a 'done' run).
        # decomp_* keys are alternatives to plain phase_b: each runs
        # its own scheduler. If multiple decomp_* are ticked plus
        # phase_b, the first in order wins; later occurrences become
        # no-ops with a log warning (we never run two competing
        # schedulers in a row).
        valid = {"hall_check", "phase_a", "phase_b", "cg",
                  "decomp_spectral", "decomp_temporal",
                  "decomp_metis", "decomp_curriculum",
                  "lns", "alns", "sa", "ts", "vns", "ils",
                  "lagrangian", "rooms"}
        seq = [s for s in (steps or []) if s in valid]
        # decomp_spectral is shorthand for "phase_b with
        # use_decomposition=true" -- the existing phase_b handler
        # already does spectral when that flag is set. Substitute
        # in-place so the rest of the dispatcher never sees the
        # alias.
        seq = ["phase_b" if s == "decomp_spectral" else s for s in seq]
        # Make a local copy of phase_b_kwargs under a different name:
        # writing to `phase_b_kwargs` here would shadow the closure
        # variable for the WHOLE function and trigger UnboundLocalError
        # on the read that precedes the assignment (the bug fixed in
        # commit deferred to here).
        pb_kwargs = (dict(phase_b_kwargs)
                     if phase_b_kwargs is not None else None)
        if pb_kwargs is not None and any(s == "phase_b" for s in seq):
            # If the user ticked decomp_spectral (now mapped to
            # phase_b), force use_decomposition=true; otherwise
            # leave the existing flag (already true by default).
            pb_kwargs.setdefault("use_decomposition", True)
        # De-conflict scheduler steps. Keep the first scheduler
        # token; later ones are dropped from the run with a notice.
        scheduler_tokens = ("phase_b", "decomp_temporal",
                             "decomp_metis", "decomp_curriculum")
        seen_scheduler = False
        deconflicted = []
        dropped_schedulers = []
        for s in seq:
            if s in scheduler_tokens:
                if seen_scheduler:
                    dropped_schedulers.append(s)
                    continue
                seen_scheduler = True
            deconflicted.append(s)
        seq = deconflicted
        if dropped_schedulers:
            print(f"[full] WARNING: piu' scheduler ticked nella "
                  f"pipeline; eseguo solo il primo, scarto "
                  f"{dropped_schedulers}")
        n_steps = max(1, len(seq))
        with SessionLocal() as db:
            n_cl = db.query(models.SchoolClass).count()
            n_te = db.query(models.Teacher).count()
        print(f"[full] starting on {n_cl} classes, {n_te} teachers; "
              f"steps={seq}")

        # Mutable pipeline state passed across steps.
        state: dict[str, Any] = {
            "profs": None,           # built lazily after phase_a
            "full_solution": None,   # last produced (p,c,s,d,h)->1 dict
            "dc_value": None,        # day-count cache (filled by phase_b)
            "sid": None,             # latest active solution id
            "obj": None,
            "metrics": {},
            "rooms_metrics": {},
        }

        def _maybe_rooms_for(stage_label: str, *, enabled: bool,
                              tlim: float, prefer_home: bool):
            if not enabled or state["sid"] is None:
                return
            try:
                rm = _apply_rooms_to_solution(
                    state["sid"], time_limit_s=tlim,
                    workers=workers, prefer_home=prefer_home,
                    log_prefix=f"{stage_label}.rooms", log=False,
                )
                state["rooms_metrics"] = {**state["rooms_metrics"], **rm}
            except Exception as e:  # noqa: BLE001
                print(f"[{stage_label}] rooms step failed: {e}")
                state["rooms_metrics"]["rooms_error"] = str(e)

        for i, step in enumerate(seq):
            update_run(rid, progress=i / n_steps, current_step=step)
            if step == "phase_a":
                print("[full] === STEP phase_a: assignment ===")
                with SessionLocal() as db:
                    data = engine_io.school_dict_from_db(db)
                cattedre, _solver, _status = ca.solve_assignment(
                    data, time_limit_s=time_assign,
                    workers=workers, log=False,
                )
                with SessionLocal() as db:
                    engine_io.import_assignments_into_db(db, cattedre)
                    state["profs"] = engine_io.profs_dict_from_db(db)
                continue

            if step == "phase_b":
                print("[full] === STEP phase_b: schedule ===")
                if state["profs"] is None:
                    with SessionLocal() as db:
                        state["profs"] = engine_io.profs_dict_from_db(db)
                profs = state["profs"]
                if not profs:
                    raise RuntimeError(
                        "phase_b: nessuna assegnazione; "
                        "metti 'phase_a' prima nella pipeline."
                    )
                classes, triples, class_profs = cv2.build_indices(profs)
                dc_value = cv2.solve_phase_a(
                    profs, classes, triples, class_profs,
                    time_limit=(pb_kwargs or {}).get("time_a", 60),
                    workers=workers, log=False,
                )
                state["dc_value"] = dc_value
                full_solution: dict = {}
                if ((pb_kwargs or {}).get("use_decomposition", True)
                        and len(classes) >= 8):
                    M, classes_v, _ = dec.build_adjacency(profs)
                    k = (pb_kwargs or {}).get("k", 4)
                    labels, _ = dec.spectral_cluster(M, k)
                    bridges, cl_to_label = dec.find_bridges(
                        profs, classes_v, labels,
                    )
                    classes_per_cluster = defaultdict(set)
                    for c, lbl in cl_to_label.items():
                        classes_per_cluster[lbl].add(c)
                    bridges_set = set(bridges.keys())
                    bridge_solutions: dict[int, dict] = {}
                    a_failed = []
                    for d in DAYS:
                        out, _st = dec.stage_a_bridges(
                            d, profs, bridges_set, triples, dc_value,
                            (pb_kwargs or {}).get("time_bridges", 30), workers,
                        )
                        if out is None:
                            a_failed.append(d)
                        else:
                            bridge_solutions[d] = out
                    cluster_solutions: dict[tuple[int, int], dict] = {}
                    b_failed: dict[int, set] = defaultdict(set)
                    for d in DAYS:
                        if d not in bridge_solutions:
                            continue
                        for k_id in sorted(
                            classes_per_cluster,
                            key=lambda kk: -len(classes_per_cluster[kk])
                        ):
                            out, _st = dec.stage_b_cluster_internals(
                                classes_per_cluster[k_id], d, profs,
                                bridges_set, triples, dc_value,
                                bridge_solutions[d],
                                (pb_kwargs or {}).get("time_cluster", 20),
                                workers,
                            )
                            if out is None:
                                b_failed[d].add(k_id)
                            else:
                                cluster_solutions[(k_id, d)] = out
                    for d in DAYS:
                        if d in bridge_solutions:
                            full_solution.update(bridge_solutions[d])
                        for k_id in classes_per_cluster:
                            if (k_id, d) in cluster_solutions:
                                full_solution.update(
                                    cluster_solutions[(k_id, d)]
                                )
                    for d in sorted(set(b_failed.keys()) | set(a_failed)):
                        succ = {}
                        for k_id in classes_per_cluster:
                            if k_id in b_failed.get(d, set()):
                                continue
                            if (k_id, d) in cluster_solutions:
                                succ.update(cluster_solutions[(k_id, d)])
                        out, _st = dec.stage_c_ricucitura(
                            d, profs, bridges_set, triples, dc_value, succ,
                            (pb_kwargs or {}).get("time_ricucitura", 60),
                            workers,
                        )
                        if out is not None:
                            full_solution = {
                                kk: vv for kk, vv in full_solution.items()
                                if kk[3] != d
                            }
                            full_solution.update(out)
                else:
                    for d in DAYS:
                        out, _st = cv2.solve_phase_b_for_day(
                            d, profs, classes, triples, class_profs,
                            dc_value,
                            time_limit=(pb_kwargs or {}).get("time_mono", 120),
                            workers=workers, log=False,
                        )
                        if out is not None:
                            full_solution.update(out)
                v, m = meta.compute_soft(full_solution, profs)
                feasible = meta.is_hard_feasible(
                    full_solution, profs, verbose=False,
                )
                with SessionLocal() as db:
                    sid = engine_io.import_solution_into_db(
                        db, full_solution,
                        name=f"Full pipeline run {rid} (phase_b)",
                        kind="phase_b",
                        obj_value=float(v),
                        metrics={**m, "feasible": feasible},
                        make_active=True,
                    )
                state.update(full_solution=full_solution, sid=sid,
                             obj=float(v),
                             metrics={**m, "feasible": feasible})
                print(f"[full] phase_b done: obj={v} metrics={m} sid={sid}")
                _maybe_rooms_for(
                    "phase_b",
                    enabled=bool((pb_kwargs or {}).get("optimize_rooms", False)),
                    tlim=float((pb_kwargs or {}).get(
                        "rooms_time_limit_s", 30.0)),
                    prefer_home=bool((pb_kwargs or {}).get(
                        "rooms_prefer_home", True)),
                )
                continue

            # ---- Decomposition steps (alternative schedulers) ----
            # decomp_spectral is normalized to "phase_b" earlier in
            # the dispatcher (the phase_b handler already runs
            # spectral when use_decomposition=true). Only the three
            # genuinely-new methods land here.
            if step in ("decomp_temporal", "decomp_metis",
                        "decomp_curriculum"):
                method = step.replace("decomp_", "")
                print(f"[full] === STEP decomp_{method} ===")
                if state["profs"] is None:
                    with SessionLocal() as db:
                        state["profs"] = engine_io.profs_dict_from_db(db)
                profs = state["profs"]
                if not profs:
                    raise RuntimeError(
                        f"decomp_{method}: nessuna assegnazione; "
                        f"metti 'phase_a' prima nella pipeline."
                    )
                # Lazy import the engine modules
                exp_dir = os.path.join(os.path.dirname(__file__),
                                        "..", "..", "engine", "scripts")
                if exp_dir not in sys.path:
                    sys.path.insert(0, exp_dir)
                pb = pb_kwargs or {}
                t_a = float(pb.get("time_a", 60))
                t_day = float(pb.get("time_day", 30))
                t_bridges = float(pb.get("time_bridges", 30))
                t_cluster = float(pb.get("time_cluster", 30))
                t_ric = float(pb.get("time_ricucitura", 60))
                t_mono = float(pb.get("time_mono", 120))

                if method == "temporal":
                    import decomposition_temporal as dec_t  # type: ignore
                    # Persist profs to a temp pickle so the
                    # ProcessPoolExecutor workers can read it.
                    import tempfile, pickle as _pk
                    ws = _run_workspace(rid)
                    profs_pkl = os.path.join(ws, "profs_decomp.pkl")
                    with open(profs_pkl, "wb") as f:
                        _pk.dump(profs, f)
                    res = dec_t.run_temporal_pipeline(
                        profs_pkl,
                        parallel=True,
                        n_workers=int(pb.get("n_workers") or
                                       min(6, os.cpu_count() or 1)),
                        time_a=t_a, time_day=t_day,
                        day_timeout=t_day * 6,
                        cpsat_workers_per_day=int(
                            pb.get("cpsat_workers_per_day", 2)),
                        enforce_no_holes=bool(
                            pb.get("enforce_no_holes", True)),
                        log_progress=False,
                    )
                    state["full_solution"] = res["full_solution"]
                    state["dc_value"] = res["dc_value"]
                    state["metrics"] = {
                        **state.get("metrics", {}),
                        "decomp_method": "temporal",
                        "decomp_master_s": round(
                            res["timings"]["master"], 1),
                        "decomp_days_total_s": round(
                            res["timings"]["days_total"], 1),
                        "decomp_failed_days": res["failed_days"],
                    }
                elif method in ("metis", "curriculum"):
                    if method == "metis":
                        import decomposition_metis as dec_x  # type: ignore
                        kwargs = dict(
                            k=pb.get("k"),
                            imbalance=float(pb.get("imbalance", 1.05)),
                        )
                        solver_fn = dec_x.solve_with_metis_decomposition
                    else:
                        import decomposition_curriculum as dec_x  # type: ignore
                        # Need the class -> curriculum mapping
                        with SessionLocal() as db:
                            cls_to_curr = {}
                            for c in db.query(models.SchoolClass).all():
                                if c.curriculum_id is not None:
                                    cur = db.query(models.Curriculum).filter_by(
                                        id=c.curriculum_id).first()
                                    cls_to_curr[c.name] = (
                                        cur.name if cur
                                        else "cur_" + str(c.curriculum_id))
                                else:
                                    cls_to_curr[c.name] = "_unknown"
                        auto = dec_x.auto_group_small_curricula(
                            cls_to_curr, min_classes=int(
                                pb.get("min_cluster_size", 3)))
                        kwargs = dict(
                            classroom_to_curriculum=cls_to_curr,
                            manual_groupings=auto,
                        )
                        solver_fn = dec_x.solve_with_curriculum_decomposition
                    res = solver_fn(
                        profs,
                        time_a=t_a, time_bridges=t_bridges,
                        time_per_cluster=t_cluster,
                        time_ricucitura=t_ric, time_mono=t_mono,
                        workers=workers, log=False,
                        **kwargs,
                    )
                    state["full_solution"] = res["full_solution"]
                    state["dc_value"] = res["dc_value"]
                    state["metrics"] = {
                        **state.get("metrics", {}),
                        "decomp_method": method,
                        "decomp_master_s": round(
                            res["timings"]["master"], 1),
                        "decomp_days_total_s": round(
                            res["timings"]["days_total"], 1),
                        "decomp_cluster_sizes": res["cluster_sizes"],
                        "decomp_bridges_count": res["bridges_count"],
                        "decomp_failed_days": res["failed_days"],
                    }
                # Persist the solution from the temporal/metis/
                # curriculum scheduler and continue with the
                # metaheuristics that follow in the pipeline list.
                full_solution = state["full_solution"] or {}
                v, m = meta.compute_soft(full_solution, profs)
                feasible = meta.is_hard_feasible(
                    full_solution, profs, verbose=False)
                with SessionLocal() as db:
                    sid = engine_io.import_solution_into_db(
                        db, full_solution,
                        name=f"Pipeline {rid} decomp_{method}",
                        kind=f"phase_b_{method}",
                        obj_value=float(v),
                        metrics={**m, "feasible": feasible,
                                 **state.get("metrics", {})},
                        make_active=True,
                    )
                state["sid"] = sid
                state["obj"] = float(v)
                print(f"[full] decomp_{method} done: feasible="
                      f"{feasible}, obj={v:.1f}")
                _maybe_rooms_for(
                    f"decomp_{method}",
                    enabled=bool(pb.get("optimize_rooms", False)),
                    tlim=float(pb.get("rooms_time_limit_s", 30.0)),
                    prefer_home=bool(pb.get("rooms_prefer_home", True)),
                )
                continue

            if step == "hall_check":
                print("[full] === STEP hall_check (diagnostic) ===")
                try:
                    sys.path.insert(0, os.path.join(
                        os.path.dirname(__file__), "..", "..", "engine",
                    ))
                    from diagnostics import hall_check as hc  # type: ignore
                    with SessionLocal() as db:
                        report = hc.hall_check_from_db(db)
                except Exception as e:  # noqa: BLE001
                    print(f"[full] hall_check error: {e}")
                    report = {"ok": True, "warnings": [str(e)]}
                if not report.get("ok"):
                    msg = (f"Hall pre-check ha rilevato "
                           f"{len(report.get('violations', []))} "
                           f"violazioni; pipeline interrotta.")
                    update_run(rid, error=msg, progress=1.0,
                                metrics={"hall_violations": report.get(
                                    "violations", []
                                )[:5]})
                    print(f"[full] aborting: {msg}")
                    return
                continue

            if step == "cg":
                print("[full] === STEP cg (Column Generation) ===")
                try:
                    sys.path.insert(0, os.path.join(
                        os.path.dirname(__file__), "..", "..", "engine",
                    ))
                    import column_generation as cgmod  # type: ignore
                    if state["profs"] is None:
                        with SessionLocal() as db:
                            state["profs"] = engine_io.profs_dict_from_db(db)
                    if state["dc_value"] is None and state["full_solution"]:
                        state["dc_value"] = _restore_dc_from_solution(
                            state["full_solution"]
                        )
                    if state["dc_value"] is None:
                        # Fallback: try to read it from a recent solution
                        with SessionLocal() as db:
                            active = engine_io.get_active_solution(db)
                            if active is not None:
                                sol2 = engine_io.lessons_to_solution_dict(
                                    db, active.id
                                )
                                state["full_solution"] = sol2
                                state["dc_value"] = _restore_dc_from_solution(sol2)
                    if state["dc_value"] is None:
                        print("[full] cg: nessuna baseline; skip")
                        continue
                    new_sol, info = cgmod.run_column_generation(
                        state["profs"], state["dc_value"],
                        time_budget_s=60.0, log=True,
                    )
                except Exception as e:  # noqa: BLE001
                    print(f"[full] cg error: {e}")
                    continue
                if new_sol is not None and info.get("feasible_after_assembly"):
                    v, m = meta.compute_soft(new_sol, state["profs"])
                    with SessionLocal() as db:
                        sid = engine_io.import_solution_into_db(
                            db, new_sol,
                            name=f"Full pipeline run {rid} (cg)",
                            kind="cg",
                            obj_value=float(v),
                            metrics={**m, **info, "feasible": True},
                            make_active=True,
                        )
                    state.update(full_solution=new_sol, sid=sid,
                                  obj=float(v),
                                  metrics={**m, "feasible": True})
                continue

            if step in ("lns", "alns", "sa", "ts", "vns", "ils",
                         "lagrangian"):
                print(f"[full] === STEP {step} ===")
                if state["full_solution"] is None or state["profs"] is None:
                    # Try to load from active DB solution
                    with SessionLocal() as db:
                        active = engine_io.get_active_solution(db)
                        if active is None:
                            raise RuntimeError(
                                f"{step}: nessuna soluzione attiva; "
                                "metti 'phase_b' prima nella pipeline."
                            )
                        state["profs"] = engine_io.profs_dict_from_db(db)
                        state["full_solution"] = (
                            engine_io.lessons_to_solution_dict(db, active.id)
                        )
                        state["sid"] = active.id
                profs = state["profs"]
                sol = state["full_solution"]
                if state["dc_value"] is None:
                    state["dc_value"] = _restore_dc_from_solution(sol)
                dc_value = state["dc_value"]
                # Cluster for LNS/ILS (cheap, recomputed each call)
                try:
                    M, classes_v, _ = dec.build_adjacency(profs)
                    labels, _ = dec.spectral_cluster(
                        M, max(2, min(4, len(classes_v) // 5)),
                    )
                    cc = defaultdict(set)
                    for j, c in enumerate(classes_v):
                        cc[int(labels[j])].add(c)
                    classes_clusters = dict(cc)
                except Exception:
                    classes_clusters = None

                if step == "lns":
                    new_sol, _hist = meta.run_lns(
                        sol, profs, dc_value, budget_lns,
                        classes_clusters=classes_clusters,
                        log=True, workers=workers,
                    )
                elif step == "alns":
                    sys.path.insert(0, os.path.join(
                        os.path.dirname(__file__), "..", "..", "engine",
                    ))
                    import alns as alns_mod  # type: ignore
                    new_sol, _hist = alns_mod.run_alns(
                        sol, profs, dc_value, budget_lns,
                        classes_clusters=classes_clusters,
                        log=True, workers=workers,
                    )
                elif step == "sa":
                    new_sol = meta.run_sa(
                        sol, profs, dc_value, budget_sa, log=True,
                    )
                elif step == "ts":
                    new_sol = meta.run_tabu(
                        sol, profs, dc_value, budget_ts, log=True,
                    )
                elif step == "vns":
                    sys.path.insert(0, os.path.join(
                        os.path.dirname(__file__), "..", "..", "engine",
                    ))
                    import vns as vns_mod  # type: ignore
                    new_sol, _hist = vns_mod.run_vns(
                        sol, profs, dc_value, budget_ts, log=True,
                    )
                elif step == "lagrangian":
                    sys.path.insert(0, os.path.join(
                        os.path.dirname(__file__), "..", "..", "engine",
                    ))
                    import lagrangian as lag_mod  # type: ignore
                    new_sol, _info = lag_mod.run_lagrangian(
                        sol, profs, dc_value,
                        time_budget_s=budget_lns,
                        classes_clusters=classes_clusters,
                        log=True,
                    )
                else:  # "ils"
                    new_sol = meta.run_ils(
                        sol, profs, dc_value, budget_ils,
                        classes_clusters=classes_clusters, log=True,
                    )
                v, m = meta.compute_soft(new_sol, profs)
                feasible = meta.is_hard_feasible(
                    new_sol, profs, verbose=False,
                )
                with SessionLocal() as db:
                    sid = engine_io.import_solution_into_db(
                        db, new_sol,
                        name=f"Full pipeline run {rid} ({step})",
                        kind=step,
                        obj_value=float(v),
                        metrics={**m, "feasible": feasible},
                        make_active=True,
                    )
                state.update(full_solution=new_sol, sid=sid,
                             obj=float(v),
                             metrics={**m, "feasible": feasible})
                print(f"[full] {step} done: obj={v} sid={sid}")
                _maybe_rooms_for(
                    step,
                    enabled=meta_optimize_rooms,
                    tlim=meta_rooms_time_limit_s,
                    prefer_home=meta_rooms_prefer_home,
                )
                continue

            if step == "rooms":
                print("[full] === STEP rooms (standalone) ===")
                if state["sid"] is None:
                    with SessionLocal() as db:
                        active = engine_io.get_active_solution(db)
                        if active is None:
                            raise RuntimeError(
                                "rooms: nessuna soluzione attiva."
                            )
                        state["sid"] = active.id
                _maybe_rooms_for(
                    "full",
                    enabled=True,
                    tlim=meta_rooms_time_limit_s,
                    prefer_home=meta_rooms_prefer_home,
                )
                continue

        update_run(rid, solution_id=state["sid"], obj_value=state["obj"],
                   metrics={**state["metrics"], **state["rooms_metrics"]},
                   progress=1.0, current_step=None)
        print(f"[full] DONE id={state['sid']} obj={state['obj']} "
              f"metrics={state['metrics']} rooms={state['rooms_metrics']}")

    start_thread(run_id, target)
    return run_id


# ----------------------------------------------------------------------
# Drag & drop validation: HARD-only check
# ----------------------------------------------------------------------


# ----------------------------------------------------------------------
# Lock honoring and event placement
# ----------------------------------------------------------------------


@contextlib.contextmanager
def _progress_ticker(rid: int, budget_s: float, *,
                      start: float = 0.05, end: float = 0.95,
                      tick_every: float = 1.5):
    """Context manager that runs a daemon thread bumping the run's
    `progress` field every `tick_every` seconds based on wallclock
    time vs `budget_s`. Used by run_meta etc. where the underlying
    solver is a single blocking call with no internal progress hook.

    Usage:
        with _progress_ticker(rid, budget_s):
            new_sol = meta.run_lns(...)
    """
    stop_evt = threading.Event()
    t0 = time.time()
    def _bump():
        while not stop_evt.is_set():
            try:
                elapsed = time.time() - t0
                pct = min(end, start + (elapsed / max(budget_s, 1.0))
                                          * (end - start))
                update_run(rid, progress=pct)
            except Exception:
                pass
            if stop_evt.wait(tick_every):
                break
    bump_thread = threading.Thread(target=_bump, daemon=True)
    bump_thread.start()
    try:
        yield
    finally:
        stop_evt.set()
        bump_thread.join(timeout=2.0)


def _locked_day_count_from_snapshot(snapshot: list[dict]
                                     ) -> dict[tuple, int]:
    """Aggregate a Lesson-level snapshot into a Phase A floor:
    {(teacher_name, class_name, subject, day) -> n_locked_in_that_day}.
    Used by the native-lock CP-SAT path: each entry becomes a
    `model.Add(day_count[k] >= n)` constraint."""
    out: dict[tuple, int] = {}
    for snap in snapshot:
        if snap.get("day") is None or snap.get("hour") is None:
            continue
        k = (snap["teacher_name"], snap["class_name"],
             snap["subject"], int(snap["day"]))
        out[k] = out.get(k, 0) + 1
    return out


def _locked_slots_by_day(snapshot: list[dict]
                          ) -> dict[int, list[tuple]]:
    """Group a Lesson-level snapshot by day into the
    `(prof, class, subject, hour)` tuples consumed by
    solve_phase_b_for_day's `locked_slots_for_day` parameter."""
    out: dict[int, list[tuple]] = {}
    for snap in snapshot:
        if snap.get("day") is None or snap.get("hour") is None:
            continue
        d = int(snap["day"])
        out.setdefault(d, []).append((
            snap["teacher_name"], snap["class_name"],
            snap["subject"], int(snap["hour"]),
        ))
    return out


def _apply_locked_classrooms(db: Session, solution_id: int,
                              snapshot: list[dict]) -> int:
    """After a NATIVE-lock solve, the day/hour of each locked Lesson
    is already correct (the solver enforced it). This helper just
    re-applies the locked classroom_name and cotaught_with attributes
    to the matching Lesson rows. No deletion, no relocation -- the
    solver did the heavy lifting.
    """
    if not snapshot:
        return 0
    n_touched = 0
    for snap in snapshot:
        if snap.get("day") is None or snap.get("hour") is None:
            continue
        l = db.query(models.Lesson).filter(
            models.Lesson.solution_id == solution_id,
            models.Lesson.teacher_name == snap["teacher_name"],
            models.Lesson.class_name == snap["class_name"],
            models.Lesson.subject == snap["subject"],
            models.Lesson.day == int(snap["day"]),
            models.Lesson.hour == int(snap["hour"]),
        ).first()
        if l is None:
            # Should not happen with native locks; if it does, the
            # solver returned INFEASIBLE earlier or an upstream error
            # dropped the Lesson. Skip silently and let the caller
            # decide based on the run's status.
            continue
        if snap.get("classroom_name"):
            l.classroom_name = snap["classroom_name"]
        if snap.get("cotaught_with"):
            l.cotaught_with = snap["cotaught_with"]
        n_touched += 1
    return n_touched


# Engine HARD constants mirrored here so the pre-flight check
# doesn't need to import the CP-SAT module just to read them.
_LOCK_MAX_PER_DAY_TRIPLE = 2     # max ore stessa cattedra/giorno
_LOCK_MAX_PER_DAY_PROF_CL = 3    # max ore (prof, class)/giorno
_LOCK_MAX_PROF_HOURS_PER_DAY = 5 # max ore prof/giorno


def validate_locks_vs_constraints(snapshot: list[dict]) -> list[str]:
    """Pre-flight check: detect locks that already violate the
    structural HARD constraints of the engine, BEFORE spending a
    minute on the solver only to get an INFEASIBLE message.

    Returns a list of human-readable violation strings; empty list
    means the lock set is consistent with the HARD constraints we
    can check at this layer.

    Catches:
      - >MAX_PER_DAY_TRIPLE locks for the same cattedra in one day
      - >MAX_PER_DAY_PROF_CL locks for the same (prof, class) in one
        day
      - >MAX_PROF_HOURS_PER_DAY locks for the same prof in one day
      - two locks at the same (class, day, hour) but with different
        teachers (a class cannot be in two lessons at once)
      - two locks at the same (prof, day, hour) (a prof cannot be
        in two classes at once)
      - two locks with the same classroom_name at the same
        (day, hour) but different (class, subject), unless the
        classroom is multi_class -- but we don't have the
        Classroom row here so we just flag it; the engine layer
        will resolve / accept multi_class as appropriate.

    Does NOT catch:
      - free_day collisions (the engine free_day is a 3-way choice;
        the solver will pick a different candidate when one is
        locked)
      - hard_motorie_pairs / hard_dual_math etc. -- these are
        per-class flags that interact with the structure of
        day_count and are non-trivial to reproduce here. The
        engine returns a clear INFEASIBLE message when violated.
    """
    if not snapshot:
        return []
    violations: list[str] = []

    by_triple_day: dict[tuple, int] = {}
    by_profcl_day: dict[tuple, int] = {}
    by_prof_day: dict[tuple, int] = {}
    by_class_slot: dict[tuple, list[tuple]] = {}
    by_prof_slot: dict[tuple, list[tuple]] = {}
    by_room_slot: dict[tuple, list[tuple]] = {}

    for snap in snapshot:
        if snap.get("day") is None or snap.get("hour") is None:
            continue
        t = snap["teacher_name"]
        c = snap["class_name"]
        s = snap["subject"]
        d = int(snap["day"])
        h = int(snap["hour"])
        room = snap.get("classroom_name")

        by_triple_day[(t, c, s, d)] = by_triple_day.get((t, c, s, d), 0) + 1
        by_profcl_day[(t, c, d)] = by_profcl_day.get((t, c, d), 0) + 1
        by_prof_day[(t, d)] = by_prof_day.get((t, d), 0) + 1
        by_class_slot.setdefault((c, d, h), []).append((t, s))
        by_prof_slot.setdefault((t, d, h), []).append((c, s))
        if room:
            by_room_slot.setdefault((room, d, h), []).append((c, s, t))

    for (t, c, s, d), n in by_triple_day.items():
        if n > _LOCK_MAX_PER_DAY_TRIPLE:
            violations.append(
                f"cattedra {t}/{c}/{s} ha {n} lock in giorno {d} "
                f"ma il massimo per cattedra/giorno e' "
                f"{_LOCK_MAX_PER_DAY_TRIPLE}"
            )
    for (t, c, d), n in by_profcl_day.items():
        if n > _LOCK_MAX_PER_DAY_PROF_CL:
            violations.append(
                f"docente {t} in classe {c} ha {n} lock in giorno {d} "
                f"ma il massimo per (docente,classe)/giorno e' "
                f"{_LOCK_MAX_PER_DAY_PROF_CL}"
            )
    for (t, d), n in by_prof_day.items():
        if n > _LOCK_MAX_PROF_HOURS_PER_DAY:
            violations.append(
                f"docente {t} ha {n} lock in giorno {d} "
                f"ma il massimo per docente/giorno e' "
                f"{_LOCK_MAX_PROF_HOURS_PER_DAY}"
            )
    for (c, d, h), entries in by_class_slot.items():
        teachers = {e[0] for e in entries}
        if len(teachers) > 1:
            violations.append(
                f"classe {c} ha {len(entries)} lock simultanei in "
                f"giorno {d} ora {h} ({sorted(teachers)}): la classe "
                f"non puo' stare in piu' lezioni contemporaneamente"
            )
    for (t, d, h), entries in by_prof_slot.items():
        classes = {e[0] for e in entries}
        if len(classes) > 1:
            violations.append(
                f"docente {t} ha {len(entries)} lock simultanei in "
                f"giorno {d} ora {h} ({sorted(classes)}): il docente "
                f"non puo' stare in piu' classi contemporaneamente"
            )
    for (room, d, h), entries in by_room_slot.items():
        if len(entries) > 1:
            classes = {e[0] for e in entries}
            if len(classes) > 1:
                violations.append(
                    f"aula {room} ha {len(entries)} lock simultanei in "
                    f"giorno {d} ora {h} ({sorted(classes)}): se l'aula "
                    f"non e' multi_class l'engine restituira' "
                    f"INFEASIBLE")
    return violations


def _snapshot_and_validate_locks(db: Session) -> list[dict]:
    """Read the locked-Lesson snapshot AND run the pre-flight
    validation. If the lock set violates a structural HARD,
    raise RuntimeError with a multi-line message listing every
    violation, BEFORE the solver thread is spawned. The router's
    HTTPException handler maps RuntimeError to a 400 with code
    `engine_error`.
    """
    snap = _snapshot_locked_lessons(db)
    if snap:
        violations = validate_locks_vs_constraints(snap)
        if violations:
            raise RuntimeError(
                "Lock incompatibili con i vincoli HARD attuali: "
                + "; ".join(violations)
                + ". Sblocca le lezioni in conflitto o rimuovi i "
                  "vincoli incompatibili e riprova."
            )
    return snap


def _preflight_lock_check() -> None:
    """Sync wrapper for the pre-flight check. Called by every
    run_xxx entry-point BEFORE create_run + start_thread, so a lock
    violation surfaces as a 400 on the synchronous POST instead of
    silently failing the run later. Opens its own session: cheap
    and short-lived.
    """
    with SessionLocal() as db:
        snap = _snapshot_locked_lessons(db)
    if not snap:
        return
    violations = validate_locks_vs_constraints(snap)
    if violations:
        raise RuntimeError(
            "Lock incompatibili con i vincoli HARD attuali: "
            + "; ".join(violations)
            + ". Sblocca le lezioni in conflitto o rimuovi i "
              "vincoli incompatibili e riprova."
        )


def _snapshot_locked_lessons(db: Session) -> list[dict]:
    """Capture every Lesson belonging to a LOCKED Assignment in the
    active solution, so we can restore them after a Phase B / meta run
    that doesn't natively know about Assignment.locked. Returns a list
    of dicts ready to be re-inserted into the new solution.
    """
    active = engine_io.get_active_solution(db)
    if active is None:
        return []
    locked_keys: set[tuple[str, str, str]] = set()
    teachers = {t.id: t for t in db.query(models.Teacher).all()}
    classes = {c.id: c for c in db.query(models.SchoolClass).all()}
    for a in db.query(models.Assignment).filter(
        models.Assignment.locked == True  # noqa: E712
    ).all():
        t = teachers.get(a.teacher_id)
        c = classes.get(a.class_id)
        if t is None or c is None:
            continue
        locked_keys.add((t.name, c.name, a.subject))
    if not locked_keys:
        return []
    out: list[dict] = []
    for l in db.query(models.Lesson).filter(
        models.Lesson.solution_id == active.id
    ).all():
        if (l.teacher_name, l.class_name, l.subject) in locked_keys:
            out.append({
                "teacher_name": l.teacher_name,
                "class_name": l.class_name,
                "subject": l.subject,
                "day": l.day, "hour": l.hour,
                "classroom_name": l.classroom_name,
                "cotaught_with": l.cotaught_with,
            })
    return out


def run_place_event(event_ids: list[int], lock_mode: str = "all_others_locked",
                    *, prefer_pref: bool = False,
                    label: str | None = None) -> int:
    """Place the lessons of a set of cattedre into the active solution
    using a HARD-feasible greedy placer. Used by the per-row "Piazza"
    button in /monitor.

    `lock_mode`:
        all_others_locked            every other lesson is treated as
                                     fixed; we just fit the missing
                                     hours into free slots.
        same_class_or_teacher_movable  lessons of the target events'
                                     classes or teachers can be evicted;
                                     everything else is fixed.
        all_others_movable           no fixed lessons; the placer can
                                     evict anything (used as a fallback
                                     for tightly-packed schedules).

    Implementation is greedy + HARD-only: for each missing hour we
    pick the first slot that doesn't violate teacher/class/classroom
    HARD-availability AND doesn't collide with a "frozen" lesson
    according to lock_mode. Conflicts with movable lessons cause those
    lessons to be deleted (the user can "Piazza" them again later).

    Caveats: this is NOT a SOFT-optimal placer; for that the user
    should run the full Phase B + meta pipeline. The greedy approach
    is fast (sub-second on small/medium schools) and surfaces
    placement failures clearly when no HARD-feasible slot exists.
    """
    params = dict(event_ids=list(event_ids), lock_mode=lock_mode,
                  prefer_pref=prefer_pref)
    run_id = create_run(
        "place_event",
        label or f"Piazza eventi ({len(event_ids)})",
        None, params,
    )

    def target(rid: int):
        with SessionLocal() as db:
            active = engine_io.get_active_solution(db)
            if active is None:
                raise RuntimeError(
                    "Nessuna soluzione attiva: lancia prima Phase B."
                )
            # Resolve target Assignments
            targets = []
            for aid in event_ids:
                a = db.get(models.Assignment, int(aid))
                if a is None:
                    continue
                t = db.get(models.Teacher, a.teacher_id)
                c = db.get(models.SchoolClass, a.class_id)
                if t is None or c is None:
                    continue
                targets.append((a, t, c))
            if not targets:
                raise RuntimeError("Nessun evento target valido.")
            print(f"[piazza] {len(targets)} eventi target, lock_mode={lock_mode}")

            # HARD-availability sets (teacher / class / room cells)
            av = _availability_constraints(db)

            # Existing lessons in the active solution. Categorize:
            # frozen (cannot be evicted) vs movable (can be evicted).
            target_keys = {(t.name, c.name, a.subject) for (a, t, c) in targets}
            target_teachers = {t.name for (_, t, _) in targets}
            target_classes  = {c.name for (_, _, c) in targets}
            frozen_owner: set[tuple[str, int, int]] = set()
            frozen_class: set[tuple[str, int, int]] = set()
            frozen_room:  set[tuple[str, int, int]] = set()
            movable: list[models.Lesson] = []
            for l in db.query(models.Lesson).filter(
                models.Lesson.solution_id == active.id
            ).all():
                if (l.teacher_name, l.class_name, l.subject) in target_keys:
                    # The target's own lessons are always re-placed
                    movable.append(l)
                    continue
                touches_target = (
                    l.teacher_name in target_teachers
                    or l.class_name in target_classes
                )
                if lock_mode == "all_others_movable":
                    movable.append(l)
                    continue
                if (lock_mode == "same_class_or_teacher_movable"
                        and touches_target):
                    movable.append(l)
                    continue
                # frozen
                frozen_owner.add((l.teacher_name, l.day, l.hour))
                frozen_class.add((l.class_name, l.day, l.hour))
                if l.classroom_name:
                    frozen_room.add((l.classroom_name, l.day, l.hour))
            print(f"[piazza] frozen: {len(frozen_owner)} owner, "
                  f"{len(frozen_class)} class, {len(frozen_room)} room")
            print(f"[piazza] movable: {len(movable)} lessons "
                  f"(will be evicted on conflict)")

            # Wipe target events' existing lessons (we re-place them all)
            n_wiped = 0
            for l in list(movable):
                if (l.teacher_name, l.class_name, l.subject) in target_keys:
                    db.delete(l); n_wiped += 1
            db.flush()
            print(f"[piazza] wiped {n_wiped} existing lessons of target events")

            # Track temporary occupancy (frozen + already placed in this run)
            placed_owner = set(frozen_owner)
            placed_class = set(frozen_class)
            placed_room  = set(frozen_room)

            n_placed = 0
            n_unplaced = 0
            # Sequence target hours (one entry per missing hour)
            for (a, t, c) in targets:
                hours_to_place = int(a.hours)
                placements = []
                for d in DAYS:
                    if len(placements) >= hours_to_place:
                        break
                    for h in HOURS:
                        if len(placements) >= hours_to_place:
                            break
                        # HARD-availability checks
                        if (t.name, d, h) in av["teacher_hard"]:
                            continue
                        if (c.name, d, h) in av["class_hard"]:
                            continue
                        # Frozen + already-placed-in-this-run conflicts
                        if (t.name, d, h) in placed_owner:
                            continue
                        if (c.name, d, h) in placed_class:
                            continue
                        # OK: take this slot
                        placements.append((d, h))
                        placed_owner.add((t.name, d, h))
                        placed_class.add((c.name, d, h))
                # Insert lessons
                for (d, h) in placements:
                    db.add(models.Lesson(
                        solution_id=active.id,
                        teacher_name=t.name, class_name=c.name,
                        subject=a.subject,
                        day=int(d), hour=int(h),
                        classroom_name=None,
                    ))
                    n_placed += 1
                missing = hours_to_place - len(placements)
                if missing > 0:
                    n_unplaced += missing
                    print(f"[piazza] WARN {t.name}/{c.name}/{a.subject}: "
                          f"piazzate {len(placements)}/{hours_to_place} ore, "
                          f"{missing} non collocabili (HARD-infeasible).")
            db.commit()
            update_run(rid, progress=1.0, metrics={
                "n_targets": len(targets),
                "n_placed": n_placed,
                "n_unplaced": n_unplaced,
                "lock_mode": lock_mode,
            })
            print(f"[piazza] DONE: {n_placed} piazzate, {n_unplaced} non piazzate")

    start_thread(run_id, target)
    return run_id


def _apply_rooms_to_solution(sid: int, *, time_limit_s: float,
                             workers: int, prefer_home: bool,
                             log_prefix: str = "rooms",
                             log: bool = False) -> dict[str, Any]:
    """Run the classroom-assignment step on solution `sid` synchronously
    (inside another run's worker thread). Returns a metrics dict that
    can be merged into the parent run's metrics_json.

    Used by:
      - run_phase_b / run_meta when their `optimize_rooms` toggle is on
      - run_full_pipeline when one of its steps in the pipeline list
        carries the per-step rooms toggle
      - the standalone "rooms" pipeline step
    """
    from classroom_assignment import (  # type: ignore
        solve_classroom_assignment, greedy_classroom_assignment,
    )
    with SessionLocal() as db:
        lessons = engine_io.lessons_for_classroom_step(db, sid)
        rooms = engine_io.classrooms_dicts_from_db(db)
        # Native lock for the classroom step: read the snapshot of
        # locked Lessons that have a classroom_name and force the
        # solver to assign that room to that lesson.
        locked_snap = _snapshot_locked_lessons(db)
    locked_classrooms = [
        (d["class_name"], d["subject"], int(d["day"]), int(d["hour"]),
         d["classroom_name"])
        for d in locked_snap
        if d.get("day") is not None and d.get("hour") is not None
        and d.get("classroom_name")
    ]
    if not rooms:
        print(f"[{log_prefix}] no rooms in DB; skipping room step")
        return {"rooms_skipped": "no_rooms"}
    if not lessons:
        print(f"[{log_prefix}] solution has no lessons; skipping room step")
        return {"rooms_skipped": "no_lessons"}
    print(f"[{log_prefix}] {len(lessons)} lessons, {len(rooms)} rooms"
          + (f", {len(locked_classrooms)} classroom locks"
             if locked_classrooms else ""))
    result, status = solve_classroom_assignment(
        lessons, rooms, time_limit_s=time_limit_s,
        workers=workers, log=log,
        locked_classrooms=locked_classrooms or None,
    )
    if result is None:
        print(f"[{log_prefix}] CP-SAT infeasible ({status}); fallback greedy")
        # Greedy is now lock-aware (FU-2): forward the same
        # locked_classrooms list so the fallback honours every lock.
        result = greedy_classroom_assignment(
            lessons, rooms, prefer_home=prefer_home,
            locked_classrooms=locked_classrooms or None,
        )
    with SessionLocal() as db:
        n_rooms = engine_io.apply_room_mapping(db, sid, result)
    print(f"[{log_prefix}] {n_rooms}/{len(lessons)} lessons got a room")
    return {"rooms_assigned": n_rooms, "rooms_total_lessons": len(lessons)}


def run_classroom_assignment(time_limit_s: float, workers: int, log: bool,
                             prefer_home: bool = True) -> int:
    """Step 'Assegna aule' — uses engine/classroom_assignment.py."""
    params = dict(time_limit_s=time_limit_s, workers=workers, log=log,
                  prefer_home=prefer_home)
    run_id = create_run("rooms", "Assegnazione aule", None, params)

    def target(rid: int):
        from classroom_assignment import (  # type: ignore
            solve_classroom_assignment, greedy_classroom_assignment,
        )
        with SessionLocal() as db:
            active = engine_io.get_active_solution(db)
            if active is None:
                raise RuntimeError(
                    "Nessuna soluzione attiva: esegui prima Phase B."
                )
            lessons = engine_io.lessons_for_classroom_step(db, active.id)
            rooms = engine_io.classrooms_dicts_from_db(db)
            locked_snap = _snapshot_locked_lessons(db)
        locked_classrooms = [
            (d["class_name"], d["subject"], int(d["day"]), int(d["hour"]),
             d["classroom_name"])
            for d in locked_snap
            if d.get("day") is not None and d.get("hour") is not None
            and d.get("classroom_name")
        ]
        if not rooms:
            raise RuntimeError(
                "Nessuna aula nel DB: importa o genera la lista aule prima."
            )
        if not lessons:
            raise RuntimeError("Soluzione attiva senza lezioni.")
        print(f"[rooms] {len(lessons)} lezioni, {len(rooms)} aule"
              + (f", {len(locked_classrooms)} aule lockate"
                 if locked_classrooms else ""))
        result, status = solve_classroom_assignment(
            lessons, rooms, time_limit_s=time_limit_s,
            workers=workers, log=log,
            locked_classrooms=locked_classrooms or None,
        )
        if result is None:
            print(f"[rooms] CP-SAT infeasible ({status}); fallback greedy")
            result = greedy_classroom_assignment(
                lessons, rooms, prefer_home=prefer_home,
                locked_classrooms=locked_classrooms or None,
            )
        with SessionLocal() as db:
            n = engine_io.apply_room_mapping(db, active.id, result)
        update_run(rid, progress=1.0, metrics={
            "rooms_assigned": n, "lessons": len(lessons),
        })
        print(f"[rooms] {n}/{len(lessons)} lezioni hanno un'aula")

    start_thread(run_id, target)
    return run_id


def auto_generate_classrooms(overrides: dict[str, int | None] | None = None
                             ) -> dict[str, Any]:
    """Synchronous helper: build the classrooms via the recipe and persist.

    The recipe scales with the number of classes currently in the DB.
    `overrides` is a partial dict {kind: count}; any kind not present
    falls back to the proportional default returned by
    `compute_default_counts`. Returns a summary dict including the
    counts actually used."""
    from . import mock_classrooms
    out = {"created": 0, "updated": 0, "counts_used": {}, "n_classes": 0}
    with SessionLocal() as db:
        class_names = [c.name for c in db.query(models.SchoolClass).all()]
        if not class_names:
            raise RuntimeError(
                "Nessuna classe nel DB: importa o genera la scuola prima."
            )
        n_classes = len(class_names)
        defaults = mock_classrooms.compute_default_counts(n_classes)
        counts_used = dict(defaults)
        if overrides:
            for k, v in overrides.items():
                if v is not None and k in counts_used:
                    counts_used[k] = max(0, int(v))
        out["n_classes"] = n_classes
        out["counts_used"] = counts_used
        recipe = mock_classrooms.build_recipe_for_classes(
            class_names, n_classes=n_classes, overrides=counts_used
        )
        # Wipe existing classrooms (cascades remove tag assignments
        # via the ClassroomTagAssignment FK).
        db.query(models.ClassroomSubjectPreference).delete()
        db.query(models.ClassroomClassPreference).delete()
        db.query(models.ClassroomUnavailability).delete()
        db.query(models.ClassroomTagAssignment).delete()
        db.query(models.Classroom).delete()
        db.commit()
        # Cache to avoid re-querying for repeated tag names.
        tag_id_by_name: dict[str, int] = {
            t.name: t.id
            for t in db.query(models.ClassroomTag).all()
        }
        for r in recipe:
            cr = models.Classroom(
                name=r["name"], kind=r["kind"],
                capacity=r["capacity"],
                multi_class=r["multi_class"],
                multi_class_max=r["multi_class_max"],
                multi_class_pref=r["multi_class_pref"],
            )
            db.add(cr)
            db.flush()
            for subj in r.get("subject_required", []):
                db.add(models.ClassroomSubjectPreference(
                    classroom_id=cr.id, subject=subj,
                    weight=10.0, required=True,
                ))
            home = r.get("is_home_for_class")
            if home:
                db.add(models.ClassroomClassPreference(
                    classroom_id=cr.id, class_name=home,
                    weight=20.0, is_home=True,
                ))
            # Auto-tag based on the recipe (kind + curriculum hints +
            # common Italian subjects). The mock-school workflow ends
            # up with a fully-tagged set out of the box.
            for tname in r.get("tags", []) or []:
                tname_l = (tname or "").strip().lower()
                if not tname_l:
                    continue
                tid = tag_id_by_name.get(tname_l)
                if tid is None:
                    new_tag = models.ClassroomTag(name=tname_l)
                    db.add(new_tag)
                    db.flush()
                    tid = new_tag.id
                    tag_id_by_name[tname_l] = tid
                db.add(models.ClassroomTagAssignment(
                    classroom_id=cr.id, tag_id=tid,
                ))
            out["created"] += 1
        db.commit()
    return out


DAY_TO_INT = {
    "Monday": 1, "Tuesday": 2, "Wednesday": 3,
    "Thursday": 4, "Friday": 5, "Saturday": 6,
    "Lunedi": 1, "Martedi": 2, "Mercoledi": 3,
    "Giovedi": 4, "Venerdi": 5, "Sabato": 6,
}


def _logical_constraints(db: Session) -> dict[str, list[dict]]:
    """Materialize logical disjunctive rules grouped by entity_type+name.
    Returns a dict like:
      {
        'teacher_rules': {teacher_name: [ {clauses, is_hard, soft_penalty}, ...]},
        'class_rules':   {class_name:   [...]},
        'room_rules':    {room_name:    [...]},
      }
    """
    import json as _json
    teachers = {t.id: t.name for t in db.query(models.Teacher).all()}
    classes = {c.id: c.name for c in db.query(models.SchoolClass).all()}
    rooms = {r.id: r.name for r in db.query(models.Classroom).all()}
    out = {"teacher_rules": {}, "class_rules": {}, "room_rules": {}}
    for r in db.query(models.LogicalUnavailability).all():
        try:
            clauses = _json.loads(r.parsed_dnf_json or "[]")
        except Exception:
            clauses = []
        rec = {"clauses": clauses, "is_hard": r.is_hard,
               "soft_penalty": r.soft_penalty}
        if r.entity_type == "teacher":
            n = teachers.get(r.entity_id)
            if n: out["teacher_rules"].setdefault(n, []).append(rec)
        elif r.entity_type == "class":
            n = classes.get(r.entity_id)
            if n: out["class_rules"].setdefault(n, []).append(rec)
        elif r.entity_type == "classroom":
            n = rooms.get(r.entity_id)
            if n: out["room_rules"].setdefault(n, []).append(rec)
    return out


def _logical_violation_summary(rules: dict, name: str,
                               unavail_set: set[tuple[int, int]]
                               ) -> tuple[bool, int]:
    """For the rules attached to `name`, returns (any_hard_violated,
    total_soft_penalty).

    Penalty semantics by rule kind:
      * HARD            (is_hard=True)      : violated -> hard flag
      * SOFT            (is_hard=False, p>=0): violated -> +p
      * PREFERRED       (is_hard=False, p<0) : satisfied -> +p (= bonus)

    Both SOFT and PREFERRED contributions are summed in `soft_pen` so the
    same objective accumulator handles both.
    """
    from .utils.logic_parser import evaluate_against_unavailable
    hard_violated = False
    soft_pen = 0
    for rule in rules.get(name, []):
        ok = evaluate_against_unavailable(rule["clauses"], unavail_set)
        pen = int(rule["soft_penalty"])
        if not ok:
            if rule["is_hard"]:
                hard_violated = True
            elif pen >= 0:
                # SOFT constraint, pay penalty
                soft_pen += pen
            # PREFERRED + violated -> no contribution
        else:
            # satisfied
            if not rule["is_hard"] and pen < 0:
                # PREFERRED + satisfied -> apply bonus (negative)
                soft_pen += pen
    return hard_violated, soft_pen


def _logical_check_for_solution(db: Session, sol: dict
                                ) -> tuple[bool, int, str | None]:
    """Run all logical rules over the given solution. Returns
    (all_hard_satisfied, total_soft_penalty, first_violation_msg_or_None).
    """
    rules = _logical_constraints(db)
    # Build unavailable sets per entity from the solution and the 3-state matrix
    av = _availability_constraints(db)
    teacher_unavail: dict[str, set] = {}
    class_unavail: dict[str, set] = {}
    room_unavail: dict[str, set] = {}
    # 3-state hard cells already block the slot
    for t, d, h in av["teacher_hard"]:
        teacher_unavail.setdefault(t, set()).add((d, h))
    for c, d, h in av["class_hard"]:
        class_unavail.setdefault(c, set()).add((d, h))
    for r, d, h in av["room_hard"]:
        room_unavail.setdefault(r, set()).add((d, h))
    # Slots actually busy in the solution count as unavailable for the
    # entity (occupied by a lesson)
    active = engine_io.get_active_solution(db)
    rooms_by_lesson = {}
    if active is not None:
        for l in db.query(models.Lesson).filter(
            models.Lesson.solution_id == active.id
        ).all():
            rooms_by_lesson[(l.teacher_name, l.class_name, l.subject,
                             l.day, l.hour)] = l.classroom_name
    for k, v in sol.items():
        if v != 1:
            continue
        p, cl, _subj, d, h = k
        teacher_unavail.setdefault(p, set()).add((d, h))
        class_unavail.setdefault(cl, set()).add((d, h))
        room = rooms_by_lesson.get(k)
        if room:
            room_unavail.setdefault(room, set()).add((d, h))

    total_soft = 0
    first_violation = None

    def visit(group_name, name_to_set, rule_group):
        nonlocal total_soft, first_violation
        for name, rule_list in rule_group.items():
            unav = name_to_set.get(name, set())
            for rule in rule_list:
                from .utils.logic_parser import evaluate_against_unavailable
                ok = evaluate_against_unavailable(rule["clauses"], unav)
                pen = int(rule["soft_penalty"])
                if not ok:
                    if rule["is_hard"]:
                        if first_violation is None:
                            first_violation = (
                                f"vincolo logico HARD violato su {group_name} "
                                f"{name}"
                            )
                        return  # stop on first hard violation
                    if pen >= 0:
                        # SOFT, pay penalty when violated
                        total_soft += pen
                    # PREFERRED violated -> no contribution
                else:
                    if not rule["is_hard"] and pen < 0:
                        # PREFERRED satisfied -> bonus (negative addend)
                        total_soft += pen

    visit("docente", teacher_unavail, rules["teacher_rules"])
    if first_violation is None:
        visit("classe", class_unavail, rules["class_rules"])
    if first_violation is None:
        visit("aula", room_unavail, rules["room_rules"])
    return (first_violation is None, total_soft, first_violation)


def _availability_constraints(db: Session) -> dict[str, Any]:
    """Materialize the HARD/SOFT availability per (teacher, class,
    classroom). Used by drag-drop validation and soft scoring.

    Returns:
      teacher_hard:    set[(name, day, hour)]
      teacher_soft:    dict[(name, day, hour) -> penalty]
      class_hard:      set[(name, day, hour)]
      class_soft:      dict[...]
      room_hard:       set[(name, day, hour)]
      room_soft:       dict[...]
    """
    teacher_hard: set = set()
    teacher_soft: dict = {}
    teacher_enforced: set = set()
    teachers = {t.id: t for t in db.query(models.Teacher).all()}
    for u in db.query(models.TeacherUnavailability).all():
        t = teachers.get(u.teacher_id)
        if t is None:
            continue
        if u.state == "hard":
            teacher_hard.add((t.name, u.day, u.hour))
        elif u.state in ("soft", "preferred"):
            # 'soft'      -> positive penalty (penalised when used)
            # 'preferred' -> negative penalty (rewarded when used)
            teacher_soft[(t.name, u.day, u.hour)] = u.soft_penalty
        elif u.state == "enforced":
            # The teacher MUST have a lesson at this slot. The hard
            # constraint is enforced at solver time; here we just collect.
            teacher_enforced.add((t.name, u.day, u.hour))
    # Auto-promote free_day -> 6 hard cells
    for t in teachers.values():
        d = DAY_TO_INT.get(t.free_day or "")
        if d is None:
            continue
        for h in HOURS:
            teacher_hard.add((t.name, d, h))

    class_hard: set = set()
    class_soft: dict = {}
    class_enforced: set = set()
    classes = {c.id: c for c in db.query(models.SchoolClass).all()}
    for u in db.query(models.ClassUnavailability).all():
        c = classes.get(u.class_id)
        if c is None:
            continue
        if u.state == "hard":
            class_hard.add((c.name, u.day, u.hour))
        elif u.state in ("soft", "preferred"):
            class_soft[(c.name, u.day, u.hour)] = u.soft_penalty
        elif u.state == "enforced":
            class_enforced.add((c.name, u.day, u.hour))

    room_hard: set = set()
    room_soft: dict = {}
    room_enforced: set = set()
    rooms = {r.id: r for r in db.query(models.Classroom).all()}
    for u in db.query(models.ClassroomUnavailability).all():
        r = rooms.get(u.classroom_id)
        if r is None:
            continue
        if u.state == "hard":
            room_hard.add((r.name, u.day, u.hour))
        elif u.state in ("soft", "preferred"):
            room_soft[(r.name, u.day, u.hour)] = u.soft_penalty
        elif u.state == "enforced":
            room_enforced.add((r.name, u.day, u.hour))

    return {
        "teacher_hard": teacher_hard,
        "teacher_soft": teacher_soft,
        "teacher_enforced": teacher_enforced,
        "class_hard": class_hard,
        "class_soft": class_soft,
        "class_enforced": class_enforced,
        "room_hard": room_hard,
        "room_soft": room_soft,
        "room_enforced": room_enforced,
    }


def availability_soft_penalty(sol: dict, db: Session) -> int:
    """Sum of soft penalties induced by SOFT-yellow availability cells
    overlapping with active lessons in `sol`."""
    av = _availability_constraints(db)
    total = 0
    # Need lesson rows for classroom info
    rooms_by_lesson = {}
    active = engine_io.get_active_solution(db)
    if active is not None:
        for l in db.query(models.Lesson).filter(
            models.Lesson.solution_id == active.id
        ).all():
            rooms_by_lesson[(l.teacher_name, l.class_name, l.subject,
                             l.day, l.hour)] = l.classroom_name
    for k, v in sol.items():
        if v != 1:
            continue
        p, cl, _subj, d, h = k
        total += av["teacher_soft"].get((p, d, h), 0)
        total += av["class_soft"].get((cl, d, h), 0)
        room = rooms_by_lesson.get(k)
        if room:
            total += av["room_soft"].get((room, d, h), 0)
    return total


def preview_moves_for_lesson(db: Session, src: tuple,
                              candidates: list[tuple[int, int]] | None = None
                              ) -> list[dict[str, Any]]:
    """For each (day, hour) candidate, simulate moving the lesson at src
    there and report:
      - status: 'ok' / 'hard_violation' / 'soft_worse' / 'noop'
      - reason: explanation when violating HARD
      - delta_soft: int delta (negative = improvement)
    The simulation does NOT persist anything."""
    import metaheuristics as meta  # type: ignore

    active = engine_io.get_active_solution(db)
    if active is None:
        return []
    sol = engine_io.lessons_to_solution_dict(db, active.id)
    profs = engine_io.profs_dict_from_db(db)
    if src not in sol:
        return []
    if candidates is None:
        candidates = [(d, h) for d in DAYS for h in HOURS]
    av = _availability_constraints(db)
    p, cl, subj, _, _ = src
    src_lesson = db.query(models.Lesson).filter(
        models.Lesson.solution_id == active.id,
        models.Lesson.teacher_name == p,
        models.Lesson.class_name == cl,
        models.Lesson.subject == subj,
        models.Lesson.day == src[3],
        models.Lesson.hour == src[4],
    ).first()
    src_room = src_lesson.classroom_name if src_lesson else None
    v0, _ = meta.compute_soft(sol, profs)

    results: list[dict[str, Any]] = []
    for d, h in candidates:
        if d == src[3] and h == src[4]:
            results.append({"day": d, "hour": h, "status": "noop",
                            "reason": "slot di origine",
                            "delta_soft": 0})
            continue
        dst = (p, cl, subj, d, h)
        # quick HARD checks: 3-state availability for teacher/class/room
        if (p, d, h) in av["teacher_hard"]:
            results.append({"day": d, "hour": h,
                            "status": "hard_violation",
                            "reason": f"docente {p} HARD non disp.",
                            "delta_soft": None})
            continue
        if (cl, d, h) in av["class_hard"]:
            results.append({"day": d, "hour": h,
                            "status": "hard_violation",
                            "reason": f"classe {cl} HARD non disp.",
                            "delta_soft": None})
            continue
        # Note: room availability is INTENTIONALLY not checked here. The
        # preview shows the slot as free if teacher/class allow the move;
        # if the lesson's old room is occupied (or HARD-unavailable) at
        # the destination, validate_and_apply_move clears the room and
        # asks the user to pick a new one (room_cleared=True flag).
        # destination already occupied by SAME (same triple) -> noop
        if sol.get(dst, 0) == 1:
            results.append({"day": d, "hour": h, "status": "noop",
                            "reason": "stessa lezione presente",
                            "delta_soft": 0})
            continue
        # destination occupied by DIFFERENT triple -> overlap explanation
        # detect class or teacher already busy at (d, h)
        teacher_busy = any(
            v == 1 and k[0] == p and k[3] == d and k[4] == h
            for k, v in sol.items() if k != src
        )
        class_busy = any(
            v == 1 and k[1] == cl and k[3] == d and k[4] == h
            for k, v in sol.items() if k != src
        )
        if teacher_busy:
            results.append({"day": d, "hour": h,
                            "status": "hard_violation",
                            "reason": f"docente {p} occupato in altro slot",
                            "delta_soft": None})
            continue
        if class_busy:
            results.append({"day": d, "hour": h,
                            "status": "hard_violation",
                            "reason": f"classe {cl} ha gia\\` lezione in {d}/{h}",
                            "delta_soft": None})
            continue
        # full HARD check (covers no-holes / dual-mat / motorie / 5-consec)
        new_sol = dict(sol)
        new_sol[src] = 0
        new_sol[dst] = 1
        if not meta.is_hard_feasible(new_sol, profs, verbose=False):
            results.append({"day": d, "hour": h,
                            "status": "hard_violation",
                            "reason": "viola un vincolo HARD globale "
                                      "(buchi/uscita/dual mat/motorie)",
                            "delta_soft": None})
            continue
        ok_hard, _soft_logical_new, msg = _logical_check_for_solution(db, new_sol)
        if not ok_hard:
            results.append({"day": d, "hour": h,
                            "status": "hard_violation",
                            "reason": msg or "vincolo logico HARD violato",
                            "delta_soft": None})
            continue
        v1, _ = meta.compute_soft(new_sol, profs)
        # 3-state + logical SOFT contributions
        _ok0, soft_logical_old, _ = _logical_check_for_solution(db, sol)
        v0_full = v0 + availability_soft_penalty(sol, db) + soft_logical_old
        v1_full = v1 + availability_soft_penalty(new_sol, db) + _soft_logical_new
        delta = int(v1_full - v0_full)
        if delta > 0:
            status = "soft_worse"
        elif delta < 0:
            status = "ok"
        else:
            status = "ok"
        results.append({"day": d, "hour": h, "status": status,
                        "reason": None, "delta_soft": delta})
    return results


def validate_and_apply_move(db: Session, src: tuple,
                            dst: tuple) -> dict[str, Any]:
    """src/dst are (teacher_name, class_name, subject, day, hour). The lesson
    at src moves to dst. Returns a dict with accepted/reason and optional
    obj before/after."""
    import metaheuristics as meta  # type: ignore
    active = engine_io.get_active_solution(db)
    if active is None:
        return {"accepted": False, "reason": "Nessuna soluzione attiva"}
    sol = engine_io.lessons_to_solution_dict(db, active.id)
    profs = engine_io.profs_dict_from_db(db)
    if src not in sol:
        return {"accepted": False, "reason": "Lezione di origine non trovata"}
    if sol.get(dst, 0) == 1:
        return {"accepted": False,
                "reason": "Slot di destinazione gia\` occupato dalla "
                          "stessa lezione (no-op)"}
    # 3-state availability HARD enforcement (teacher / class / classroom)
    av = _availability_constraints(db)
    p_dst, cl_dst, _subj_dst, d_dst, h_dst = dst
    if (p_dst, d_dst, h_dst) in av["teacher_hard"]:
        return {"accepted": False,
                "reason": (f"Il docente {p_dst} ha indisponibilita HARD "
                           f"in giorno {d_dst} ora {h_dst}.")}
    if (cl_dst, d_dst, h_dst) in av["class_hard"]:
        return {"accepted": False,
                "reason": (f"La classe {cl_dst} ha indisponibilita HARD "
                           f"in giorno {d_dst} ora {h_dst}.")}
    # if the lesson has a classroom, also check room HARD
    src_lesson = db.query(models.Lesson).filter(
        models.Lesson.solution_id == active.id,
        models.Lesson.teacher_name == src[0],
        models.Lesson.class_name == src[1],
        models.Lesson.subject == src[2],
        models.Lesson.day == src[3],
        models.Lesson.hour == src[4],
    ).first()
    # Room HARD-unavailability is NOT a reason to reject the move: the
    # post-apply pass below will simply clear the classroom and tell the
    # caller via room_cleared=True so the UI can prompt for a new pick.

    new_sol = dict(sol)
    new_sol[src] = 0
    new_sol[dst] = 1
    if not meta.is_hard_feasible(new_sol, profs, verbose=False):
        return {"accepted": False,
                "reason": "Mossa rifiutata: viola almeno un vincolo HARD."}
    # Logical disjunctive HARD constraints
    ok_hard, _soft_pen, msg = _logical_check_for_solution(db, new_sol)
    if not ok_hard:
        return {"accepted": False,
                "reason": "Mossa rifiutata: " + (msg or "vincolo logico HARD violato.")}
    v0, m0 = meta.compute_soft(sol, profs)
    v1, m1 = meta.compute_soft(new_sol, profs)
    # 3-state SOFT contribution (added on top of meta SOFT score)
    v0 += availability_soft_penalty(sol, db)
    v1 += availability_soft_penalty(new_sol, db)
    # Logical SOFT contribution
    _ok0, soft0, _ = _logical_check_for_solution(db, sol)
    _ok1, soft1, _ = _logical_check_for_solution(db, new_sol)
    v0 += soft0
    v1 += soft1
    # Apply: replace the solution dict, then carry the classroom across
    # the move (replace_solution_lessons keys on (p,cl,subj,day,hour),
    # so the moved lesson would otherwise lose its classroom).
    engine_io.replace_solution_lessons(db, active.id, new_sol)
    src_room = src_lesson.classroom_name if src_lesson else None
    room_cleared = False
    cleared_room = None
    if src_room:
        # Look up the moved lesson row by its new key
        new_row = db.query(models.Lesson).filter(
            models.Lesson.solution_id == active.id,
            models.Lesson.teacher_name == dst[0],
            models.Lesson.class_name == dst[1],
            models.Lesson.subject == dst[2],
            models.Lesson.day == dst[3],
            models.Lesson.hour == dst[4],
        ).first()
        # Conflict 1: the room is occupied by another lesson at dst
        conflict_lesson = db.query(models.Lesson).filter(
            models.Lesson.solution_id == active.id,
            models.Lesson.day == dst[3],
            models.Lesson.hour == dst[4],
            models.Lesson.classroom_name == src_room,
            models.Lesson.id != (new_row.id if new_row else -1),
        ).first()
        # Conflict 2: the room is HARD-unavailable in admin matrix at dst
        conflict_admin = (src_room, dst[3], dst[4]) in av["room_hard"]
        if new_row is not None:
            if conflict_lesson is None and not conflict_admin:
                # Free: carry the room across the move
                new_row.classroom_name = src_room
            else:
                # Occupied: leave the moved lesson without a classroom and
                # tell the caller so the UI can prompt for a new pick.
                new_row.classroom_name = None
                room_cleared = True
                cleared_room = src_room
    active.obj_value = float(v1)
    active.metrics_json = json.dumps({**m1, "feasible": True})
    db.commit()
    return {
        "accepted": True,
        "reason": ("Miglioramento di "
                   f"{int(v0 - v1)} punti SOFT" if v1 < v0 else
                   ("Stesso valore SOFT" if v1 == v0
                    else f"Peggioramento di {int(v1 - v0)} punti SOFT")),
        "obj_before": float(v0),
        "obj_after": float(v1),
        "delta": float(v1 - v0),
        "metrics_before": m0,
        "metrics_after": m1,
        "room_cleared": room_cleared,
        "cleared_room": cleared_room,
    }


# ----------------------------------------------------------------------
# DECOMPOSITION: temporal (per-day) parallel pipeline
# ----------------------------------------------------------------------

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
            locked_snap = _snapshot_locked_lessons(db)
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
        import sys
        exp_dir = os.path.join(
            os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__)))),
            "engine", "scripts")
        if exp_dir not in sys.path:
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
        if locked_snap:
            print(f"[temporal] native lock path: {len(locked_snap)} "
                  f"locked lessons fed to solver")
        if coteach_groups:
            print(f"[temporal] {len(coteach_groups)} coteach groups "
                  f"fed to solver")
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
        )
        update_run(rid, progress=0.85)

        full_solution = result["full_solution"]
        timings = result["timings"]
        failed_days = result["failed_days"]
        status = result["status"]

        import metaheuristics as meta  # type: ignore
        v0, m0 = meta.compute_soft(full_solution, profs)
        feasible = meta.is_hard_feasible(full_solution, profs, verbose=False)
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
                if meta.is_hard_feasible(refined, profs, verbose=False) \
                        and v1 <= v0:
                    print(f"[temporal] ALNS improved {v0:.1f} -> {v1:.1f}")
                    full_solution = refined
                    v0, m0 = v1, m1
                else:
                    print(f"[temporal] ALNS dropped (no improvement or "
                          f"infeasible)")
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
                make_active=True,
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
            locked_snap = _snapshot_locked_lessons(db)
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

        import sys
        exp_dir = os.path.join(
            os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__)))),
            "engine", "scripts")
        if exp_dir not in sys.path:
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
        if locked_snap:
            print(f"[curriculum] native lock path: {len(locked_snap)} "
                  f"locked lessons fed to solver")
        if coteach_groups:
            print(f"[curriculum] {len(coteach_groups)} coteach groups")
        result = dec_c.solve_with_curriculum_decomposition(
            profs, cls_to_curr, manual,
            time_a=time_a, time_bridges=time_bridges,
            time_per_cluster=time_per_cluster,
            time_ricucitura=time_ricucitura, time_mono=time_mono,
            workers=workers, log=True,
            locked_day_count=locked_dc,
            locked_by_day=locked_by_day,
            coteach_groups=coteach_groups or None,
        )
        update_run(rid, progress=0.85)
        full_solution = result["full_solution"]
        timings = result["timings"]
        failed_days = result["failed_days"]
        status = result["status"]

        import metaheuristics as meta  # type: ignore
        v0, m0 = meta.compute_soft(full_solution, profs)
        feasible = meta.is_hard_feasible(full_solution, profs, verbose=False)

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
                if (meta.is_hard_feasible(refined, profs, verbose=False)
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
                make_active=True,
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
            locked_snap = _snapshot_locked_lessons(db)
            profs = engine_io.profs_dict_from_db(db)
        if not profs:
            raise RuntimeError("Nessun assegnamento prof->classe.")

        import sys
        exp_dir = os.path.join(
            os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__)))),
            "engine", "scripts")
        if exp_dir not in sys.path:
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
        if locked_snap:
            print(f"[metis] native lock path: {len(locked_snap)} "
                  f"locked lessons fed to solver")
        if coteach_groups:
            print(f"[metis] {len(coteach_groups)} coteach groups")
        result = dec_m.solve_with_metis_decomposition(
            profs, k=k, imbalance=imbalance,
            time_a=time_a, time_bridges=time_bridges,
            time_per_cluster=time_per_cluster,
            time_ricucitura=time_ricucitura, time_mono=time_mono,
            workers=workers, log=True,
            locked_day_count=locked_dc,
            locked_by_day=locked_by_day,
            coteach_groups=coteach_groups or None,
        )
        update_run(rid, progress=0.85)
        full_solution = result["full_solution"]
        timings = result["timings"]
        failed_days = result["failed_days"]
        status = result["status"]

        import metaheuristics as meta  # type: ignore
        v0, m0 = meta.compute_soft(full_solution, profs)
        feasible = meta.is_hard_feasible(full_solution, profs, verbose=False)

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
                if (meta.is_hard_feasible(refined, profs, verbose=False)
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
                make_active=True,
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
