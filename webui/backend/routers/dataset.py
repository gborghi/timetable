"""Dataset import / mock generation / state inspection."""
from __future__ import annotations

import os
import pickle
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from .. import models, schemas, optimization, engine_io
from ..db import get_db

router = APIRouter(prefix="/api/dataset", tags=["dataset"])


@router.get("/state")
def get_state(db: Session = Depends(get_db)):
    n_classes = db.query(models.SchoolClass).count()
    n_teachers = db.query(models.Teacher).count()
    n_subjects = db.query(models.Subject).count()
    n_assignments = db.query(models.Assignment).count()
    n_rooms = db.query(models.Classroom).count()
    n_solutions = db.query(models.Solution).count()
    active = engine_io.get_active_solution(db)
    return {
        "classes": n_classes,
        "teachers": n_teachers,
        "subjects": n_subjects,
        "assignments": n_assignments,
        "classrooms": n_rooms,
        "solutions": n_solutions,
        "active_solution": (
            None if active is None else {
                "id": active.id,
                "name": active.name,
                "kind": active.kind,
                "obj_value": active.obj_value,
                "metrics": active.metrics,
            }
        ),
    }


@router.post("/mock")
def generate_mock(payload: schemas.MockGenIn):
    run_id = optimization.run_mock_generation(
        profile=payload.profile,
        mode=payload.mode,
        margin=payload.margin,
        custom_curricula=payload.custom_curricula,
        base_max_hours=payload.base_max_hours,
    )
    return {"run_id": run_id}


@router.post("/import-profile")
def import_profile(payload: schemas.ImportPickleIn):
    here = os.path.dirname(os.path.abspath(__file__))
    experiments_dir = os.path.normpath(
        os.path.join(here, "..", "..", "..", "experiments")
    )
    school_pkl = os.path.join(experiments_dir, f"school_{payload.profile}.pkl")
    if not os.path.exists(school_pkl):
        raise HTTPException(
            404, f"school_{payload.profile}.pkl not found in experiments/"
        )
    run_id = optimization.import_experiments_profile(
        payload.profile, payload.use_optimized
    )
    return {"run_id": run_id}


@router.get("/available-profiles")
def list_profiles():
    here = os.path.dirname(os.path.abspath(__file__))
    experiments_dir = os.path.normpath(
        os.path.join(here, "..", "..", "..", "experiments")
    )
    profiles = []
    for name in ("small", "medium", "big", "huge", "superhuge"):
        school = os.path.join(experiments_dir, f"school_{name}.pkl")
        if os.path.exists(school):
            has_profs = os.path.exists(
                os.path.join(experiments_dir, f"profs_{name}.pkl")
            )
            has_opt = os.path.exists(
                os.path.join(experiments_dir,
                             f"solution_timetable_{name}_optimized.pkl")
            )
            has_dec = os.path.exists(
                os.path.join(experiments_dir,
                             f"solution_timetable_{name}_decomposed.pkl")
            )
            profiles.append({
                "name": name,
                "has_profs": has_profs,
                "has_optimized_solution": has_opt,
                "has_decomposed_solution": has_dec,
            })
    return profiles


@router.post("/upload-pickle")
async def upload_pickle(kind: str, file: UploadFile = File(...),
                        db: Session = Depends(get_db)):
    """Upload a pickle file. `kind` is one of school/profs/solution."""
    data = await file.read()
    obj = pickle.loads(data)
    if kind == "school":
        engine_io.import_school_into_db(db, obj, replace=True)
        return {"ok": True, "imported": "school", "n_classes": len(obj.get("classes", []))}
    if kind == "profs":
        n = engine_io.import_profs_into_db(db, obj)
        return {"ok": True, "imported": "profs", "n_assignments": n}
    if kind == "solution":
        # Need profs to compute SOFT
        from .. import engine_io as ei
        profs = ei.profs_dict_from_db(db)
        v, m = 0.0, {}
        try:
            import metaheuristics as meta  # type: ignore
            v, m = meta.compute_soft(obj, profs)
        except Exception:
            pass
        sid = ei.import_solution_into_db(
            db, obj, name=file.filename or "uploaded",
            kind="imported", obj_value=float(v),
            metrics=m, make_active=True,
        )
        return {"ok": True, "imported": "solution",
                "solution_id": sid, "obj_value": v, "metrics": m}
    raise HTTPException(400, f"unknown kind {kind}")


@router.post("/clear")
def clear_database(scope: str = "all", db: Session = Depends(get_db)):
    """Wipe DB tables; scope = all / solutions / assignments."""
    if scope == "solutions":
        db.query(models.Lesson).delete()
        db.query(models.DayCount).delete()
        db.query(models.Solution).delete()
        db.commit()
        return {"ok": True}
    if scope == "assignments":
        db.query(models.Assignment).delete()
        db.commit()
        return {"ok": True}
    if scope == "all":
        for tbl in (
            models.Lesson, models.DayCount, models.Solution,
            models.Assignment,
            models.ClassroomSubjectPreference,
            models.ClassroomClassPreference,
            models.ClassroomUnavailability,
            models.Classroom,
            models.CoTeachingRule,
            models.ClassSubject, models.SchoolClass,
            models.TeacherSubject, models.TeacherUnavailability,
            models.TeacherMandatoryFreeDay,
            models.TeacherCompatibleClass,
            models.Teacher,
            models.SubjectGroupWeight, models.Subject,
            models.RunLog, models.Run,
        ):
            db.query(tbl).delete()
        db.commit()
        return {"ok": True}
    raise HTTPException(400, f"unknown scope {scope}")
