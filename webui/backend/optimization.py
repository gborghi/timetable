"""High-level wrappers that turn DB state into engine-friendly inputs,
invoke the experiments/ functions, and persist the results back to the DB.

Each public function returns the run_id; the actual work runs in a thread
managed by run_manager."""
from __future__ import annotations

import datetime as dt
import json
import os
import pickle
import random
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
        update_run(rid, progress=1.0, metrics={
            "classes": n_classes, "teachers": n_teachers,
        })
        print(f"[mock] DB now has {n_classes} classes and "
              f"{n_teachers} teachers")

    start_thread(run_id, target)
    return run_id


# ----------------------------------------------------------------------
# Import a pre-existing experiments/ pickle (small/big/medium/...)
# ----------------------------------------------------------------------


def import_experiments_profile(profile: str, use_optimized: bool,
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
    experiments_dir = os.path.normpath(
        os.path.join(here, "..", "..", "experiments")
    )

    def target(rid: int):
        school_pkl = os.path.join(experiments_dir, f"school_{profile}.pkl")
        profs_pkl = os.path.join(experiments_dir, f"profs_{profile}.pkl")
        sol_optimized = os.path.join(
            experiments_dir, f"solution_timetable_{profile}_optimized.pkl"
        )
        sol_decomposed = os.path.join(
            experiments_dir, f"solution_timetable_{profile}_decomposed.pkl"
        )
        sol_plain = os.path.join(
            experiments_dir, f"solution_timetable_{profile}.pkl"
        )
        if not os.path.exists(school_pkl):
            raise FileNotFoundError(
                f"school_{profile}.pkl not found in experiments/"
            )
        with open(school_pkl, "rb") as f:
            school = pickle.load(f)
        print(f"[import] loaded {school_pkl}: "
              f"{len(school.get('classes', []))} classes, "
              f"{len(school.get('teachers', []))} teachers")
        with SessionLocal() as db:
            engine_io.import_school_into_db(db, school, replace=True)

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
        elif os.path.exists(sol_decomposed):
            sol_path = sol_decomposed
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


def run_assignment(time_limit_s: float, workers: int, log: bool) -> int:
    params = dict(time_limit_s=time_limit_s, workers=workers, log=log)
    run_id = create_run("assignment", "Assegnazione docenti->classi",
                        None, params)

    def target(rid: int):
        import cpsat_v2_assignment as ca  # type: ignore
        with SessionLocal() as db:
            data = engine_io.school_dict_from_db(db)
        if not data["classes"] or not data["teachers"]:
            raise RuntimeError("DB vuoto: importa o genera una scuola.")
        cattedre, solver, status = ca.solve_assignment(
            data, time_limit_s=time_limit_s,
            workers=workers, log=log,
        )
        ws = _run_workspace(rid)
        with open(os.path.join(ws, "cattedre.pkl"), "wb") as f:
            pickle.dump(cattedre, f)
        with SessionLocal() as db:
            n = engine_io.import_assignments_into_db(db, cattedre)
        print(f"[assign] saved {n} assignments to DB")
        update_run(rid, progress=1.0,
                   metrics={"assignments": n, "status": str(status)})

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
                use_decomposition: bool = True) -> int:
    params = dict(k=k, time_a=time_a, time_bridges=time_bridges,
                  time_cluster=time_cluster, time_ricucitura=time_ricucitura,
                  time_mono=time_mono, workers=workers, log=log,
                  use_decomposition=use_decomposition)
    run_id = create_run("phase_b", "Schedulazione orario", None, params)

    def target(rid: int):
        with SessionLocal() as db:
            profs = engine_io.profs_dict_from_db(db)
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
        # Phase A inside the timetable: day_count
        dc_value = cv2.solve_phase_a(
            profs, classes, triples, class_profs,
            time_limit=time_a, workers=workers, log=log,
        )
        with open(os.path.join(ws, "phase_a_dc.pkl"), "wb") as f:
            pickle.dump(dc_value, f)

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
            for d in DAYS:
                out, status = dec.stage_a_bridges(
                    d, profs, bridges_set, triples, dc_value,
                    time_bridges, workers,
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
                for k_id in sorted(classes_per_cluster,
                                    key=lambda kk: -len(classes_per_cluster[kk])):
                    cl_set = classes_per_cluster[k_id]
                    if not cl_set:
                        continue
                    out, status = dec.stage_b_cluster_internals(
                        cl_set, d, profs, bridges_set, triples, dc_value,
                        bridge_solutions[d], time_cluster, workers,
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
                        full_solution.update(cluster_solutions[(k_id, d)])
            days_C = sorted(set(b_failed.keys()) | set(a_failed))
            c_failed = []
            for d in days_C:
                succ = {}
                for k_id in classes_per_cluster:
                    if k_id in b_failed.get(d, set()):
                        continue
                    if (k_id, d) in cluster_solutions:
                        succ.update(cluster_solutions[(k_id, d)])
                out, status = dec.stage_c_ricucitura(
                    d, profs, bridges_set, triples, dc_value, succ,
                    time_ricucitura, workers,
                )
                if out is None:
                    c_failed.append(d)
                else:
                    full_solution = {
                        kk: vv for kk, vv in full_solution.items()
                        if kk[3] != d
                    }
                    full_solution.update(out)
            for d in c_failed:
                out, status = dec.solve_monolithic_day(
                    d, profs, triples, dc_value,
                    time_mono, workers,
                )
                if out is not None:
                    full_solution = {
                        kk: vv for kk, vv in full_solution.items()
                        if kk[3] != d
                    }
                    full_solution.update(out)
        else:
            # monolithic per day
            for d in DAYS:
                out, status = cv2.solve_phase_b_for_day(
                    d, profs, classes, triples, class_profs, dc_value,
                    time_limit=time_mono, workers=workers, log=log,
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
        update_run(rid, solution_id=sid, obj_value=float(v),
                   metrics={**m, "feasible": feasible},
                   progress=1.0)
        print(f"[phaseB] solution id={sid} obj={v} metrics={m}")

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
             tabu_size: int = 80) -> int:
    params = dict(stage=stage, budget_s=budget_s, workers=workers, log=log,
                  n_cycles=n_cycles,
                  ts_budget_per_cycle=ts_budget_per_cycle,
                  sa_T0=sa_T0, sa_alpha=sa_alpha,
                  tabu_size=tabu_size)
    run_id = create_run(stage, f"{stage.upper()} on active solution",
                        None, params)

    def target(rid: int):
        import metaheuristics as meta  # type: ignore
        import decomposition_spectral_v2 as dec  # type: ignore
        with SessionLocal() as db:
            profs = engine_io.profs_dict_from_db(db)
            active = engine_io.get_active_solution(db)
            if active is None:
                raise RuntimeError("Nessuna soluzione attiva; esegui prima "
                                   "Phase B o importa un pickle.")
            sol = engine_io.lessons_to_solution_dict(db, active.id)
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
        if stage == "lns":
            new_sol, _hist = meta.run_lns(
                sol, profs, dc_value, budget_s,
                classes_clusters=classes_clusters,
                log=log, workers=workers,
            )
        elif stage == "sa":
            new_sol = meta.run_sa(
                sol, profs, dc_value, budget_s,
                T0=sa_T0, alpha=sa_alpha, log=log,
            )
        elif stage == "ts":
            new_sol = meta.run_tabu(
                sol, profs, dc_value, budget_s,
                tabu_size=tabu_size, log=log,
            )
        elif stage == "ils":
            new_sol = meta.run_ils(
                sol, profs, dc_value, budget_s,
                classes_clusters=classes_clusters,
                ts_budget_per_cycle=ts_budget_per_cycle,
                n_cycles=n_cycles, log=log,
            )
        else:
            raise RuntimeError(f"Unknown stage {stage}")

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
        update_run(rid, solution_id=sid, obj_value=float(v),
                   metrics={**m, "feasible": feasible}, progress=1.0)
        print(f"[{stage}] solution id={sid} obj={v} metrics={m}")

    start_thread(run_id, target)
    return run_id


# ----------------------------------------------------------------------
# Step 8: full pipeline
# ----------------------------------------------------------------------


def run_full_pipeline(profile: str, time_assign: float,
                      phase_b_kwargs: dict[str, Any],
                      budget_lns: float, budget_sa: float,
                      budget_ts: float, budget_ils: float,
                      workers: int = 8) -> int:
    params = dict(profile=profile, time_assign=time_assign,
                  phase_b=phase_b_kwargs,
                  budget_lns=budget_lns, budget_sa=budget_sa,
                  budget_ts=budget_ts, budget_ils=budget_ils,
                  workers=workers)
    run_id = create_run("full", f"Full pipeline ({profile})", profile, params)

    def target(rid: int):
        import cpsat_v2_assignment as ca  # type: ignore
        import cpsat_v2_timetable as cv2  # type: ignore
        import decomposition_spectral_v2 as dec  # type: ignore
        import metaheuristics as meta  # type: ignore

        with SessionLocal() as db:
            data = engine_io.school_dict_from_db(db)
            n_cl = db.query(models.SchoolClass).count()
            n_te = db.query(models.Teacher).count()
        print(f"[full] starting on {n_cl} classes, {n_te} teachers")

        print("[full] === STEP 2: assignment ===")
        cattedre, solver, status = ca.solve_assignment(
            data, time_limit_s=time_assign, workers=workers, log=False,
        )
        with SessionLocal() as db:
            engine_io.import_assignments_into_db(db, cattedre)
            profs = engine_io.profs_dict_from_db(db)

        update_run(rid, progress=0.15)
        print("[full] === STEP 3: phase B (decomposed) ===")
        classes, triples, class_profs = cv2.build_indices(profs)
        dc_value = cv2.solve_phase_a(
            profs, classes, triples, class_profs,
            time_limit=phase_b_kwargs.get("time_a", 60),
            workers=workers, log=False,
        )

        full_solution: dict = {}
        if phase_b_kwargs.get("use_decomposition", True) and len(classes) >= 8:
            M, classes_v, _ = dec.build_adjacency(profs)
            k = phase_b_kwargs.get("k", 4)
            labels, _ = dec.spectral_cluster(M, k)
            bridges, cl_to_label = dec.find_bridges(profs, classes_v, labels)
            classes_per_cluster = defaultdict(set)
            for c, lbl in cl_to_label.items():
                classes_per_cluster[lbl].add(c)
            bridges_set = set(bridges.keys())
            bridge_solutions: dict[int, dict] = {}
            a_failed = []
            for d in DAYS:
                out, _st = dec.stage_a_bridges(
                    d, profs, bridges_set, triples, dc_value,
                    phase_b_kwargs.get("time_bridges", 30), workers,
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
                for k_id in sorted(classes_per_cluster,
                                    key=lambda kk: -len(classes_per_cluster[kk])):
                    out, _st = dec.stage_b_cluster_internals(
                        classes_per_cluster[k_id], d, profs, bridges_set,
                        triples, dc_value, bridge_solutions[d],
                        phase_b_kwargs.get("time_cluster", 20), workers,
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
                        full_solution.update(cluster_solutions[(k_id, d)])
            for d in sorted(set(b_failed.keys()) | set(a_failed)):
                succ = {}
                for k_id in classes_per_cluster:
                    if k_id in b_failed.get(d, set()):
                        continue
                    if (k_id, d) in cluster_solutions:
                        succ.update(cluster_solutions[(k_id, d)])
                out, _st = dec.stage_c_ricucitura(
                    d, profs, bridges_set, triples, dc_value, succ,
                    phase_b_kwargs.get("time_ricucitura", 60), workers,
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
                    d, profs, classes, triples, class_profs, dc_value,
                    time_limit=phase_b_kwargs.get("time_mono", 120),
                    workers=workers, log=False,
                )
                if out is not None:
                    full_solution.update(out)
        update_run(rid, progress=0.45)

        v0, m0 = meta.compute_soft(full_solution, profs)
        print(f"[full] phase B done: obj={v0} metrics={m0}")

        # Cluster for LNS/ILS
        M, classes_v, _ = dec.build_adjacency(profs)
        labels, _ = dec.spectral_cluster(
            M, max(2, min(4, len(classes_v) // 5))
        )
        cc = defaultdict(set)
        for i, c in enumerate(classes_v):
            cc[int(labels[i])].add(c)
        classes_clusters = dict(cc)

        budgets = dict(
            lns=budget_lns, sa=budget_sa,
            ts=budget_ts, ils=budget_ils,
        )
        sol_final, history = meta.run_cascade(
            full_solution, profs, dc_value, budgets,
            classes_clusters=classes_clusters, log=True,
        )
        v, m = meta.compute_soft(sol_final, profs)
        feasible = meta.is_hard_feasible(sol_final, profs, verbose=False)

        with SessionLocal() as db:
            sid = engine_io.import_solution_into_db(
                db, sol_final,
                name=f"Full pipeline run {rid}",
                kind="full",
                obj_value=float(v),
                metrics={**m, "feasible": feasible},
                make_active=True,
            )
        update_run(rid, solution_id=sid, obj_value=float(v),
                   metrics={**m, "feasible": feasible}, progress=1.0)
        print(f"[full] DONE id={sid} obj={v} metrics={m}")

    start_thread(run_id, target)
    return run_id


# ----------------------------------------------------------------------
# Drag & drop validation: HARD-only check
# ----------------------------------------------------------------------


def run_classroom_assignment(time_limit_s: float, workers: int, log: bool,
                             prefer_home: bool = True) -> int:
    """Step 'Assegna aule' — uses experiments/classroom_assignment.py."""
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
        if not rooms:
            raise RuntimeError(
                "Nessuna aula nel DB: importa o genera la lista aule prima."
            )
        if not lessons:
            raise RuntimeError("Soluzione attiva senza lezioni.")
        print(f"[rooms] {len(lessons)} lezioni, {len(rooms)} aule")
        result, status = solve_classroom_assignment(
            lessons, rooms, time_limit_s=time_limit_s,
            workers=workers, log=log,
        )
        if result is None:
            print(f"[rooms] CP-SAT infeasible ({status}); fallback greedy")
            result = greedy_classroom_assignment(
                lessons, rooms, prefer_home=prefer_home
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
        # Wipe existing classrooms
        db.query(models.ClassroomSubjectPreference).delete()
        db.query(models.ClassroomClassPreference).delete()
        db.query(models.ClassroomUnavailability).delete()
        db.query(models.Classroom).delete()
        db.commit()
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
