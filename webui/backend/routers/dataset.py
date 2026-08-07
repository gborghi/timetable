"""Dataset import / mock generation / state inspection."""
from __future__ import annotations

import logging
import os
import pickle
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .. import models, schemas, optimization, engine_io
from ..db import get_db
from ..services.dataset_state import compute_state

router = APIRouter(prefix="/api/dataset", tags=["dataset"])

log = logging.getLogger("pitantum.dataset")


# Upload-pickle is a known RCE surface (pickle.loads on untrusted
# bytes). It is disabled by default and only re-enabled by an explicit
# env flag plus a non-empty PITANTUM_API_KEY -- so the endpoint is
# never reachable anonymously and an operator has to consciously opt
# in for trusted, locally-uploaded pickles.
_UPLOAD_PICKLE_FLAG = "PITANTUM_ALLOW_PICKLE_UPLOAD"

# Hard cap on uploaded pickle payload size. 64 MiB covers the largest
# legitimate scenarios (mega-profile school dumps) while bounding the
# damage of a malicious / accidental over-large upload.
_UPLOAD_PICKLE_MAX_BYTES = 64 * 1024 * 1024


def _pickle_upload_enabled() -> bool:
    flag = os.environ.get(_UPLOAD_PICKLE_FLAG, "").strip().lower()
    if flag not in ("1", "true", "yes", "on"):
        return False
    # Require an API key to be configured -- never expose unauthenticated.
    return bool(os.environ.get("PITANTUM_API_KEY", "").strip())


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


def _resolve_profile_sqlite(name: str) -> str | None:
    """Path to the per-profile SQLite snapshot
    (``engine/scripts/data/<name>/<name>.sqlite``) or ``None``.

    This is the canonical solved-model source: ``import_engine_profile``
    prefers it, and it carries anagrafica + the constraint tables +
    WorkingDay/Slot + the solved Lessons in one file -- so a profile can
    exist as a ready-made "modello risolto" with no pickles at all."""
    return _resolve_profile_pkl(name, f"{name}.sqlite")


@router.post("/import-profile")
def import_profile(payload: schemas.ImportPickleIn):
    school_pkl = _resolve_profile_pkl(
        payload.profile, f"school_{payload.profile}.pkl")
    sqlite_snap = _resolve_profile_sqlite(payload.profile)
    if not school_pkl and not sqlite_snap:
        raise HTTPException(
            404,
            f"profilo '{payload.profile}' non trovato: né "
            f"{payload.profile}.sqlite né school_{payload.profile}.pkl "
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
    for name in ("small", "medium", "big", "huge", "superhuge", "mega",
                 "liceo60", "liceo90", "liceo90doc"):
        sqlite_snap = _resolve_profile_sqlite(name)
        school = _resolve_profile_pkl(name, f"school_{name}.pkl")
        if not school and not sqlite_snap:
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
        # A SQLite snapshot carries the solved Lessons in-DB (the
        # import copies the `solutions`+`lessons` tables), so it is a
        # ready-made solved model even with no solution pickle: surface
        # its assignments and solution as present.
        if sqlite_snap:
            has_profs = True
            has_opt = True
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
    """Upload a pickle file. `kind` is one of school/profs/solution.

    Disabled by default. `pickle.loads()` on user-controlled bytes is
    arbitrary code execution; the endpoint is only reachable when both
    PITANTUM_ALLOW_PICKLE_UPLOAD=1 *and* PITANTUM_API_KEY are set. Use
    the SQLite snapshot import path (engine_io.import_profile_sqlite_into_db,
    surfaced by /api/dashboard/import-db) for the safe equivalent.
    """
    if not _pickle_upload_enabled():
        raise HTTPException(
            403,
            "Endpoint disabilitato per motivi di sicurezza "
            "(pickle.loads esegue codice arbitrario). "
            "Usare /api/dashboard/import-db con uno snapshot SQLite. "
            "Per riabilitare in un contesto fidato: settare "
            f"{_UPLOAD_PICKLE_FLAG}=1 e PITANTUM_API_KEY.",
        )
    if kind not in ("school", "profs", "solution"):
        raise HTTPException(400, f"unknown kind {kind}")
    data = await file.read()
    if len(data) > _UPLOAD_PICKLE_MAX_BYTES:
        raise HTTPException(
            413,
            f"File troppo grande ({len(data)} bytes); "
            f"max {_UPLOAD_PICKLE_MAX_BYTES} bytes.",
        )
    log.warning(
        "pickle upload accepted kind=%s size=%d filename=%r",
        kind, len(data), file.filename,
    )
    try:
        obj = pickle.loads(data)  # noqa: S301 -- gated by env flag above
    except Exception as exc:
        raise HTTPException(400, f"Pickle non valido: {exc}") from exc
    headers = {"X-Pickle-Upload-Enabled": "true"}
    if kind == "school":
        engine_io.import_school_into_db(db, obj, replace=True)
        return JSONResponse(
            {"ok": True, "imported": "school",
             "n_classes": len(obj.get("classes", []))},
            headers=headers,
        )
    if kind == "profs":
        n = engine_io.import_profs_into_db(db, obj)
        return JSONResponse(
            {"ok": True, "imported": "profs", "n_assignments": n},
            headers=headers,
        )
    # solution
    from .. import engine_io as ei
    profs = ei.profs_dict_from_db(db)
    v, m = 0.0, {}
    try:
        import metaheuristics as meta  # type: ignore
        v, m = meta.compute_soft(obj, profs)
    except Exception:
        log.exception("metaheuristics.compute_soft failed for upload-pickle")
    sid = ei.import_solution_into_db(
        db, obj, name=file.filename or "uploaded",
        kind="imported", obj_value=float(v),
        metrics=m, make_active=True,
    )
    return JSONResponse(
        {"ok": True, "imported": "solution",
         "solution_id": sid, "obj_value": v, "metrics": m},
        headers=headers,
    )


@router.post("/clear")
def clear_database(scope: str = "all", db: Session = Depends(get_db)):
    """Wipe DB tables; scope = all / solutions / assignments."""
    from ..run_manager import active_run_count
    if active_run_count() > 0:
        raise HTTPException(
            409,
            {
                "detail": (
                    "Impossibile azzerare il database mentre ci sono run "
                    "attivi o in coda: potrebbe corrompere l'esecuzione in "
                    "corso. Attendere o annullare i run prima di procedere."
                ),
                "code": "runs_active",
            },
        )
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
