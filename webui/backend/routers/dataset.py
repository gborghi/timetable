"""Dataset import / mock generation / state inspection."""
from __future__ import annotations

import os
import pickle
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .. import models, schemas, optimization, engine_io
from ..db import get_db
from ..services.dataset_state import compute_state
from ..utils.ttl_cache import cached as ttl_cached

router = APIRouter(prefix="/api/dataset", tags=["dataset"])


@router.get("/state")
def get_state(db: Session = Depends(get_db)):
    """Always-fresh: 9 COUNT queries on indexed tables, <5ms even on
    superhuge. Originally TTL-cached 30s to reduce poll cost (Section
    2.4 P1) but the cache occasionally served stale snapshots after
    background-thread imports (run_manager._runner writes outside the
    request lifecycle, so the MutationBumpMiddleware doesn't see those
    writes). Polling 1-2x/s adds <20ms/s of backend CPU which is
    irrelevant for single-user dev. Cache-Control: no-store also
    forbids browser/proxy caching."""
    return JSONResponse(
        content=compute_state(db),
        headers={"Cache-Control": "no-store, max-age=0"},
    )


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


def _engine_scripts_dir() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(
        os.path.join(here, "..", "..", "..", "engine", "scripts")
    )


def _resolve_profile_pkl(name: str, filename: str) -> str | None:
    """Return the absolute path to ``filename`` for the given profile,
    or ``None`` if not found. Tries the canonical post-rename layout
    (``engine/scripts/data/<profile>/<filename>``) first, then falls
    back to the flat legacy layout (``engine/scripts/<filename>``)
    for older checkouts.

    Solutions written by run_*_pipeline.py are stored under
    ``engine/scripts/output/<profile>/`` -- callers looking for a
    solution_*.pkl should pass ``filename`` rooted at "output/...".
    The function understands both data/ and output/ subdirs.
    """
    base = _engine_scripts_dir()
    for candidate in (
        os.path.join(base, "data", name, filename),
        os.path.join(base, "output", name, filename),
        os.path.join(base, filename),
    ):
        if os.path.exists(candidate):
            return candidate
    return None


@router.post("/import-profile")
def import_profile(payload: schemas.ImportPickleIn):
    school_pkl = _resolve_profile_pkl(
        payload.profile, f"school_{payload.profile}.pkl")
    if not school_pkl:
        raise HTTPException(
            404,
            f"school_{payload.profile}.pkl not found "
            f"(searched engine/scripts/data/{payload.profile}/, "
            f"engine/scripts/output/{payload.profile}/, "
            f"engine/scripts/)"
        )
    run_id = optimization.import_engine_profile(
        payload.profile, payload.use_optimized,
        import_curricula=payload.import_curricula,
        import_classrooms=payload.import_classrooms,
        import_students=payload.import_students,
        students_seed=payload.students_seed,
    )
    return {"run_id": run_id}


@router.get("/available-profiles")
def list_profiles():
    profiles = []
    for name in ("small", "medium", "big", "huge", "superhuge", "mega"):
        school = _resolve_profile_pkl(name, f"school_{name}.pkl")
        if not school:
            continue
        has_profs = _resolve_profile_pkl(name, f"profs_{name}.pkl") is not None
        # MEGA's pipeline (run_mega_pipeline.py) writes
        # solution_mega_temporal_alns.pkl (final ALNS-polished) and
        # solution_temporal_mega.pkl (pre-ALNS); other profiles use the
        # canonical solution_timetable_<name>_{optimized,decomposed}.pkl
        # naming. Detect either form, in either layout.
        has_opt = (
            _resolve_profile_pkl(
                name, f"solution_timetable_{name}_optimized.pkl") is not None
            or _resolve_profile_pkl(
                name, f"solution_{name}_temporal_alns.pkl") is not None
        )
        has_dec = (
            _resolve_profile_pkl(
                name, f"solution_timetable_{name}_decomposed.pkl") is not None
            or _resolve_profile_pkl(
                name, f"solution_temporal_{name}.pkl") is not None
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
