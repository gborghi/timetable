"""Dataset import / mock generation / state inspection."""
from __future__ import annotations

import logging
import os
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .. import models, schemas, optimization
from ..db import get_db
from ..services.dataset_state import compute_state

router = APIRouter(prefix="/api/dataset", tags=["dataset"])

log = logging.getLogger("pitantum.dataset")


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
