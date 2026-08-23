"""High-level wrappers that turn DB state into engine-friendly inputs,
invoke the engine/ functions, and persist the results back to the DB.

Each public function returns the run_id; the actual work runs in a thread
managed by run_manager.

The pipeline pieces that used to live in this file now live under
``backend.pipeline`` (preflight, diagnostics, rooms, moves,
decompositions, HARD-check context). This module remains the
compatibility facade: ``from backend.optimization import X`` still
works for every historical name.
"""
from __future__ import annotations

import contextlib
import os
import pickle
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

# This import has to come BEFORE the engine modules:
from .engine_paths import ensure_engine_on_path  # noqa: E402

ensure_engine_on_path()

from ortools.sat.python import cp_model
from sqlalchemy.orm import Session

from . import engine_io, models
from .db import SessionLocal
from .run_manager import (
    create_run,
    is_cancel_requested,
    raise_if_cancelled,
    start_thread,
    update_run,
)

from .workspace import (
    _coverage_ratio,
    _coverage_strict,
    _gate_coverage,
    _run_workspace,
    _uncovered_report,
)

from .pipeline.decompositions import (
    run_decomposition_curriculum as run_decomposition_curriculum,
)
from .pipeline.decompositions import (
    run_decomposition_metis as run_decomposition_metis,
)
from .pipeline.decompositions import (
    run_decomposition_temporal as run_decomposition_temporal,
)
from .pipeline.diagnostics import (
    run_diag_bipartite as run_diag_bipartite,
)
from .pipeline.diagnostics import (
    run_diag_correlations as run_diag_correlations,
)
from .pipeline.diagnostics import (
    run_diag_distributions as run_diag_distributions,
)
from .pipeline.diagnostics import (
    run_diag_hall_check as run_diag_hall_check,
)
from .pipeline.diagnostics import (
    run_diag_montecarlo as run_diag_montecarlo,
)
from .pipeline.diagnostics import (
    run_diagnostic_async as run_diagnostic_async,
)
from .pipeline.diagnostics import run_hall_check as run_hall_check
from .pipeline.grid import DAY_TO_INT as DAY_TO_INT
from .pipeline.grid import DAYS as DAYS
from .pipeline.grid import HOURS as HOURS
from .pipeline.hard_check import (
    _build_special_room_ctx_safe as _build_special_room_ctx_safe,
)
from .pipeline.hard_check import _class_busy_key_fn as _class_busy_key_fn
from .pipeline.hard_check import _hard_check_ctx as _hard_check_ctx
from .pipeline.hard_check import _hard_check_ctx_fresh as _hard_check_ctx_fresh
from .pipeline.hard_check import (
    _load_dsl_hard_expressions as _load_dsl_hard_expressions,
)
from .pipeline.moves import (
    _availability_constraints as _availability_constraints,
)
from .pipeline.moves import (
    _logical_check_for_solution as _logical_check_for_solution,
)
from .pipeline.moves import _logical_constraints as _logical_constraints
from .pipeline.moves import (
    _logical_violation_summary as _logical_violation_summary,
)
from .pipeline.moves import assess_solution_health as assess_solution_health
from .pipeline.moves import (
    availability_soft_penalty as availability_soft_penalty,
)
from .pipeline.moves import preview_moves_for_lesson as preview_moves_for_lesson
from .pipeline.moves import validate_and_apply_move as validate_and_apply_move
from .pipeline.moves import validate_and_apply_swap as validate_and_apply_swap
from .pipeline.moves import validate_hard_placement as validate_hard_placement
from .pipeline.preflight import (
    _LOCK_MAX_PER_DAY_PROF_CL as _LOCK_MAX_PER_DAY_PROF_CL,
)
from .pipeline.preflight import (
    _LOCK_MAX_PER_DAY_TRIPLE as _LOCK_MAX_PER_DAY_TRIPLE,
)
from .pipeline.preflight import (
    _LOCK_MAX_PROF_HOURS_PER_DAY as _LOCK_MAX_PROF_HOURS_PER_DAY,
)
from .pipeline.preflight import (
    _apply_locked_classrooms as _apply_locked_classrooms,
)
from .pipeline.preflight import (
    _locked_day_count_from_snapshot as _locked_day_count_from_snapshot,
)
from .pipeline.preflight import _locked_slots_by_day as _locked_slots_by_day
from .pipeline.preflight import _preflight_lock_check as _preflight_lock_check
from .pipeline.preflight import _read_locked_lessons as _read_locked_lessons
from .pipeline.preflight import (
    _snapshot_and_validate_locks as _snapshot_and_validate_locks,
)
from .pipeline.preflight import (
    validate_coteach_sostegno_potenziamento
    as validate_coteach_sostegno_potenziamento,
)
from .pipeline.preflight import (
    validate_locks_vs_constraints as validate_locks_vs_constraints,
)
from .pipeline.preflight import validate_plessi_rules as validate_plessi_rules
from .pipeline.rooms import _apply_joint_room_map as _apply_joint_room_map
from .pipeline.rooms import _apply_rooms_to_solution as _apply_rooms_to_solution
from .pipeline.rooms import _log_room_pins as _log_room_pins
from .pipeline.rooms import _room_map_from_joint_x as _room_map_from_joint_x
from .pipeline.rooms import _rooms_unplaced_count as _rooms_unplaced_count
from .pipeline.rooms import (
    _rooms_with_greedy_fallback as _rooms_with_greedy_fallback,
)
from .pipeline.rooms import _unplaced_from_status as _unplaced_from_status
from .pipeline.rooms import auto_generate_classrooms as auto_generate_classrooms
from .pipeline.rooms import (
    retry_unplaced_days_with_lambda as retry_unplaced_days_with_lambda,
)
from .pipeline.rooms import run_classroom_assignment as run_classroom_assignment

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
        # schedule/mock_classes2.py was renamed to engine/mock_school_generator.py
        import mock_school_generator as mc  # type: ignore

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
        out_path = Path(ws) / "school.pkl"
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
                               students_seed: int = 42,
                               replace_working_hours: bool = True) -> int:
    params = dict(profile=profile, use_optimized=use_optimized,
                  import_curricula=import_curricula,
                  import_classrooms=import_classrooms,
                  import_students=import_students,
                  replace_working_hours=replace_working_hours)
    run_id = create_run("import", f"Import {profile}", profile, params)
    from pathlib import Path
    here = Path(__file__).resolve().parent
    engine_scripts_dir = (here / ".." / ".." / "engine" / "scripts").resolve()

    def _resolve_pkl(filename: str) -> str | None:
        """Locate ``filename`` for the given profile under the
        post-rename ``engine/scripts/data/<profile>/`` and
        ``engine/scripts/output/<profile>/`` subdirs, falling back
        to the flat ``engine/scripts/`` legacy layout."""
        for cand in (
            engine_scripts_dir / "data" / profile / filename,
            engine_scripts_dir / "output" / profile / filename,
            engine_scripts_dir / filename,
        ):
            if os.path.exists(cand):
                return cand
        return None

    def target(rid: int):
        # New default path: load the per-profile SQLite snapshot
        # built by ``webui/backend/scripts/build_profile_db.py``. The
        # snapshot carries anagrafica + the 14 constraint tables +
        # WorkingDay/Slot + Lessons in one file, replacing the slim
        # pickles + the post-import classroom / student / curricula
        # auto-generation.
        sqlite_path = engine_scripts_dir / "data" / profile / f"{profile}.sqlite"
        if os.path.exists(sqlite_path):
            print(f"[import] using SQLite snapshot {sqlite_path}")
            with SessionLocal() as db:
                counts = engine_io.import_profile_sqlite_into_db(
                    db, sqlite_path, replace=True,
                    replace_working_hours=replace_working_hours,
                )
                _set_app_state(db, "last_profile", profile)
            print(f"[import] sqlite import counts: {counts}")
            update_run(rid, progress=1.0, metrics={
                "source": "sqlite", "counts": counts,
            })
            return

        # Fallback (deprecated): legacy pickle path. Kept for users
        # who haven't run ``python -m backend.scripts.build_profile_db
        # <profile>`` yet, or for one-off pickle dumps not yet
        # converted. Logged at INFO so the deprecation is visible.
        print(f"[import] {profile}.sqlite not found; "
              f"falling back to legacy pickle import (deprecated)")
        school_pkl = _resolve_pkl(f"school_{profile}.pkl")
        profs_pkl = _resolve_pkl(f"profs_{profile}.pkl")
        sol_optimized = _resolve_pkl(
            f"solution_timetable_{profile}_optimized.pkl")
        sol_decomposed = _resolve_pkl(
            f"solution_timetable_{profile}_decomposed.pkl")
        sol_plain = _resolve_pkl(f"solution_timetable_{profile}.pkl")
        # MEGA pipeline (run_mega_pipeline.py) emits non-canonical
        # filenames: solution_mega_temporal_alns.pkl is the post-ALNS
        # polished result (the equivalent of *_optimized.pkl), and
        # solution_temporal_mega.pkl is the pre-ALNS temporal-decomposed
        # result (the equivalent of *_decomposed.pkl). Honour these as
        # additional fallbacks before giving up.
        sol_alt_optimized = _resolve_pkl(
            f"solution_{profile}_temporal_alns.pkl")
        sol_alt_decomposed = _resolve_pkl(
            f"solution_temporal_{profile}.pkl")
        if not school_pkl:
            raise FileNotFoundError(
                f"school_{profile}.pkl not found "
                f"(searched engine/scripts/data/{profile}/, "
                f"engine/scripts/output/{profile}/, "
                f"engine/scripts/)"
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

        if profs_pkl:
            with open(profs_pkl, "rb") as f:
                profs = pickle.load(f)
            print(f"[import] loaded {profs_pkl}: {len(profs)} teachers")
            with SessionLocal() as db:
                n = engine_io.import_profs_into_db(db, profs)
                print(f"[import] {n} assignments imported")
        sol_path = None
        if use_optimized and sol_optimized:
            sol_path = sol_optimized
        elif use_optimized and sol_alt_optimized:
            sol_path = sol_alt_optimized
        elif sol_decomposed:
            sol_path = sol_decomposed
        elif sol_alt_decomposed:
            sol_path = sol_alt_decomposed
        elif sol_plain:
            sol_path = sol_plain
        sol = None
        sol_label = None
        if sol_path:
            with open(sol_path, "rb") as f:
                sol = pickle.load(f)
            sol_label = Path(sol_path).name
            print(f"[import] loaded {sol_path}: {len(sol)} cells")
        else:
            # Fallback: rebuild the solution dict from the orario_classi
            # xlsx if it's checked into engine/scripts/output/<profile>/.
            # The mega profile is shipped this way (the canonical pickle
            # is gitignored to keep the repo small, but the xlsx output
            # is tracked so reviewers can read the schedule).
            xlsx_path = _resolve_pkl(f"orario_classi_{profile}.xlsx")
            if xlsx_path:
                try:
                    sol = engine_io.solution_dict_from_class_xlsx(xlsx_path)
                    sol_label = Path(xlsx_path).name + " (xlsx)"
                    print(f"[import] no solution pickle; "
                          f"reconstructed {len(sol)} cells from {xlsx_path}")
                except Exception as e:
                    print(f"[import] xlsx fallback failed: {e}")
                    sol = None
        if sol:
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
                    name=f"Imported {profile} ({sol_label})",
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
        with open(Path(ws) / "cattedre.pkl", "wb") as f:
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
                      teacher_name: str, locked: bool = True,
                      *, target_kind: str = "class",
                      group_name: str | None = None,
                      hours: int | None = None,
                      ) -> tuple[bool, str, models.Assignment | None]:
    """Create/replace an Assignment for a (target, subject) pair.

    Task C3: target_kind='group' creates a group-targeted Assignment
    (Assignment.group_id set, class_id=None). Hours come from the
    explicit `hours` parameter (group-target Assignments don't go
    through ClassSubject); the caller is responsible for matching
    the StudyGroup's subject_hours."""
    if target_kind == "group":
        if not group_name:
            return False, "target_kind=group richiede group_name", None
        if hours is None or hours <= 0:
            return (False,
                    "target_kind=group richiede hours > 0", None)
        g = db.query(models.StudyGroup).filter(
            models.StudyGroup.name == group_name
        ).first()
        if g is None:
            return (False,
                    f"Gruppo {group_name} inesistente", None)
        t = db.query(models.Teacher).filter(
            models.Teacher.name == teacher_name
        ).first()
        if t is None:
            return False, f"Docente {teacher_name} inesistente", None
        teacher_subjects = {ts.subject for ts in t.subjects}
        if teacher_subjects and subject not in teacher_subjects:
            return (False,
                    f"Il docente {teacher_name} non insegna "
                    f"{subject}", None)
        existing = db.query(models.Assignment).filter(
            models.Assignment.group_id == g.id,
            models.Assignment.teacher_id == t.id,
            models.Assignment.subject == subject,
        ).first()
        if existing is not None:
            existing.hours = int(hours)
            existing.locked = locked
            new = existing
        else:
            new = models.Assignment(
                class_id=None, group_id=g.id, teacher_id=t.id,
                subject=subject, hours=int(hours),
                locked=locked,
            )
            db.add(new)
        db.commit()
        return True, "ok", new
    # Default: target_kind='class'
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
    # Finding 12: for a class target the weekly hours come from the
    # curriculum (ClassSubject). Silently ignoring a conflicting `hours`
    # let the API accept one number and use another. Reject the mismatch
    # instead of hiding it; a matching or omitted value passes through.
    if hours is not None and int(hours) != int(csubj.hours_per_week):
        return (False,
                f"Le ore di {subject} in {class_name} vengono dal curricolo "
                f"({csubj.hours_per_week}h); il parametro hours={int(hours)} "
                f"e' incoerente. Rimuovilo o correggi il monte ore della "
                f"classe.", None)
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
    # Replace existing. Support rows are excluded on purpose: this
    # endpoint means "whoever teaches (class, subject), it's now this
    # teacher", and a sostegno cattedra is nobody's subject -- letting
    # it match here would silently hand a pupil's support teacher's
    # hours to somebody else. Sostegno goes through
    # `sostegno_assignment`.
    existing = db.query(models.Assignment).filter(
        models.Assignment.class_id == cl.id,
        models.Assignment.subject == subject,
        models.Assignment.is_support == False,  # noqa: E712
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


def sostegno_assignment(db: Session, teacher_name: str, student_id: int,
                        hours: int, *, locked: bool = True
                        ) -> tuple[bool, str, models.Assignment | None]:
    """Create/replace the sostegno cattedra of `teacher_name` on one
    pupil.

    Deliberately NOT a special case of `manual_assignment`: that one
    insists on a ClassSubject row for the subject and on the teacher
    declaring they teach it. Neither applies here. A support teacher
    doesn't teach a subject and no class has "sostegno" among its
    weekly hours, so requiring either would force every school to
    invent a fake Subject just to hire a docente di sostegno.

    `class_id` is filled in from the pupil's class -- it is a cache of
    the pupil's whereabouts, re-derived at solve time by
    `engine_io.support_class_id`, not an independent piece of data.
    """
    if hours is None or hours <= 0:
        return False, "Il sostegno richiede ore > 0", None
    t = db.query(models.Teacher).filter(
        models.Teacher.name == teacher_name
    ).first()
    if t is None:
        return False, f"Docente {teacher_name} inesistente", None
    st = db.get(models.Student, student_id)
    if st is None:
        return False, f"Alunno #{student_id} inesistente", None
    if st.class_id is None:
        return (False,
                f"L'alunno {st.last_name} {st.first_name} non ha una "
                f"classe: non ci sono lezioni da seguire", None)
    existing = db.query(models.Assignment).filter(
        models.Assignment.teacher_id == t.id,
        models.Assignment.student_id == st.id,
        models.Assignment.is_support == True,  # noqa: E712
    ).first()
    if existing is not None:
        existing.class_id = st.class_id
        existing.hours = int(hours)
        existing.locked = locked
        new = existing
    else:
        new = models.Assignment(
            teacher_id=t.id, student_id=st.id, class_id=st.class_id,
            subject=models.SUPPORT_SUBJECT, hours=int(hours),
            is_support=True, locked=locked,
        )
        db.add(new)
    db.commit()
    return True, "ok", new


def _norm_joint_vars(jv: dict | None) -> dict | None:
    r"""Normalize the API's joint-vars selection into the internal shape,
    or ``None`` when joint room optimization is off (so every existing
    call path stays byte-identical). The UI ships two sections -- decision
    blocks and objective terms; here only ``room`` (joint on/off) and the
    per-term toggles matter, and unknown/absent keys default to ON.

    Returns ``{"exclude": set, "obj_home_room": bool, ...}`` where
    ``exclude`` are the schedule-side objective terms to drop
    (``sixth`` / ``buchi`` / ``day_load``) and ``obj_*`` gate the
    room-side objective terms fed to ``add_joint_room_vars``.
    """
    if not jv or not jv.get("enabled"):
        return None
    obj = jv.get("obj") or {}
    cont = jv.get("room_continuity") or "none"
    if cont not in ("none", "day", "week", "soft"):
        cont = "none"
    return {
        "enabled": True,
        "room_continuity": cont,
        "obj_home_room": bool(obj.get("home_room", True)),
        "obj_room_pref": bool(obj.get("room_pref", True)),
        "obj_special_overflow": bool(obj.get("special_overflow", True)),
        "obj_plessi": bool(obj.get("plessi", True)),
        # sorted list (not a set): this dict lands in the run's params
        # which are json.dumps'd by create_run; consumers use `in` / set(),
        # both fine on a list.
        "exclude": sorted(
            name for name in ("sixth", "buchi", "day_load")
            if not obj.get(name, True)
        ),
    }


def _add_joint_rooms(model, slot, ctx: dict, jv: dict, *, plessi_data=None):
    r"""Fold room vars into an existing week ``slot`` model (joint). Builds
    per-cell occupancy indicators from the slot vars, then calls
    ``classroom_assignment.add_joint_room_vars``. Returns
    ``(x, obj_terms, info)``; ``obj_terms`` are folded into the schedule
    objective so the room soft goals influence WHERE lessons land.
    """
    try:
        import classroom_assignment as ca  # type: ignore
    except ImportError:
        from engine import classroom_assignment as ca  # type: ignore
    cell_to_keys, cell_lessons = engine_io.joint_cells_from_slot_keys(
        slot.keys(), ctx)
    cell_occ: dict = {}
    for cell, keys in cell_to_keys.items():
        vars_ = [slot[k] for k in keys]
        if len(vars_) == 1:
            cell_occ[cell] = vars_[0]
        else:
            # OR indicator: occ == 1 iff any co-teacher slot is placed.
            occ = model.NewBoolVar(f"jocc_{cell[0]}_{cell[1]}_{cell[2]}_{cell[3]}")
            for v in vars_:
                model.Add(occ >= v)
            model.Add(occ <= sum(vars_))
            cell_occ[cell] = occ
    x, obj_terms, info = ca.add_joint_room_vars(
        model, cell_occ, cell_lessons, ctx["classrooms"],
        plessi_data=plessi_data,
        candidate_rooms=ctx.get("candidate_rooms"),
        want_home_bonus=jv["obj_home_room"],
        want_room_pref=jv["obj_room_pref"],
        want_overflow=jv["obj_special_overflow"],
        want_plessi=jv["obj_plessi"],
    )

    # Room-continuity (Stage 3): a global mode from the joint-vars picker,
    # overlaid with per-class pragmas from the general DSL / stored presets.
    # A pinned class (room_policy='fissa' / enforced) is already single-room
    # HARD via _can_host, so the GLOBAL mode skips it; a per-class pragma
    # still wins where it is explicitly named.
    modes: dict = {}
    g = (jv.get("room_continuity") or "none")
    if g != "none":
        pinned = set(ctx.get("home_by_class") or {})
        for (cl, _s, _d, _h) in cell_lessons:
            if cl not in pinned:
                modes[cl] = g
    for cl, mode in (ctx.get("continuity_dsl") or {}).items():
        modes[cl] = mode  # explicit per-class pragma overrides the global
    if modes:
        cont_terms = ca.add_room_continuity_constraints(
            model, x, cell_lessons, modes)
        obj_terms = list(obj_terms) + list(cont_terms)
        info["continuity_classes"] = len(modes)
    return x, obj_terms, info


# ----------------------------------------------------------------------
# Step 3: Phase B (decomposed) — uses decomposition_spectral_v2
# ----------------------------------------------------------------------


def run_phase_b(k: int, time_a: float, time_bridges: float,
                time_cluster: float, time_ricucitura: float,
                time_mono: float, workers: int, log: bool,
                use_decomposition: bool = True,
                optimize_rooms: bool = False,
                rooms_time_limit_s: float = 30.0,
                rooms_prefer_home: bool = True,
                cp_sat_scope: str = "day",
                phase_a_mode: str = "always",
                respect_room_capacity: bool = False,
                thoroughness: str = "balanced",
                joint_vars: dict | None = None) -> int:
    # Phase 3 -- enforce the same (cp_sat_scope, phase_a_mode)
    # cross-field rules as PhaseBRunIn so direct callers (full
    # pipeline, programmatic harness, tests) get the same guard. The
    # router validator catches API usage; this catches everything
    # else.
    if cp_sat_scope not in ("day", "week"):
        raise ValueError(
            f"cp_sat_scope must be 'day' or 'week', got {cp_sat_scope!r}")
    if phase_a_mode not in ("always", "skip", "soft_hint"):
        raise ValueError(
            f"phase_a_mode must be 'always' / 'skip' / 'soft_hint', "
            f"got {phase_a_mode!r}")
    # Joint (day,hour,room): room vars are a GLOBAL per-slot resource that
    # does not decompose along the teacher partition, so joint optimization
    # is coherent only on the monolithic WEEK path (same reason special-room
    # capacity lives there, never in the spectral stages). Enabling it forces
    # week scope + no decomposition, and turns on the rooms extraction step
    # (the joint coupling guarantees that step now succeeds for every lesson).
    _jv = _norm_joint_vars(joint_vars)
    if _jv is not None:
        # Optimizing rooms + schedule TOGETHER (joint model) vs. as separate
        # steps is the USER's choice from the UI, not something to override
        # silently. The joint room vars (~rooms x cells) are heavier at scale
        # (verified fine at 60 classes, can go UNKNOWN around 90 on the
        # monolithic week path), but that is a trade-off the user opts into --
        # keep it on and only WARN. ``PITANTUM_JOINT_MAX_CLASSES`` remains as
        # an OPTIONAL ops ceiling for headless/batch runs; UNSET (the default)
        # means NO cap, so an explicit UI request is always honoured.
        try:
            with SessionLocal() as _db_n:
                _n_classes = _db_n.query(models.SchoolClass).count()
        except Exception:  # noqa: BLE001
            _n_classes = 0
        _cap_env = os.environ.get("PITANTUM_JOINT_MAX_CLASSES")
        _joint_cap = (int(_cap_env) if (_cap_env and _cap_env.strip())
                      else None)
        if _joint_cap is not None and _n_classes > _joint_cap:
            print(f"[phase_b] joint rooms disattivato dal tetto esplicito "
                  f"PITANTUM_JOINT_MAX_CLASSES={_joint_cap} "
                  f"({_n_classes} classi); uso il week classico + "
                  f"assegnazione aule esatta separata")
            _jv = None
        elif _n_classes > 75:
            print(f"[phase_b] joint rooms ATTIVO su {_n_classes} classi "
                  f"(scelta utente): il modello congiunto e' piu' pesante a "
                  f"questa scala; imposta PITANTUM_JOINT_MAX_CLASSES per un "
                  f"tetto di sicurezza.")
    if _jv is not None:
        if cp_sat_scope != "week":
            print("[phase_b] joint rooms richiede scope settimanale: "
                  "forzo cp_sat_scope='week'")
            cp_sat_scope = "week"
        if phase_a_mode == "always":
            phase_a_mode = "soft_hint"
        use_decomposition = False
        optimize_rooms = True
    elif joint_vars is not None and (joint_vars or {}).get("enabled"):
        # Joint was requested but auto-disabled above: still give the caller
        # the scalable equivalent -- classic week solve + separate exact rooms.
        if cp_sat_scope != "week":
            cp_sat_scope = "week"
        if phase_a_mode == "always":
            phase_a_mode = "soft_hint"
        use_decomposition = False
        optimize_rooms = True
    if cp_sat_scope == "day" and phase_a_mode != "always":
        raise ValueError(
            "cp_sat_scope='day' requires phase_a_mode='always'")
    if cp_sat_scope == "week" and phase_a_mode == "always":
        raise ValueError(
            "cp_sat_scope='week' is incompatible with "
            "phase_a_mode='always'; use 'skip' or 'soft_hint'")
    params = dict(k=k, time_a=time_a, time_bridges=time_bridges,
                  time_cluster=time_cluster, time_ricucitura=time_ricucitura,
                  time_mono=time_mono, workers=workers, log=log,
                  use_decomposition=use_decomposition,
                  optimize_rooms=optimize_rooms,
                  rooms_time_limit_s=rooms_time_limit_s,
                  rooms_prefer_home=rooms_prefer_home,
                  cp_sat_scope=cp_sat_scope,
                  phase_a_mode=phase_a_mode,
                  respect_room_capacity=respect_room_capacity,
                  joint_vars=_jv)
    _preflight_lock_check()
    run_id = create_run("phase_b", "Schedulazione orario", None, params)

    def target(rid: int):
        # Read locked Lessons BEFORE running anything. Every CP-SAT path
        # -- monolithic week, monolithic per-day, and the decomposed
        # spectral stages (A/B/C + ricucitura + day fallback) -- feeds
        # them to the solver as native hard constraints (slot var == 1
        # per locked (p,c,s,d,h), plus lock-floors in Phase A). There is
        # no snapshot/restore; `_read_locked_lessons` only READS the
        # current locked set, and `_apply_locked_classrooms` below only
        # re-decorates room metadata onto the lessons the solver placed.
        with SessionLocal() as db:
            locked_snap = _read_locked_lessons(db)
            profs = engine_io.profs_dict_from_db(db)
            coteach_groups = engine_io.coteach_groups_for_solver(db)
            support_assignments = engine_io.support_assignments_from_db(db)
            potenziamento_assignments = (
                engine_io.potenziamento_assignments_from_db(db))
            parallel_groups = engine_io.parallel_groups_for_solver(db)
            group_assignments = engine_io.group_assignments_for_solver(db)
        if locked_snap:
            print(f"[phaseB] {len(locked_snap)} locked lessons "
                  f"(native CP-SAT path, "
                  f"{'decomposed' if use_decomposition else 'monolithic'})")
        if coteach_groups:
            print(f"[phaseB] {len(coteach_groups)} coteach groups "
                  f"(shared mode)")
            # Soft coteach (required=False) is applied as a weighted SOFT
            # term via the DSL objective on the DSL-engaged paths (the
            # weekly solver loads it through _apply_dsl_rules_to_week_solver;
            # the per-day monolithic path only when hard DSL rules are also
            # present). The NATIVE hardcoded per-day/decomposition path does
            # not model it. Say so instead of pretending either extreme
            # (finding 38): it is a preference, honoured where the DSL runs.
            n_soft = sum(1 for g in coteach_groups if not g.get("required"))
            if n_soft:
                print(f"[phaseB] {n_soft} compresenze 'preferibili' (soft): "
                      f"applicate come preferenza pesata dal livello DSL "
                      f"(garantite sullo scope 'week'); la decomposizione "
                      f"per giorno potrebbe non considerarle. Per un obbligo "
                      f"pieno impostale come 'obbligatorie'.")
        if support_assignments:
            print(f"[phaseB] {len(support_assignments)} support "
                  f"(sostegno) assignments")
        if potenziamento_assignments:
            print(f"[phaseB] {len(potenziamento_assignments)} "
                  f"potenziamento assignments")
        if parallel_groups:
            print(f"[phaseB] {len(parallel_groups)} parallel groups "
                  f"(intra-class)")
        if group_assignments:
            print(f"[phaseB] {len(group_assignments)} group "
                  f"assignments (inter-class StudyGroup)")
        if not profs:
            raise RuntimeError(
                "Nessun assegnamento prof->classe; esegui prima "
                "l'assegnazione (step 2)."
            )
        ws = _run_workspace(rid)
        with open(Path(ws) / "profs.pkl", "wb") as f:
            pickle.dump(profs, f)

        import cpsat_v2_timetable as cv2  # type: ignore
        import metaheuristics as meta  # type: ignore
        classes, triples, class_profs = cv2.build_indices(profs)
        print(f"[phaseB] {len(profs)} profs, {len(classes)} classes, "
              f"{len(triples)} triples")
        print(f"[phaseB] cp_sat_scope={cp_sat_scope!r} "
              f"phase_a_mode={phase_a_mode!r}")
        # Finding 19: name the current activity so the Runs UI stops
        # showing a frozen bar with no step. The frontend maps these keys
        # via pipeline_labels.js (unknown keys fall back to the raw text).
        update_run(rid, progress=0.05, current_step="phase_a")
        # Phase A inside the timetable: day_count. Native locks are
        # passed both on the monolithic and on the decomposed path
        # (decomposed forwards them to the 4 stages below).
        locked_dc = _locked_day_count_from_snapshot(locked_snap)
        locked_by_day = _locked_slots_by_day(locked_snap)
        # Bound on BOTH paths: only the ``day`` branch below computes a
        # real day-count. On the ``week`` path the day distribution is a
        # CP-SAT decision, so there is no dc_value to gate against --
        # ``_gate_coverage`` treats ``None`` as "total unknown" and skips.
        # That is sound here: ``_solve_phase_b_week`` raises on anything
        # other than OPTIMAL/FEASIBLE, and the week model carries the
        # per-cattedra weekly hours equality as a HARD constraint, so a
        # returned solution is complete by construction. Without this
        # initialisation the week path raised UnboundLocalError at the
        # ``_gate_coverage`` call and discarded a fully solved timetable.
        dc_value: dict | None = None
        _joint_room_map: dict | None = None
        if cp_sat_scope == "week":
            full_solution, _joint_room_map = _solve_phase_b_week(
                rid=rid, ws=ws, profs=profs, classes=classes,
                triples=triples, class_profs=class_profs,
                phase_a_mode=phase_a_mode,
                time_a=time_a, time_mono=time_mono,
                workers=workers, log=log,
                locked_dc=locked_dc,
                locked_by_day=locked_by_day,
                coteach_groups=coteach_groups,
                support_assignments=support_assignments,
                potenziamento_assignments=potenziamento_assignments,
                parallel_groups=parallel_groups,
                group_assignments=group_assignments,
                joint_vars=_jv,
            )
            update_run(rid, progress=0.90, current_step="phase_b")
        else:
            # 08b: per-class flags for Phase A's day_count pragmas too
            # (motorie 0/2-per-day, Mat/Ita, day-load), so the class-card
            # toggles are consistent from the day distribution onward.
            with SessionLocal() as _db_pa:
                _pa_class_flags = engine_io.class_flags_from_db(_db_pa)
                _pa_cdl = engine_io.class_day_load_allowed_from_db(_db_pa)
                _pa_cfd = engine_io.class_free_days_from_db(_db_pa)
            # Build special-room ctx BEFORE Phase A so it can enforce
            # per-day capacity caps on gym/lab subjects at day-count level.
            try:
                with SessionLocal() as _db_sr:
                    _sr_ctx = cv2.build_special_room_ctx(_db_sr)
            except Exception:
                _sr_ctx = None
            dc_value = cv2.solve_phase_a(
                profs, classes, triples, class_profs,
                time_limit=time_a, workers=workers, log=log,
                locked_day_count=locked_dc or None,
                coteach_groups=coteach_groups or None,
                support_assignments=support_assignments or None,
                potenziamento_assignments=potenziamento_assignments or None,
                parallel_groups=parallel_groups or None,
                group_assignments=group_assignments or None,
                class_flags=_pa_class_flags,
                class_day_load_allowed=_pa_cdl,
                class_free_days=_pa_cfd,
                thoroughness=thoroughness,
                special_room_ctx=_sr_ctx,
            )
            with open(Path(ws) / "phase_a_dc.pkl", "wb") as f:
                pickle.dump(dc_value, f)
            update_run(rid, progress=0.20, current_step="phase_b")

            full_solution = {}
            # Task C3: spectral stages A/B/C don't model group_slot
            # vars. When group_assignments are present, force the
            # per-day monolithic path so groups are scheduled
            # correctly. The overall run still benefits from the
            # cached `dc_value` from Phase A above.
            # Plessi: costruito una volta per run e passato a ogni stage.
            # E' None quando la scuola non ha plessi configurati (caso
            # normale), e allora nulla cambia rispetto a prima.
            try:
                with SessionLocal() as _db_p:
                    _plessi_ctx = cv2.build_plessi_ctx(_db_p)
            except Exception:
                _plessi_ctx = None
            if _plessi_ctx:
                print(f"[phase_b] plessi attivi: "
                      f"{len(_plessi_ctx[1])} classi con sede nota")
            # Special-room (gym/lab) capacity (finding 34). Built once.
            # Also passed to Phase A so it distributes special-room
            # lessons across days respecting per-day capacity (e.g.
            # max 6 concurrent PE classes × 6 hours = 36 PE-hours/day).
            try:
                with SessionLocal() as _db_sr:
                    _special_room_ctx = cv2.build_special_room_ctx(_db_sr)
            except Exception:
                _special_room_ctx = None
            # Per-class overrides of the ex-officio HARD invariants (08b).
            try:
                with SessionLocal() as _db_cf:
                    _class_flags = engine_io.class_flags_from_db(_db_cf)
            except Exception:
                _class_flags = None
            if _special_room_ctx:
                print(f"[phase_b] aule speciali: capienza per kind "
                      f"{_special_room_ctx[1]}")
            # Per-slot GENERAL room capacity (option A): cap the number of
            # distinct classes in session in the same (day, hour) at the total
            # room count, so the schedule itself is room-feasible per slot and
            # the room step can seat everyone. Opt-in via respect_room_capacity;
            # None -> off (byte-identical). Like the special-room cap it is a
            # GLOBAL per-slot rule the spectral stages can't see, so it forces
            # the monolithic per-day path below.
            _total_room_capacity = None
            if respect_room_capacity:
                # Count of STANDARD (ordinary) rooms: the per-slot cap bounds
                # only the ordinary load, since required-kind lessons sit in
                # their lab/gym (see solve_phase_b_for_day, which excludes them
                # via the special-room subj_kind map). This is what lets a
                # class in the gym free its ordinary seat -> rooms < classes.
                try:
                    with SessionLocal() as _db_rc:
                        # Standard rooms = rooms that host exactly 1 class
                        # (multi_class_max <= 1). Special rooms (palestra
                        # with multi_class_max=2) are counted separately
                        # via build_special_room_ctx and excluded here.
                        # This works for any kind label: 'standard',
                        # 'area_*', etc. — the distinguishing factor is
                        # whether the room supports multi-class sharing.
                        _total_room_capacity = (
                            _db_rc.query(models.Classroom)
                            .filter(models.Classroom.multi_class_max <= 1)
                            .count() or None)
                except Exception:
                    _total_room_capacity = None
                if _total_room_capacity:
                    print(f"[phase_b] capienza aule standard attiva: "
                          f"{_total_room_capacity}")
            # HARD DSL rule expression strings, loaded ONCE (used both to
            # force the monolithic per-day path below and to feed its
            # verify + no-good gate). None => no hard DSL => zero drift.
            try:
                with SessionLocal() as _db_h:
                    _dsl_hard = _load_dsl_hard_expressions(_db_h)
            except Exception:
                _dsl_hard = None
            # Audit H8/H10: the spectral stages model NONE of special-room
            # capacity, plessi commuting, coteach, sostegno or intra-class
            # parallel (disjoint class subsets can't see a global per-slot cap
            # or a shared-teacher rule). When any is present, fall back to the
            # monolithic per-day path (which does model them) instead of only
            # warning and shipping a violation the validator then rejects.
            # Audit H6: a HARD DSL rule the CP compiler cannot emit is only
            # enforced (verify + no-good) on the monolithic per-day path, so
            # its presence also forces monolithic -- the spectral stages
            # would silently ship a timetable that violates it.
            _needs_mono = (bool(_special_room_ctx) or bool(_plessi_ctx)
                           or bool(_total_room_capacity)
                           or bool(coteach_groups)
                           or bool(support_assignments)
                           or bool(parallel_groups)
                           or bool(_dsl_hard))
            if _needs_mono and use_decomposition and len(classes) >= 8:
                print("[phase_b] decomposizione spettrale disattivata: "
                      "aule speciali / plessi / coteach / sostegno / parallel "
                      "/ HARD DSL non decomponibili per cluster "
                      "-> per-day monolitico")

            if (use_decomposition and len(classes) >= 8
                    and not group_assignments and not _needs_mono):
                import decomposition_spectral_v2 as dec  # type: ignore
                M, classes_v, _ = dec.build_adjacency(profs)
                labels, _ = dec.spectral_cluster(M, k)
                bridges, cl_to_label = dec.find_bridges(
                    profs, classes_v, labels)
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
                        plessi_ctx=_plessi_ctx,
                        class_flags=_class_flags,
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
                    raise_if_cancelled(rid)
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
                            plessi_ctx=_plessi_ctx,
                            class_flags=_class_flags,
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
                        plessi_ctx=_plessi_ctx,
                        class_flags=_class_flags,
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
                        plessi_ctx=_plessi_ctx,
                        special_room_ctx=_special_room_ctx,
                        class_flags=_class_flags,
                        total_room_capacity=_total_room_capacity,
                    )
                    if out is not None:
                        full_solution = {
                            kk: vv for kk, vv in full_solution.items()
                            if kk[3] != d
                        }
                        full_solution.update(out)
            else:
                # monolithic per day -- locks + coteach + sostegno + parallel.
                # Per-day DSL: enforce DB HARD rules the single-day CP can
                # model; cross-day / unsupported rules are skipped with a
                # diagnostic and delegated to the metaheuristic post-pass.
                # When there are no HARD DSL rules ``via_dsl`` stays False and
                # the call is byte-identical to the pre-wiring path (zero
                # drift on non-DSL runs). ``_dsl_hard`` was loaded once above.
                _dsl_sink: list[str] = []
                _prev_day = None
                _prev_out = None
                import decomposition_temporal as _dec_t  # type: ignore
                for d in DAYS:
                    raise_if_cancelled(rid)
                    out, status = cv2.solve_phase_b_for_day(
                        d, profs, classes, triples, class_profs, dc_value,
                        time_limit=time_mono, workers=workers, log=log,
                        locked_slots_for_day=locked_by_day.get(d, []),
                        coteach_groups=coteach_groups or None,
                        support_assignments=support_assignments or None,
                        parallel_groups=parallel_groups or None,
                        group_assignments=group_assignments or None,
                        via_dsl=bool(_dsl_hard),
                        dsl_hard_expressions=_dsl_hard or None,
                        plessi_ctx=_plessi_ctx,
                        special_room_ctx=_special_room_ctx,
                        class_flags=_class_flags,
                        total_room_capacity=_total_room_capacity,
                        diagnostics_sink=_dsl_sink,
                        warm_start=_dec_t.hint_from_day(_prev_out, d),
                    )
                    if out is None and _prev_out is not None:
                        print(f"[phaseB] giorno {d} INFEASIBLE; "
                              f"2-day F&O con giorno {_prev_day}")
                        _new_prev, out = _dec_t.fix_and_optimize_two_days(
                            _prev_day, d, profs, dc_value, _prev_out,
                            time_limit=time_mono, workers=workers,
                            locked_by_day=locked_by_day,
                            coteach_groups=coteach_groups or None,
                            support_assignments=support_assignments or None,
                            parallel_groups=parallel_groups or None,
                            group_assignments=group_assignments or None,
                            special_room_ctx=_special_room_ctx,
                            class_flags=_class_flags,
                            total_room_capacity=_total_room_capacity,
                            plessi_ctx=_plessi_ctx,
                            dsl_hard_expressions=_dsl_hard or None,
                        )
                        if _new_prev is not None and _new_prev is not _prev_out:
                            for _k in list(full_solution):
                                if len(_k) == 5 and _k[3] == _prev_day:
                                    del full_solution[_k]
                            full_solution.update(_new_prev)
                            _prev_out = _new_prev
                    if out is None:
                        _expl = _dec_t.explain_day_infeasibility(
                            profs, dc_value, d)
                        _why = _dec_t.format_infeasibility(_expl)
                        if locked_by_day.get(d):
                            raise RuntimeError(
                                f"Phase B (giorno {d}) INFEASIBLE: i lock di "
                                f"quel giorno sono incompatibili con i vincoli "
                                f"correnti.{_why} Rimuovi o adatta lock e "
                                "ritenta."
                            )
                        print(f"[phaseB] giorno {d} INFEASIBLE.{_why}")
                    if out is not None:
                        full_solution.update(out)
                        _prev_day, _prev_out = d, out
                # Surface what the per-day CP could not enforce (RunLog).
                for _ln in _per_day_dsl_warning_lines(_dsl_sink):
                    print(_ln)

        with open(Path(ws) / "solution.pkl", "wb") as f:
            pickle.dump(full_solution, f)

        v, m = meta.compute_soft(full_solution, profs)
        feasible = meta.is_hard_feasible(full_solution, profs, verbose=False,
                                         **_hard_check_ctx_fresh())
        # Coverage + which cattedre are (partly) unplaced.
        cov = _coverage_ratio(full_solution, dc_value)
        if cov is not None:
            m["coverage"] = round(cov, 4)
        complete = cov is None or cov >= 0.999
        uncovered = _uncovered_report(full_solution, dc_value)
        if uncovered:
            m["uncovered_count"] = sum(u["missing"] for u in uncovered)
            m["uncovered"] = uncovered[:50]
        # Findings 17 + 24: ALWAYS save the timetable (so a partial can be
        # inspected instead of thrown away), but ACTIVATE it only when it is
        # both complete AND hard-feasible. A silently-activated partial or a
        # timetable the validator rejects is exactly what the audit flagged.
        make_active = bool(feasible and complete)
        with SessionLocal() as db:
            sid = engine_io.import_solution_into_db(
                db, full_solution,
                name=f"Phase B run {rid}"
                     + ("" if make_active else " (parziale / non valido)"),
                kind="phase_b",
                obj_value=float(v),
                metrics={**m, "feasible": feasible},
                make_active=make_active,
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
        # No point assigning rooms to a timetable we won't activate.
        if optimize_rooms and make_active:
            update_run(rid, progress=0.95, current_step="rooms")
            print("[phaseB] running classroom-assignment step")
            try:
                # Joint runs: write the joint week solve's OWN room assignment
                # (captured from its room vars) so the joint room objective
                # (home / continuity) reaches the output. Fall back to the
                # standalone solver+greedy only if that map is missing or can't
                # cover every lesson.
                rooms_metrics = {}
                if _jv is not None and _joint_room_map:
                    rooms_metrics = _apply_joint_room_map(
                        sid, _joint_room_map, log_prefix="phaseB.rooms") or {}
                if not rooms_metrics or rooms_metrics.get("rooms_joint") is not True:
                    rooms_metrics = _apply_rooms_to_solution(
                        sid, time_limit_s=rooms_time_limit_s,
                        workers=workers, prefer_home=rooms_prefer_home,
                        log_prefix="phaseB.rooms", log=False,
                    )
                if rooms_metrics.get("rooms_unplaced"):
                    rooms_metrics = retry_unplaced_days_with_lambda(
                        sid, rooms_metrics,
                        time_limit_s=rooms_time_limit_s,
                        workers=workers, prefer_home=rooms_prefer_home,
                        log_prefix="phaseB.rooms")
            except Exception as e:  # noqa: BLE001
                print(f"[phaseB] rooms step failed: {e}")
                rooms_metrics = {"rooms_error": str(e)}
        update_run(rid, solution_id=sid, obj_value=float(v),
                   metrics={**m, "feasible": feasible,
                            "activated": make_active, **rooms_metrics},
                   progress=1.0, current_step=None)
        print(f"[phaseB] solution id={sid} obj={v} active={make_active} "
              f"feasible={feasible} metrics={m} rooms={rooms_metrics}")
        # P0 truthfulness (finding 17): a strict, INCOMPLETE run still fails
        # so it never reads as success -- but the partial is already saved
        # above (id=sid, non-active) for inspection, and the message names
        # the worst-uncovered cattedre instead of only a percentage and a
        # misleading "raise the time limit".
        if not complete and _coverage_strict():
            top = "; ".join(
                f"{u['class']}/{u['subject']} g{u['day']} -{u['missing']}h"
                for u in uncovered[:6])
            raise RuntimeError(
                f"phase_b: coverage {(cov or 0) * 100:.1f}% < 100% -- "
                f"{m.get('uncovered_count', 0)} ore non collocate. Orario "
                f"salvato (id={sid}) per ispezione ma NON attivato. "
                f"Cattedre piu' scoperte: {top or 'n/d'}. Se e' strutturale "
                f"(vedi hall-check / preflight) nessun aumento di tempo lo "
                f"risolve: allenta i vincoli o correggi i dati."
            )

    start_thread(run_id, target)
    return run_id


def _apply_dsl_rules_to_week_solver(solver, db, *,
                                    level: str = "phase_b") -> int:
    """Load the unified DSL constraint stream (HARD + SOFT) from the DB
    and compile it onto a week-scope ``MonolithicSolver``.

    SOFT rows are forwarded with ``is_hard=False`` and their weight so
    they land on ``solver.dsl_soft_cost_terms`` and -- via
    ``MonolithicSolver.build`` -- the objective. This is
    double-count-safe on the week path: ``compute_soft_cost_expr``
    carries only sixth/buchi/five/one penalties (no free-day or
    unavailability soft), so these SOFT rows are not otherwise present
    in the objective. Returns the number of rules applied.

    NOTE: this helper wires SOFT onto the week-scope ``MonolithicSolver``.
    The per-day path enables the same table SOFT independently inside
    ``cpsat_v2_timetable.solve_phase_b_for_day(via_dsl=True)``, which loads
    the unified stream with ``include_soft=True``, forwards each rule's
    ``is_hard``/``weight`` to its shared compiler, and re-minimizes the
    accumulated ``soft_cost_terms`` (sub-project B2). The dead Phase-A
    ``glib_pen`` term was removed; free-day soft is loader-owned, applied
    at Phase B on both paths.
    """
    try:
        from engine import dsl_translator as dt  # type: ignore
    except ImportError:
        import dsl_translator as dt  # type: ignore
    rules = dt.load_all_dsl_constraints(db, _models=models, include_soft=True)
    for r in rules:
        solver.add_dsl_constraint(
            r["expression"],
            is_hard=bool(r.get("is_hard", True)),
            soft_weight=int(r.get("weight", 0) or 0),
            level=level,
        )
    return len(rules)


class _ProgressCallback(cp_model.CpSolverSolutionCallback):
    """CP-SAT solution callback that advances the run's progress bar DURING
    a long solve (finding 19). The monolithic week solve is a single
    ``Solve`` that can run for the whole time budget; without a callback the
    bar sits frozen at the phase's start. On each improving solution this
    nudges progress within ``[base, base+span]`` as a function of elapsed
    time vs. the limit, and records the current objective. DB writes are
    throttled to at most once per ``min_interval`` seconds so the callback
    never becomes the bottleneck of the search.

    ``base``/``span`` MUST describe the window the caller's own progress
    scheme has reserved for this solve -- they are not a property of the
    solve. ``run_phase_b`` gives it 0.30..0.88; ``run_full_pipeline``
    gives it one slice of ``i/n_steps``. Hard-coding the former made the
    bar leap forward and then fall back on the pipeline path.

    It also doubles as the cancel hook: CP-SAT does not poll anything, so
    a cancel requested during a long ``Solve`` had to wait out the whole
    time budget. This is the only place inside the solve where we get
    control, so it checks and calls ``StopSearch()``. That ends the solve
    early with whatever it has; the orchestration's own
    ``raise_if_cancelled`` at the next boundary is what actually marks
    the run cancelled.
    """

    def __init__(self, rid: int, *, base: float, span: float,
                 time_limit: float, step: str = "phase_b",
                 min_interval: float = 1.2):
        super().__init__()
        self._rid = rid
        self._base = float(base)
        self._span = float(span)
        self._limit = max(1e-6, float(time_limit))
        self._step = step
        self._min_interval = float(min_interval)
        self._last_emit = -1e9
        self._n = 0

    def on_solution_callback(self) -> None:
        self._n += 1
        t = self.WallTime()
        if is_cancel_requested(self._rid):
            self.StopSearch()
            return
        if t - self._last_emit < self._min_interval:
            return
        self._last_emit = t
        # Monotone, bounded fraction: never reaches base+span (the solve's
        # own completion drives the milestone jump to the next step).
        # Progress + current_step only: update_run OVERWRITES metrics_json,
        # so touching metrics here would clobber whatever the run set before
        # the solve -- the finding-19 ask is bar MOVEMENT, nothing else.
        frac = self._base + self._span * min(0.98, t / self._limit)
        # Clamp to the caller's band lower bound: rounding a fraction that
        # sits right at ``base`` (t ~ 0 on the first incumbent) can dip
        # below it (round(2/6, 3) = 0.333 < 0.3333), which would show the
        # bar stepping backwards off the band the caller reserved.
        progress = max(self._base, round(frac, 3))
        try:
            update_run(self._rid, progress=progress,
                       current_step=self._step)
        except Exception:  # noqa: BLE001 - progress is best-effort, never fatal
            pass


def _solve_phase_b_week(*, rid: int, ws: str, profs: dict,
                          classes: list, triples: list,
                          class_profs: dict,
                          phase_a_mode: str,
                          time_a: float, time_mono: float,
                          workers: int, log: bool,
                          locked_dc: dict | None,
                          locked_by_day: dict,
                          coteach_groups: list | None,
                          support_assignments: list | None,
                          potenziamento_assignments: list | None,
                          parallel_groups: list | None,
                          group_assignments: list | None,
                          joint_vars: dict | None = None,
                          progress_base: float = 0.30,
                          progress_span: float = 0.58) -> dict:
    """Phase 3 -- single CP-SAT call covering the whole week via
    ``MonolithicSolver(scope=None)``.

    Routing:

    * ``phase_a_mode == "skip"``: ``dc_value`` stays ``None``; the
      solver builds slot vars with weekly equality
      ``sum_{d,h} slot == ore`` and decides the day distribution
      itself (gated by HARD constraints + the canonical soft cost).
    * ``phase_a_mode == "soft_hint"``: run ``cv2.solve_phase_a`` to
      produce ``dc_value``, persist it to the workspace pickle (so
      downstream meta steps can reuse it), and push it into the week
      solver via ``model.AddHint`` on the per-(t,c,s,d)
      ``day_count_for_hint`` IntVars. Hints are best-effort: CP-SAT
      may ignore them when the warm-started assignment violates a
      late-discovered HARD rule.

    HARD constraints applied to the model:

    * teacher / class / class_no_holes / h11 presence (via
      ``add_all_hard_constraints``)
    * coteach groups / sostegno shadows / potenziamento /
      parallel intra + inter
    * native locks (``add_locks``)
    * DSL pragmas loaded from the DB at level ``phase_b`` (Phase A
      pragmas are filtered out -- they operate on day_count IntVars
      that don't exist in the week-mode HARD surface)
    """
    import cpsat_v2_timetable as cv2  # type: ignore
    from ortools.sat.python import cp_model  # type: ignore
    try:
        from engine import cp_sat_constraint_model as csm  # type: ignore
    except ImportError:
        import cp_sat_constraint_model as csm  # type: ignore

    dc_value: dict | None = None
    if phase_a_mode == "soft_hint":
        print(f"[phaseB.week] running Phase A for soft_hint "
              f"(time_limit={time_a}s)")
        with SessionLocal() as _db_pa:  # 08b: Phase-A pragmas per-class
            _pa_class_flags = engine_io.class_flags_from_db(_db_pa)
            _pa_cdl = engine_io.class_day_load_allowed_from_db(_db_pa)
            _pa_cfd = engine_io.class_free_days_from_db(_db_pa)
        try:
            dc_value = cv2.solve_phase_a(
                profs, classes, triples, class_profs,
                time_limit=time_a, workers=workers, log=log,
                locked_day_count=locked_dc or None,
                coteach_groups=coteach_groups or None,
                support_assignments=support_assignments or None,
                potenziamento_assignments=potenziamento_assignments or None,
                parallel_groups=parallel_groups or None,
                group_assignments=group_assignments or None,
                class_flags=_pa_class_flags,
                class_day_load_allowed=_pa_cdl,
                class_free_days=_pa_cfd,
            )
        except cv2.PhaseAError as exc:
            # A hint that cannot be computed is a missing hint, not a
            # failed run: this branch only ever feeds ``AddHint``, and
            # the week model is complete on its own (weekly hours
            # equality is HARD there). Aborting here threw away runs
            # the week solver could -- and, on `skip`, demonstrably did
            # -- solve. Degrade to the `skip` routing and say so loudly.
            #
            # Only the SOFT path degrades. ``phase_a_mode="always"``
            # consumes dc_value as solver INPUT, so its caller below
            # still propagates the exception.
            print(f"[phaseB.week] ATTENZIONE: fase A non utilizzabile "
                  f"come suggerimento ({type(exc).__name__}): {exc}")
            print("[phaseB.week] il run prosegue come 'skip': il solver "
                  "settimanale decide da se' la distribuzione sui "
                  "giorni. L'orario prodotto resta valido -- manca "
                  "solo il suggerimento di partenza.")
            dc_value = None
        if dc_value is not None:
            with open(Path(ws) / "phase_a_dc.pkl", "wb") as f:
                pickle.dump(dc_value, f)
        update_run(rid, progress=0.20, current_step="phase_a")
    else:
        # phase_a_mode == "skip"
        update_run(rid, progress=0.10, current_step="phase_a")

    # Native locks: turn the snapshot into 5-tuples (t, cl, s, d, h)
    # and apply them as slot==1 equalities. Computed once (lock-set is
    # invariant across refinement iterations).
    locks_5: list = []
    for d, lst in (locked_by_day or {}).items():
        for entry in lst:
            if len(entry) == 4:
                t, cl, s, h = entry
                locks_5.append((t, cl, s, d, h))

    # Collect HARD DSL expression strings for the post-solve DSL
    # compliance gate. ``None`` => no hard DSL => the byte-identical
    # single-shot path runs (no verify, no refinement, no extra solve).
    with SessionLocal() as _db_h:
        hard_exprs = _load_dsl_hard_expressions(_db_h)

    # Special-room (gym/lab) capacity for the whole week (finding 34).
    # Built once; None when no subject carries a required_kind or there
    # are no such rooms, in which case the week model is unchanged.
    with SessionLocal() as _db_sr:
        _special_room_ctx = cv2.build_special_room_ctx(_db_sr)
    # Per-class HARD-invariant overrides for the week solver (finding 08b).
    try:
        with SessionLocal() as _db_cf:
            _week_class_flags = engine_io.class_flags_from_db(_db_cf)
    except Exception:
        _week_class_flags = None

    # Joint (day,hour,room): placement-independent room metadata, built
    # once. Room vars are folded into the week model so the schedule is
    # constrained to be room-feasible (capacity / required_kind / home)
    # while it still chooses hours. None when joint is off -> model
    # unchanged. Plessi in the joint model is deferred to a later stage;
    # plessi commuting is still enforced by the downstream rooms step.
    _joint_room_ctx = None
    if joint_vars is not None:
        with SessionLocal() as _db_jr:
            _joint_room_ctx = engine_io.joint_room_ctx_from_db(_db_jr)
    # Holder for the joint room assignment captured from the winning solve
    # (mutated by _solve_once / the single-shot path). solve_with_dsl_
    # refinement always returns the LAST solve_once's solution, so the last
    # capture matches the returned schedule.
    _jrm_holder: dict = {"map": None}

    def _build_week_solver(forbidden):
        """Build the monolithic week-scope solver from scratch and
        return ``(solver, cp_solver, status_name)`` after solving.

        ``forbidden`` is a list of previously-rejected assignment dicts
        applied as DSL no-good cuts over the freshly-built slot vars
        (empty on the default path => identical model to the legacy
        single-shot build).
        """
        # dc_value=None puts the model in weekly_mode; slot vars use the
        # weekly equality from profs[..]["ore"] and the day distribution
        # becomes a CP-SAT decision.
        cfg = csm.ConstraintConfig(
            enforce_no_holes=True,
            enforce_h3_presence_at_11=True,
            enforce_motorie_pair=True,
            enforce_math_italian_pair=True,
            class_flags=_week_class_flags,
            locks=[],  # native locks are added below via add_locks
            coteach_groups=list(coteach_groups or []),
            support_assignments=list(support_assignments or []),
            potenziamento_assignments=list(potenziamento_assignments or []),
            parallel_groups=list(parallel_groups or []),
            group_assignments=list(group_assignments or []),
        )
        solver = csm.MonolithicSolver(profs, dc_value=None, config=cfg,
                                        scope=None)
        print(f"[phaseB.week] slot vars: {len(solver.slot)}, "
              f"day_count hint vars: {len(solver.day_count_for_hint)}")

        # Wire up DB-driven DSL pragmas at level=phase_b (skip phase_a-only
        # pragmas: their day_count IntVars don't exist on the slot-only
        # week model).
        with SessionLocal() as db:
            n_rules = _apply_dsl_rules_to_week_solver(
                solver, db, level="phase_b")
        if n_rules:
            print(f"[phaseB.week] loaded {n_rules} DSL rules "
                  "(HARD + SOFT, level=phase_b)")

        # Inter-class group slots first so subsequent helpers see them.
        solver.add_parallel_groups_inter_class()
        solver.add_coteach_groups()
        solver.add_support_assignments()
        solver.add_potenziamento_assignments()
        solver.add_parallel_groups_intra_class()
        solver.add_all_hard_constraints()
        solver.add_class_no_overlap()

        # Per-teacher HARD caps that MonolithicSolver.build() emits but the
        # piecemeal week path never did: cap daily load at 5h (mirrors
        # MAX_PROF_HOURS_PER_DAY / the is_hard_feasible H_C "no 6-hour band"
        # check) + the min-free-days floor. Without these the week solver
        # could return a timetable its OWN validator (is_hard_feasible)
        # rejects -- feasible=False, never activated (audit finding 24). The
        # soft prof-day-load penalty usually hid it; the joint room coupling
        # perturbed the schedule enough to expose it (a prof landing on 6h).
        _mx = csm.PHASE_A_MAX_PROF_HOURS_PER_DAY
        for _t in sorted(solver.profs):
            _qt = '"' + str(_t).replace('\\', '\\\\').replace('"', '\\"') + '"'
            solver.add_dsl_constraint(
                f'teacher_max_per_day({_qt}, {_mx})', level="phase_b")
            _nf = int(solver.profs.get(_t, {}).get("min_free_days", 1) or 0)
            if _nf > 0:
                solver.add_dsl_constraint(
                    f'teacher_at_least_n_free_days({_qt}, {_nf})',
                    level="phase_b")

        if _special_room_ctx:
            n_sr = cv2.add_special_room_capacity_phase_b(
                solver.model, solver.slot, _special_room_ctx, day=None)
            if n_sr:
                print(f"[phaseB.week] aule speciali: {n_sr} "
                      f"vincoli capienza")

        if locks_5:
            print(f"[phaseB.week] applying {len(locks_5)} native locks")
            solver.add_locks(locks_5)

        # DSL no-good cuts: forbid each previously-rejected exact
        # assignment over the freshly-built slot vars. Empty on the
        # default path -> zero cuts -> identical model.
        if forbidden:
            try:
                from engine import dsl_cp_gate as _gate  # type: ignore
            except ImportError:
                import dsl_cp_gate as _gate  # type: ignore
            for fsol in forbidden:
                _gate.add_nogood(solver.model, solver.slot, fsol)

        # Soft cost as objective. Joint mode may drop schedule-side terms
        # (sixth / buchi / day_load) the user excluded from optimization.
        _excl = joint_vars["exclude"] if joint_vars else None
        obj_terms, _ = solver.compute_soft_cost_expr(
            mode="default", exclude=_excl)
        obj_terms = list(obj_terms)

        # Joint room vars: fold room assignment into THIS schedule model so
        # the solver may move a lesson to another hour to keep it room-
        # feasible, and add the room soft goals (home / pref / overflow)
        # the user left enabled.
        if _joint_room_ctx is not None:
            _jx, _jt, _jinfo = _add_joint_rooms(
                solver.model, solver.slot, _joint_room_ctx, joint_vars)
            obj_terms.extend(_jt)
            solver._joint_room_x = _jx  # for optional direct extraction
            print(f"[phaseB.week] joint rooms: {_jinfo['n_room_vars']} "
                  f"var aula, {len(_jinfo['no_room_cells'])} celle senza "
                  f"aula ammissibile, plessi(commute={_jinfo['n_plessi_commute']}"
                  f",policy={_jinfo['n_plessi_policy']})")

        if obj_terms:
            solver.model.Minimize(sum(obj_terms))

        # Phase A as soft hint, if applicable.
        if dc_value:
            n_hints = solver.add_phase_a_hint(dc_value)
            print(f"[phaseB.week] applied {n_hints} Phase A hints "
                  "via AddHint")

        cp_solver = cp_model.CpSolver()
        cp_solver.parameters.max_time_in_seconds = float(time_mono)
        cp_solver.parameters.num_search_workers = int(workers)
        cp_solver.parameters.log_search_progress = bool(log)
        print(f"[phaseB.week] solving (time_limit={time_mono}s, "
              f"workers={workers})")
        # Advance the progress bar during this single long solve (finding
        # 19). The window is the caller's: on the run_phase_b path the
        # milestone jumped to 0.30 before it and the next step
        # (rooms/finalize) picks up at ~0.90, so the callback fills the
        # gap; run_full_pipeline hands over its own step slice instead.
        _pcb = _ProgressCallback(rid, base=progress_base,
                                 span=progress_span,
                                 time_limit=time_mono, step="phase_b")
        status = cp_solver.Solve(solver.model, _pcb)
        status_name = cp_solver.StatusName(status)
        print(f"[phaseB.week] status={status_name}")
        return solver, cp_solver, status, status_name

    # The monolithic week solve below is the long wait; label it so the UI
    # shows 'Phase B' during it instead of a stale earlier step (finding 19).
    update_run(rid, progress=progress_base, current_step="phase_b")

    def _solve_once(forbidden):
        """Adapter for ``dsl_cp_gate.solve_with_dsl_refinement``: build +
        solve, returning ``(sol_or_None, status_name)``."""
        solver, cp_solver, status, status_name = _build_week_solver(forbidden)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return None, status_name
        sol = {k: 1 for k, v in solver.slot.items() if cp_solver.Value(v)}
        _jrm_holder["map"] = _room_map_from_joint_x(solver, cp_solver)
        return sol, status_name

    if hard_exprs:
        # DSL-compliant path: refine via no-good accumulation until every
        # checkable HARD DSL rule holds on the produced week (or budget).
        try:
            from engine import dsl_cp_gate as _gate  # type: ignore
        except ImportError:
            import dsl_cp_gate as _gate  # type: ignore
        print(f"[phaseB.week] DSL gate: {len(hard_exprs)} HARD rule(s) "
              "-> verify + no-good refinement")
        full_solution, status_name, unsatisfied = (
            _gate.solve_with_dsl_refinement(
                _solve_once, profs, hard_exprs, max_iters=8))
        if full_solution is None:
            if locks_5:
                raise RuntimeError(
                    "Phase B (week scope) INFEASIBLE: i lock correnti "
                    "sono incompatibili con i vincoli. Rimuovi o adatta "
                    "i lock e ritenta.")
            raise RuntimeError(
                f"Phase B (week scope) returned {status_name}: nessuna "
                "soluzione settimanale entro il time limit. Aumenta "
                "time_mono o passa a cp_sat_scope='day'.")
        if unsatisfied:
            # Surface the un-enforceable HARD rules as structured warnings
            # (the honest "couldn't fully comply within budget" signal).
            try:
                from engine import constraint_compat as _cc  # type: ignore
            except ImportError:
                import constraint_compat as _cc  # type: ignore
            warns = _cc.summarize(
                ["compile_failed:" + e + ":refinement:exhausted"
                 for e in unsatisfied],
                pipeline="week_cpsat")
            for w in warns:
                print(f"[phaseB.week][WARN] DSL hard rule not satisfied "
                      f"within budget: {getattr(w, 'reason', w)}")
            # P0 truthfulness: a timetable that still violates HARD rules
            # is NOT a valid result. The gate's no-good refinement can
            # exhaust its budget (max_iters) and return a violating
            # solution; returning it here silently marked the whole run
            # 'done' with hard constraints broken -- the single most
            # dangerous failure mode for a big school. Fail closed by
            # default. Set PITANTUM_DSL_GATE_STRICT=0 to restore the old
            # "keep the partial, violating solution" behaviour for
            # inspection.
            strict = os.environ.get(
                "PITANTUM_DSL_GATE_STRICT", "1"
            ).strip().lower() not in ("0", "false", "no", "off")
            if strict:
                raise RuntimeError(
                    "Phase B (week scope): "
                    f"{len(unsatisfied)} vincolo/i HARD DSL non "
                    "soddisfatti dopo il refinement (budget esaurito). "
                    "L'orario NON e' valido e non viene salvato. "
                    "Aumenta il time limit / max_iters, allenta i vincoli, "
                    "o imposta PITANTUM_DSL_GATE_STRICT=0 per accettare un "
                    "risultato parziale a scopo di ispezione. "
                    f"Regole violate: {'; '.join(unsatisfied[:5])}"
                    + (" ..." if len(unsatisfied) > 5 else "")
                )
        return full_solution, _jrm_holder["map"]

    # Default path (no hard DSL): single-shot build + solve, byte-identical
    # to the legacy behaviour (no verify, no refinement, no extra solve).
    solver, cp_solver, status, status_name = _build_week_solver([])
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        if locks_5:
            raise RuntimeError(
                "Phase B (week scope) INFEASIBLE: i lock correnti "
                "sono incompatibili con i vincoli. Rimuovi o adatta "
                "i lock e ritenta.")
        raise RuntimeError(
            f"Phase B (week scope) returned {status_name}: nessuna "
            "soluzione settimanale entro il time limit. Aumenta "
            "time_mono o passa a cp_sat_scope='day'.")

    # Extract the solution dict in the same shape the legacy day-mode
    # produces: {(t, cl, subj, d, h): 1}.
    full_solution = {
        k: 1 for k, v in solver.slot.items() if cp_solver.Value(v)}
    _jrm_holder["map"] = _room_map_from_joint_x(solver, cp_solver)
    return full_solution, _jrm_holder["map"]


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



def _per_day_dsl_warning_lines(diagnostics) -> list[str]:
    """Format per-day Phase-B DSL diagnostics into RunLog warning lines.

    Pure: turns the free-text ``diagnostics_sink`` collected across the day
    solves into structured ``[phaseB.day][WARN]`` lines via
    ``constraint_compat.summarize`` (drops info lines, dedups). Mirrors the
    week path's ``[phaseB.week][WARN]`` surfacing so the frontend sees, for
    cross-day / unsupported rules the per-day CP couldn't model, *which*
    constraint was not enforced and what to do (typically: run a
    metaheuristic post-pass, which evaluates every DSL rule post-hoc).
    """
    if not diagnostics:
        return []
    try:
        from engine import constraint_compat as _cc  # type: ignore
    except ImportError:
        import constraint_compat as _cc  # type: ignore
    lines = []
    for w in _cc.summarize(diagnostics, pipeline="per_day_cpsat"):
        lines.append(
            f"[phaseB.day][WARN] DSL rule not enforced per-day "
            f"({w.constraint}): {w.reason}. {w.suggestion}")
    return lines


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
            locked_snap = _read_locked_lessons(db)
            profs = engine_io.profs_dict_from_db(db)
            coteach_groups_meta = engine_io.coteach_groups_for_solver(db)
            support_assignments_meta = (
                engine_io.support_assignments_from_db(db))
            parallel_groups_meta = engine_io.parallel_groups_for_solver(
                db)
            group_assignments_meta = engine_io.group_assignments_for_solver(
                db)
            # 08b: without this the meta's is_hard_feasible re-flags every
            # class whose card relaxed an invariant, sees the baseline as
            # "dirty", and degrades (no improvement + feasible:false).
            class_flags_meta = engine_io.class_flags_from_db(db)
            # finding 34: capacita' aule speciali (palestra/lab). Costruito
            # QUI (sessione aperta) e passato materializzato, come
            # class_flags: senza, le metaeuristiche (che non ricevono `db`)
            # non vincolano la capienza palestra e reintroducono l'overflow
            # che poi rende infeasible l'assegnazione aule. Vedi
            # cpsat_v2_timetable.build_special_room_ctx.
            special_room_ctx_meta = _build_special_room_ctx_safe(db)
            active = engine_io.get_active_solution(db)
            if active is None:
                raise RuntimeError("Nessuna soluzione attiva; esegui prima "
                                   "Phase B o importa un pickle.")
            sol = engine_io.lessons_to_solution_dict(db, active.id)
            # Subproject D: pre-parse DSL SOFT rules ONCE while the DB
            # session is open. The trees MUST be produced by
            # metaheuristics' own general_dsl import (via
            # meta.parse_soft_rules) so compute_soft evaluates them
            # against the SAME AST node classes; parsing with a
            # separately-imported general_dsl alias would silently make
            # every rule read VIOLATED (dual-module AST hazard).
            soft_rules = None
            try:
                try:
                    from engine import dsl_translator as _dt  # type: ignore
                except ImportError:
                    import dsl_translator as _dt  # type: ignore
                _all = _dt.load_all_dsl_constraints(db, _models=models, include_soft=True)
                soft_rules = meta.parse_soft_rules(_all) or None
            except Exception:
                soft_rules = None
            # Universal DSL solver: load HARD DSL rule expression STRINGS
            # ONCE while the session is open and thread them into every
            # runner via `dsl_hard_expressions=`. Each runner re-parses
            # them inside is_hard_feasible with metaheuristics' own
            # general_dsl import (strings cross the boundary, not trees),
            # rejecting any move that violates an arbitrary HARD rule the
            # per-day CP compiler cannot model. None => zero-drift.
            dsl_hard_expressions = _load_dsl_hard_expressions(db)
            # Gli stessi quattro pezzi di contesto che gia\` passiamo
            # agli algoritmi: senza, `is_hard_feasible` conta il
            # sostegno come doppia occupazione della classe e dichiara
            # infattibile ogni orario. Vedi `_hard_check_ctx`.
            hard_ctx = {
                "support_assignments": support_assignments_meta,
                "coteach_groups": coteach_groups_meta,
                "parallel_groups": parallel_groups_meta,
                "group_assignments": group_assignments_meta,
                "class_flags": class_flags_meta,
                "special_room_ctx": special_room_ctx_meta,
            }
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
        if not meta.is_hard_feasible(
                sol, profs, verbose=False,
                dsl_hard_expressions=dsl_hard_expressions, **hard_ctx):
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
            _plessi_ctx_meta = None
            try:
                import cpsat_v2_timetable as _cv2m  # type: ignore
                with SessionLocal() as _db_pl:
                    _plessi_ctx_meta = _cv2m.build_plessi_ctx(_db_pl)
            except Exception:  # noqa: BLE001
                _plessi_ctx_meta = None
            c3_kwargs = dict(
                coteach_groups=coteach_groups_meta or None,
                support_assignments=support_assignments_meta or None,
                parallel_groups=parallel_groups_meta or None,
                group_assignments=group_assignments_meta or None,
                class_flags=class_flags_meta,
                special_room_ctx=special_room_ctx_meta,
                soft_rules=soft_rules,
                dsl_hard_expressions=dsl_hard_expressions,
                plessi_ctx=_plessi_ctx_meta,
            )
            if stage == "lns":
                new_sol, _hist = meta.run_lns(
                    sol, profs, dc_value, budget_s,
                    classes_clusters=classes_clusters,
                    log=log, workers=workers, locks=locks_set,
                    **c3_kwargs,
                )
            elif stage == "sa":
                new_sol = meta.run_sa(
                    sol, profs, dc_value, budget_s,
                    T0=sa_T0, alpha=sa_alpha, log=log,
                    locks=locks_set, **c3_kwargs,
                )
            elif stage == "ts":
                new_sol = meta.run_tabu(
                    sol, profs, dc_value, budget_s,
                    tabu_size=tabu_size, log=log, locks=locks_set,
                    **c3_kwargs,
                )
            elif stage == "ils":
                new_sol = meta.run_ils(
                    sol, profs, dc_value, budget_s,
                    classes_clusters=classes_clusters,
                    ts_budget_per_cycle=ts_budget_per_cycle,
                    n_cycles=n_cycles, log=log, locks=locks_set,
                    **c3_kwargs,
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
                    locks=locks_set, **c3_kwargs,
                )
            elif stage == "vns":
                import vns as vns_mod  # type: ignore
                new_sol, _hist = vns_mod.run_vns(
                    sol, profs, dc_value, budget_s,
                    log=log,
                    enabled_neighbourhoods=vns_neighbourhoods,
                    locks=locks_set, **c3_kwargs,
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
                    log=log, locks=locks_set, **c3_kwargs,
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
        feasible = meta.is_hard_feasible(
            new_sol, profs, verbose=False,
            dsl_hard_expressions=dsl_hard_expressions, **hard_ctx)
        with SessionLocal() as db:
            sid = engine_io.import_solution_into_db(
                db, new_sol,
                name=f"{stage.upper()} run {rid}",
                kind=stage,
                obj_value=float(v),
                metrics={**m, "feasible": feasible},
                make_active=feasible,
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
                if rooms_metrics.get("rooms_unplaced"):
                    rooms_metrics = retry_unplaced_days_with_lambda(
                        sid, rooms_metrics,
                        time_limit_s=rooms_time_limit_s,
                        workers=workers, prefer_home=rooms_prefer_home,
                        log_prefix=f"{stage}.rooms")
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


# Scenario presets for Phase B. The engine is fully general -- it can
# already solve a part-time school via week scope + soft_hint -- but the
# DEFAULT knobs ('day' + 'always') pin Phase A's day distribution as a
# HARD equality that Phase B cannot satisfy once teachers have real
# availability limits (audit finding 20). Rather than change what the
# solver does, we name the configurations that work so a school can pick
# one, instead of discovering the good mode by reading engine source.
SCENARIO_PRESETS: list[dict[str, Any]] = [
    {
        "key": "standard",
        "label": "Standard (decomposizione per giorno)",
        "summary": (
            "Scope 'day' + phase_a_mode 'always' con decomposizione. Veloce; "
            "adatto a scuole con poche indisponibilita' orarie rigide."
        ),
        "params": {
            "cp_sat_scope": "day",
            "phase_a_mode": "always",
            "use_decomposition": True,
        },
        "recommended_when": "Poche o nessuna indisponibilita' HARD.",
    },
    {
        "key": "part_time_sostegno",
        "label": "Part-time / sostegno (settimanale)",
        "summary": (
            "Scope 'week' + phase_a_mode 'soft_hint', senza decomposizione. "
            "La distribuzione della Fase A diventa un suggerimento e il "
            "solver ridistribuisce le ore rispettando indisponibilita' e "
            "giorni liberi veri. Piu' lento ma robusto per la scuola statale "
            "tipica (part-time, cattedre esterne, L.104, sostegno)."
        ),
        "params": {
            "cp_sat_scope": "week",
            "phase_a_mode": "soft_hint",
            "use_decomposition": False,
        },
        "recommended_when": (
            "Docenti part-time, cattedre esterne, molti giorni liberi "
            "obbligatori o indisponibilita' HARD diffuse."
        ),
    },
]



def _suggest_cg_granularity(n_classes: int) -> str:
    """Heuristic for the 'auto' granularity option.

    < 15 classes  -> 'teacher' (very small schools, per-teacher
                     pattern catalog is small enough to enumerate).
    15-30 classes -> 'teacher-day' (per-teacher patterns get large
                     fast; splitting by day is a good compromise).
    30-50 classes -> 'teacher-class' (medium schools: bind each
                     teacher to ONE class at a time -- patterns
                     stay small).
    50-80 classes -> 'class' (large schools, per-class patterns
                     scale better while teacher catalogs explode).
    > 80 classes  -> 'curriculum' (very large schools with
                     structured indirizzi).

    The 'day', 'class-day', 'teacher-subject', 'teacher-class-subject'
    granularities are never auto-selected but remain available for
    experimentation.
    """
    if n_classes < 15:
        return "teacher"
    if n_classes < 30:
        return "teacher-day"
    if n_classes < 50:
        return "teacher-class"
    if n_classes <= 80:
        return "class"
    return "curriculum"


_CG_GRANULARITIES = (
    "teacher",
    "teacher-day",
    "teacher-class",
    "teacher-class-subject",
    "teacher-subject",
    "class",
    "class-day",
    "day",
    "curriculum",
)
_CG_MODES = ("iterative-diversified", "branch-and-price", "auto")


def run_column_generation(*, time_budget_s: float = 60.0,
                          patterns_per_teacher: int = 3,
                          mode: str = "iterative-diversified",
                          granularity: str = "auto",
                          branching_strategy: str = "ryan_foster",
                          max_iterations: int = 5,
                          bp_max_iterations: int = 8,
                          pricer_time_limit: float = 5.0,
                          pricer_workers: int = 2,
                          parallel: bool = True,
                          log: bool = True) -> int:
    """Async Column Generation pass. Behaves like an alternative
    Phase-B: starts from the active assignment (Phase A), produces
    a HARD-feasible weekly schedule via the iterative master LP +
    pattern enrichment + day-by-day completion fallback. Saved as
    a new Solution with kind='cg'.

    `mode` is forwarded to the engine and selects iterative-
    diversified vs branch-and-price (real BP with per-granularity
    sub-CP-SAT pricing). `granularity` selects the BP sub-problem
    unit when mode is branch-and-price (or auto-resolved to it).
    Granularities not yet implemented in the engine fall back to
    'teacher' with a log warning.
    """
    params = dict(time_budget_s=time_budget_s,
                  patterns_per_teacher=patterns_per_teacher,
                  mode=mode,
                  granularity=granularity,
                  branching_strategy=branching_strategy,
                  max_iterations=max_iterations,
                  bp_max_iterations=bp_max_iterations,
                  pricer_time_limit=pricer_time_limit,
                  pricer_workers=pricer_workers,
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
    if granularity not in _CG_GRANULARITIES:
        print(f"[cg] WARNING: granularity={granularity!r} non "
              f"riconosciuta; uso 'teacher'")
        granularity = "teacher"
    if mode not in _CG_MODES:
        print(f"[cg] WARNING: mode={mode!r} non riconosciuta; "
              f"uso 'iterative-diversified'")
        mode = "iterative-diversified"
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
            locked_snap = _read_locked_lessons(db)
            profs = engine_io.profs_dict_from_db(db)
            coteach_groups = engine_io.coteach_groups_for_solver(db)
            support_assignments = engine_io.support_assignments_from_db(
                db)
            parallel_groups = engine_io.parallel_groups_for_solver(db)
            group_assignments = engine_io.group_assignments_for_solver(
                db)
            active = engine_io.get_active_solution(db)
            if active is None:
                raise RuntimeError("Phase B alternativa via Column "
                                    "Generation richiede una soluzione "
                                    "attiva (Phase A) come baseline.")
            sol = engine_io.lessons_to_solution_dict(db, active.id)
            # Universal DSL gate (cross-column): load HARD DSL rule
            # expression STRINGS while the session is open. The engine
            # cannot model cross-column/global HARD DSL inside a pricer,
            # so it VERIFIES the assembled solution post-hoc and reports
            # any violation as a warning (the meta post-pass enforces it).
            # None => zero-drift (the whole gate block is skipped).
            cg_dsl_hard = _load_dsl_hard_expressions(db)
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
        # 08b + 34: per-class flags and special-room capacity for the CG
        # completion solver, built once.
        import cpsat_v2_timetable as cv2  # type: ignore
        with SessionLocal() as _dbcg:
            _cg_class_flags = engine_io.class_flags_from_db(_dbcg)
            _cg_special_room = cv2.build_special_room_ctx(_dbcg)
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
                support_assignments=support_assignments or None,
                parallel_groups=parallel_groups or None,
                group_assignments=group_assignments or None,
                special_room_ctx=_cg_special_room,
                class_flags=_cg_class_flags,
                mode=mode,
                granularity=granularity,
                branching_strategy=branching_strategy,
                bp_max_iterations=bp_max_iterations,
                pricer_time_limit=pricer_time_limit,
                pricer_workers=pricer_workers,
                dsl_hard_expressions=cg_dsl_hard,
            )
        # Surface any cross-column HARD DSL the pricers could not model
        # (reported by the engine's post-assembly verification) to RunLog.
        # `print` is captured into RunLog by run_manager's stdout SSE pump;
        # the structured warnings also ride along in `info`/metrics below.
        for _w in info.get("dsl_warnings", []):
            print(f"[cg][DSL] {_w.get('severity', 'warning').upper()}: "
                  f"{_w.get('constraint')} non modellabile nel pricer "
                  f"(branch-and-price, cross-column) -- "
                  f"{_w.get('suggestion')}")
        if new_sol is None or not (info.get("feasible_after_assembly")
                                   or info.get("feasible_after_completion")):
            update_run(rid_inner, progress=1.0,
                        metrics={**info, "feasible": False},
                        error="CG skeleton non ha trovato una "
                              "soluzione feasible (vedi warnings)")
            return
        v, m = meta.compute_soft(new_sol, profs)
        # Audit H13: activate only if the produced timetable is actually
        # hard-feasible with the full DSL-aware ctx -- not a hardcoded True.
        _cg_feas = meta.is_hard_feasible(
            new_sol, profs, **_hard_check_ctx_fresh())
        with SessionLocal() as db:
            sid = engine_io.import_solution_into_db(
                db, new_sol,
                name=f"CG run {rid_inner}",
                kind="cg",
                obj_value=float(v),
                metrics={**m, **info, "feasible": _cg_feas},
                make_active=_cg_feas,
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
                if rm.get("rooms_unplaced"):
                    rm = retry_unplaced_days_with_lambda(
                        state["sid"], rm,
                        time_limit_s=tlim, workers=workers,
                        prefer_home=prefer_home,
                        log_prefix=f"{stage_label}.rooms")
                state["rooms_metrics"] = {**state["rooms_metrics"], **rm}
            except Exception as e:  # noqa: BLE001
                print(f"[{stage_label}] rooms step failed: {e}")
                state["rooms_metrics"]["rooms_error"] = str(e)

        for i, step in enumerate(seq):
            # Cooperative cancellation: bail promptly between pipeline
            # steps instead of running every remaining step to its full
            # time budget after the user clicked cancel.
            raise_if_cancelled(rid)
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
                # Build the per-run solver ctx ONCE for this phase_b step.
                # The full-pipeline block used to build none, so plessi
                # transfer-time (25/35), special-room capacity (34) and the
                # per-class HARD toggles (08b) never reached its solvers.
                with SessionLocal() as _db_ctx:
                    _plessi_ctx = cv2.build_plessi_ctx(_db_ctx)
                    _special_room_ctx = cv2.build_special_room_ctx(_db_ctx)
                    _class_flags = engine_io.class_flags_from_db(_db_ctx)
                    _cdl = engine_io.class_day_load_allowed_from_db(_db_ctx)
                    _cfd = engine_io.class_free_days_from_db(_db_ctx)
                    # Per-slot general room capacity (option A), opt-in via the
                    # phase_b step's respect_room_capacity kwarg. None -> off.
                    _total_room_capacity = None
                    if (pb_kwargs or {}).get("respect_room_capacity"):
                        _total_room_capacity = (
                            _db_ctx.query(models.Classroom)
                            .filter(models.Classroom.kind == "standard")
                            .count() or None)
                if _total_room_capacity:
                    print(f"[full] phase_b: capienza aule standard attiva: "
                          f"{_total_room_capacity}")
                _pb_scope = (pb_kwargs or {}).get("cp_sat_scope", "day")
                # WEEK scope runs its own Phase A internally (soft_hint); the
                # decomposition/per-day branches need dc_value up front.
                dc_value = None if _pb_scope == "week" else cv2.solve_phase_a(
                    profs, classes, triples, class_profs,
                    time_limit=(pb_kwargs or {}).get("time_a", 60),
                    workers=workers, log=False,
                    class_flags=_class_flags,
                    class_day_load_allowed=_cdl,
                    class_free_days=_cfd,
                )
                state["dc_value"] = dc_value
                full_solution: dict = {}
                if _pb_scope == "week":
                    # The monolithic WEEK solve is the only engine that keeps
                    # 100% coverage + honours the HARD DSL (free-day) rules at
                    # scale; the full pipeline could not reach it before (it was
                    # locked to decomposition/per-day). Classic week + separate
                    # exact rooms (joint_vars=None) -- the scalable path.
                    print("[full] phase_b: monolithic WEEK scope")
                    ws = _run_workspace(rid)
                    with SessionLocal() as _db_w:
                        _lk = _read_locked_lessons(_db_w)
                        _ct = engine_io.coteach_groups_for_solver(_db_w)
                        _sa = engine_io.support_assignments_from_db(_db_w)
                        _pa = engine_io.potenziamento_assignments_from_db(_db_w)
                        _pg = engine_io.parallel_groups_for_solver(_db_w)
                        _ga = engine_io.group_assignments_for_solver(_db_w)
                    full_solution, _ = _solve_phase_b_week(
                        rid=rid, ws=ws, profs=profs, classes=classes,
                        triples=triples, class_profs=class_profs,
                        phase_a_mode="soft_hint",
                        time_a=(pb_kwargs or {}).get("time_a", 60),
                        time_mono=(pb_kwargs or {}).get("time_mono", 120),
                        workers=workers, log=False,
                        locked_dc=_locked_day_count_from_snapshot(_lk),
                        locked_by_day=_locked_slots_by_day(_lk),
                        coteach_groups=_ct, support_assignments=_sa,
                        potenziamento_assignments=_pa, parallel_groups=_pg,
                        group_assignments=_ga,
                        joint_vars=None,
                        # This solve owns exactly this pipeline step's
                        # slice of the bar. Letting it keep the
                        # run_phase_b default made it climb to 0.88 and
                        # then snap back to (i+1)/n_steps.
                        progress_base=i / n_steps,
                        progress_span=1 / n_steps,
                    )
                elif ((pb_kwargs or {}).get("use_decomposition", True)
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
                        raise_if_cancelled(rid)
                        out, _st = dec.stage_a_bridges(
                            d, profs, bridges_set, triples, dc_value,
                            (pb_kwargs or {}).get("time_bridges", 30), workers,
                            plessi_ctx=_plessi_ctx,
                            class_flags=_class_flags,
                        )
                        if out is None:
                            a_failed.append(d)
                        else:
                            bridge_solutions[d] = out
                    cluster_solutions: dict[tuple[int, int], dict] = {}
                    b_failed: dict[int, set] = defaultdict(set)
                    for d in DAYS:
                        raise_if_cancelled(rid)
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
                                plessi_ctx=_plessi_ctx,
                                class_flags=_class_flags,
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
                        raise_if_cancelled(rid)
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
                            plessi_ctx=_plessi_ctx,
                            class_flags=_class_flags,
                        )
                        if out is not None:
                            full_solution = {
                                kk: vv for kk, vv in full_solution.items()
                                if kk[3] != d
                            }
                            full_solution.update(out)
                else:
                    for d in DAYS:
                        raise_if_cancelled(rid)
                        out, _st = cv2.solve_phase_b_for_day(
                            d, profs, classes, triples, class_profs,
                            dc_value,
                            time_limit=(pb_kwargs or {}).get("time_mono", 120),
                            workers=workers, log=False,
                            plessi_ctx=_plessi_ctx,
                            special_room_ctx=_special_room_ctx,
                            class_flags=_class_flags,
                            total_room_capacity=_total_room_capacity,
                        )
                        if out is not None:
                            full_solution.update(out)
                v, m = meta.compute_soft(full_solution, profs)
                feasible = meta.is_hard_feasible(
                    full_solution, profs, verbose=False,
                    **_hard_check_ctx_fresh(),
                )
                # P0 truthfulness: fail the run on an incomplete schedule
                # rather than saving a partial timetable as active.
                _gate_coverage(full_solution, state.get("dc_value"),
                               stage="full.phase_b", metrics=m)
                with SessionLocal() as db:
                    sid = engine_io.import_solution_into_db(
                        db, full_solution,
                        name=f"Full pipeline run {rid} (phase_b)",
                        kind="phase_b",
                        obj_value=float(v),
                        metrics={**m, "feasible": feasible},
                        make_active=feasible,
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
  # (harmless: engine_paths.ensure_engine_on_path() already handles this — audit A2)
                    sys.path.insert(0, exp_dir)
                pb = pb_kwargs or {}
                t_a = float(pb.get("time_a", 60))
                t_day = float(pb.get("time_day", 30))
                t_bridges = float(pb.get("time_bridges", 30))
                t_cluster = float(pb.get("time_cluster", 30))
                t_ric = float(pb.get("time_ricucitura", 60))
                t_mono = float(pb.get("time_mono", 120))

                # Audit H5: the decomp tokens forwarded ONLY time budgets --
                # dropping locks, coteach, sostegno, parallel, groups,
                # special-room capacity, per-class flags and the free-day
                # rule. Dropped HARDs the validator checks now fail-closed
                # (H1), but dropped LOCKS are checked by nothing, so a locked
                # lesson silently moved. Build the full context once and feed
                # it to whichever engine accepts it.
                with SessionLocal() as _db_d:
                    _d_locked = _read_locked_lessons(_db_d)
                    _d_coteach = engine_io.coteach_groups_for_solver(_db_d)
                    _d_support = engine_io.support_assignments_from_db(_db_d)
                    _d_parallel = engine_io.parallel_groups_for_solver(_db_d)
                    _d_groups = engine_io.group_assignments_for_solver(_db_d)
                    _d_class_flags = engine_io.class_flags_from_db(_db_d)
                    _d_cdl = engine_io.class_day_load_allowed_from_db(_db_d)
                    _d_special = cv2.build_special_room_ctx(_db_d)
                    _d_plessi = cv2.build_plessi_ctx(_db_d)
                _d_locked_by_day = _locked_slots_by_day(_d_locked)
                _d_locked_dc = _locked_day_count_from_snapshot(_d_locked)

                if method == "temporal":
                    import decomposition_temporal as dec_t  # type: ignore
                    # Persist profs to a temp pickle so the
                    # ProcessPoolExecutor workers can read it.
                    import pickle as _pk
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
                        locked_day_count=_d_locked_dc or None,
                        locked_by_day=_d_locked_by_day or None,
                        coteach_groups=_d_coteach or None,
                        group_assignments=_d_groups or None,
                        special_room_ctx=_d_special,
                        class_flags=_d_class_flags,
                        class_day_load_allowed=_d_cdl,
                        support_assignments=_d_support or None,
                        parallel_groups=_d_parallel or None,
                        plessi_ctx=_d_plessi,
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
                        locked_day_count=_d_locked_dc or None,
                        locked_by_day=_d_locked_by_day or None,
                        coteach_groups=_d_coteach or None,
                        support_assignments=_d_support or None,
                        parallel_groups=_d_parallel or None,
                        group_assignments=_d_groups or None,
                        class_day_load_allowed=_d_cdl,
                        special_room_ctx=_d_special,
                        plessi_ctx=_d_plessi,
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
                    full_solution, profs, verbose=False,
                    **_hard_check_ctx_fresh())
                with SessionLocal() as db:
                    sid = engine_io.import_solution_into_db(
                        db, full_solution,
                        name=f"Pipeline {rid} decomp_{method}",
                        kind=f"phase_b_{method}",
                        obj_value=float(v),
                        metrics={**m, "feasible": feasible,
                                 **state.get("metrics", {})},
                        make_active=feasible,
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
                if new_sol is not None and (
                        info.get("feasible_after_assembly")
                        or info.get("feasible_after_completion")):
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
                    _plessi_full = None
                    try:
                        import cpsat_v2_timetable as _cv2f  # type: ignore
                        with SessionLocal() as _db_plf:
                            _plessi_full = _cv2f.build_plessi_ctx(_db_plf)
                    except Exception:  # noqa: BLE001
                        _plessi_full = None
                    new_sol, _info = lag_mod.run_lagrangian(
                        sol, profs, dc_value,
                        time_budget_s=budget_lns,
                        classes_clusters=classes_clusters,
                        log=True,
                        plessi_ctx=_plessi_full,
                    )
                else:  # "ils"
                    new_sol = meta.run_ils(
                        sol, profs, dc_value, budget_ils,
                        classes_clusters=classes_clusters, log=True,
                    )
                v, m = meta.compute_soft(new_sol, profs)
                feasible = meta.is_hard_feasible(
                    new_sol, profs, verbose=False,
                    **_hard_check_ctx_fresh(),
                )
                with SessionLocal() as db:
                    sid = engine_io.import_solution_into_db(
                        db, new_sol,
                        name=f"Full pipeline run {rid} ({step})",
                        kind=step,
                        obj_value=float(v),
                        metrics={**m, "feasible": feasible},
                        make_active=feasible,
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

    Eviction is a **last resort**: each cattedra first takes every slot
    it can have for free, and only then starts displacing movable
    lessons. Without that ordering `all_others_movable` -- where every
    lesson is movable -- would bulldoze the week from Monday first hour
    onwards instead of filling the gaps it was reached for.

    Per-slot pins (`Lesson.locked`) outrank `lock_mode` entirely: a
    pinned lesson is never wiped and never evicted, matching the "locked
    lessons are hard constraints in every path" rule the CP-SAT
    pipelines follow. A pinned lesson of a *target* cattedra therefore
    stays where it is and counts against that cattedra's hours, so
    "Piazza" tops up the remainder rather than re-placing it.

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
            # Pinned hours of a target cattedra: they stay put, so they
            # count against that cattedra's hours instead of being
            # re-placed. Keyed like `target_keys`.
            kept_pins: dict[tuple[str, str, str], int] = {}
            for l in db.query(models.Lesson).filter(
                models.Lesson.solution_id == active.id
            ).all():
                key = (l.teacher_name, l.class_name, l.subject)
                if l.locked:
                    # A per-slot pin outranks lock_mode: it is a hard
                    # constraint everywhere else in the engine, so it is
                    # neither wiped nor evicted here. Freezing it also
                    # keeps the placer from double-booking against it.
                    if key in target_keys:
                        kept_pins[key] = kept_pins.get(key, 0) + 1
                    frozen_owner.add((l.teacher_name, l.day, l.hour))
                    frozen_class.add((l.class_name, l.day, l.hour))
                    if l.classroom_name:
                        frozen_room.add((l.classroom_name, l.day, l.hour))
                    continue
                if key in target_keys:
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

            # What survives in `movable` now is everything the lock_mode
            # says MAY be displaced but that nobody has displaced yet.
            # Those lessons are still in the solution and still occupy
            # their teacher's and their class' slot -- index them so a
            # candidate slot can name its occupants and evict them.
            # Skipping this is what let the placer write a second lesson
            # into an occupied cell; /schedule's by-class view then drew
            # the collision as co-teaching, hiding it completely.
            movable_by_owner: dict[tuple[str, int, int],
                                   dict[int, models.Lesson]] = {}
            movable_by_class: dict[tuple[str, int, int],
                                   dict[int, models.Lesson]] = {}
            for l in movable:
                if l.id is None:      # already wiped above
                    continue
                movable_by_owner.setdefault(
                    (l.teacher_name, l.day, l.hour), {})[l.id] = l
                movable_by_class.setdefault(
                    (l.class_name, l.day, l.hour), {})[l.id] = l

            def _occupants(tname: str, cname: str, d: int, h: int):
                """Movable lessons blocking (tname|cname, d, h). One
                lesson can block on both axes -- dict-by-id de-dupes."""
                out = dict(movable_by_owner.get((tname, d, h), {}))
                out.update(movable_by_class.get((cname, d, h), {}))
                return list(out.values())

            def _evict(l: models.Lesson) -> None:
                movable_by_owner.get(
                    (l.teacher_name, l.day, l.hour), {}).pop(l.id, None)
                movable_by_class.get(
                    (l.class_name, l.day, l.hour), {}).pop(l.id, None)
                db.delete(l)

            # Track temporary occupancy (frozen + already placed in this run)
            placed_owner = set(frozen_owner)
            placed_class = set(frozen_class)
            # Rooms are assigned by a later step (lessons go in with
            # classroom_name=None), so nothing consults this yet; kept so
            # the frozen-room set has somewhere to go if it ever does.
            placed_room  = set(frozen_room)

            n_placed = 0
            n_unplaced = 0
            n_evicted = 0
            # Sequence target hours (one entry per missing hour)
            for (a, t, c) in targets:
                pinned = kept_pins.get((t.name, c.name, a.subject), 0)
                hours_to_place = int(a.hours) - pinned
                if pinned:
                    print(f"[piazza] {t.name}/{c.name}/{a.subject}: "
                          f"{pinned} ore bloccate restano dove sono")
                placements = []
                # Pass 1 takes only slots that are free anyway; pass 2
                # is allowed to displace movable lessons. Two passes
                # rather than one so a cattedra never evicts a colleague
                # while an empty slot is still available further on in
                # the week.
                for allow_evict in (False, True):
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
                            busy = _occupants(t.name, c.name, d, h)
                            if busy and not allow_evict:
                                continue
                            for victim in busy:
                                print(f"[piazza] sfratto "
                                      f"{victim.teacher_name}/"
                                      f"{victim.class_name}/"
                                      f"{victim.subject} da ({d}, {h})")
                                _evict(victim)
                                n_evicted += 1
                            # OK: take this slot
                            placements.append((d, h))
                            placed_owner.add((t.name, d, h))
                            placed_class.add((c.name, d, h))
                    if len(placements) >= hours_to_place:
                        break
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
                "n_evicted": n_evicted,
                "lock_mode": lock_mode,
            })
            print(f"[piazza] DONE: {n_placed} piazzate, "
                  f"{n_unplaced} non piazzate, {n_evicted} sfrattate")

    start_thread(run_id, target)
    return run_id


