"""Run launching + SSE log streaming."""
from __future__ import annotations

import asyncio
import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from .. import models, schemas, optimization, run_manager
from ..db import get_db

router = APIRouter(prefix="/api/optimize", tags=["optimize"])


def _iso_utc(d):
    """Serialize a (potentially naive) datetime to an ISO 8601 string
    with explicit UTC timezone. The Run table stores naive datetimes
    coming from `datetime.utcnow()`; without this converter the
    frontend's `Date.parse` would interpret them as LOCAL time and
    skew elapsed-time computations by the user's UTC offset."""
    if d is None:
        return None
    import datetime as _dt
    if d.tzinfo is None:
        d = d.replace(tzinfo=_dt.timezone.utc)
    return d.isoformat()


def _serialize_run(r):
    try:
        params = json.loads(r.params_json or "{}")
    except Exception:
        params = {}
    try:
        metrics = json.loads(r.metrics_json or "{}")
    except Exception:
        metrics = {}
    return {
        "id": r.id, "kind": r.kind, "name": r.name,
        "profile": r.profile, "params": params,
        "status": r.status, "progress": r.progress,
        "obj_value": r.obj_value, "metrics": metrics,
        "error": r.error,
        "started_at": _iso_utc(r.started_at),
        "finished_at": _iso_utc(r.finished_at),
        "created_at": _iso_utc(r.created_at),
        "solution_id": r.solution_id,
    }


@router.get("/runs")
def list_runs(limit: int = 200,
              q: str | None = None,
              sort: str | None = None,
              db: Session = Depends(get_db)):
    """List runs. Supports the same DSL as the other tabs:
    - q='kind = phase_b AND status = done'
    - sort='-id' or 'kind:status,desc:-id'
    Default order is most-recent first (id desc) when no sort given.
    """
    rows = db.query(models.Run).order_by(
        models.Run.id.desc()
    ).limit(limit).all()
    out = [_serialize_run(r) for r in rows]
    if q or sort:
        from ..utils.list_query import filter_and_sort, QueryError
        try:
            out = filter_and_sort(out, "runs", q, sort)
        except QueryError as e:
            raise HTTPException(400, f"Errore query: {e}")
    return out


@router.get("/runs/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db)):
    r = db.get(models.Run, run_id)
    if r is None:
        raise HTTPException(404, "run not found")
    return _serialize_run(r)


from pydantic import BaseModel as _BM


class RunDeleteBatchIn(_BM):
    run_ids: list[int]


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: int, db: Session = Depends(get_db)):
    """Request cancellation of a running/pending run. The run row
    is flipped to status='cancelled' immediately. Cooperatively
    cancellable solvers stop ASAP; non-cooperative ones (raw
    CP-SAT) keep going until their time budget but no longer
    appear as active in the UI."""
    from .. import run_manager
    ok = run_manager.request_cancel(run_id)
    if not ok:
        # Either not found or already terminal
        r = db.get(models.Run, run_id)
        if r is None:
            raise HTTPException(404, "run non trovato")
        return {"ok": False,
                 "msg": f"run gia' in stato '{r.status}', no-op"}
    return {"ok": True}


@router.delete("/runs/{run_id}")
def delete_run(run_id: int, db: Session = Depends(get_db)):
    """Delete a single run row + all its log lines. The run thread (if
    still alive) is left to finish its work; we just remove the
    bookkeeping. Won't delete the produced Solution -- that lives in
    /api/schedule/solutions/{sid}."""
    r = db.get(models.Run, run_id)
    if r is None:
        raise HTTPException(404, "run not found")
    if r.status in ("running", "pending"):
        raise HTTPException(
            409,
            "Run ancora attivo: aspetta che finisca o falliscalo "
            "dal solver prima di cancellarlo."
        )
    # Cascade: delete log lines first (no FK CASCADE in the schema).
    db.query(models.RunLog).filter(
        models.RunLog.run_id == run_id
    ).delete(synchronize_session=False)
    db.delete(r)
    db.commit()
    return {"ok": True, "run_id": run_id}


@router.post("/runs/delete-batch")
def delete_runs_batch(payload: RunDeleteBatchIn,
                      db: Session = Depends(get_db)):
    """Bulk delete. Active runs are skipped (returned in `skipped_active`)
    so the caller can surface a partial-success message."""
    ids = [int(x) for x in payload.run_ids]
    if not ids:
        return {"ok": True, "deleted": 0, "skipped_active": []}
    rows = db.query(models.Run).filter(models.Run.id.in_(ids)).all()
    deletable = [r.id for r in rows if r.status not in ("running", "pending")]
    skipped = [r.id for r in rows if r.status in ("running", "pending")]
    if deletable:
        db.query(models.RunLog).filter(
            models.RunLog.run_id.in_(deletable)
        ).delete(synchronize_session=False)
        db.query(models.Run).filter(
            models.Run.id.in_(deletable)
        ).delete(synchronize_session=False)
        db.commit()
    return {"ok": True, "deleted": len(deletable),
            "skipped_active": skipped}


@router.get("/runs/{run_id}/telemetry")
def run_telemetry(run_id: int,
                   limit: int = 5000,
                   offset: int = 0,
                   phase: str | None = None):
    """Return the telemetry samples of a run.

    Each entry: `{step, timestamp_s, phase, payload: {...}}`.
    Payload keys depend on the producing stage and typically
    include `objective_value`, `hard_violations_count`,
    `placed_lessons_count`, `accepted_moves`, `temperature`, ...
    """
    from ..utils import telemetry as tel
    return {
        "run_id": run_id,
        "samples": tel.fetch_telemetry(run_id, limit=limit,
                                         offset=offset, phase=phase),
    }


@router.get("/runs/{run_id}/summary")
def run_summary_get(run_id: int):
    """Aggregated stats across all telemetry phases for a run."""
    from ..utils import telemetry as tel
    return tel.fetch_summary(run_id)


@router.get("/runs/{run_id}/log-text")
def get_run_log(run_id: int, db: Session = Depends(get_db)):
    rows = db.query(models.RunLog).filter(
        models.RunLog.run_id == run_id
    ).order_by(models.RunLog.seq).all()
    return {"lines": [r.text for r in rows]}


@router.get("/runs/{run_id}/stream")
async def stream(run_id: int):
    return EventSourceResponse(run_manager.stream_events(run_id, replay=True))


# ---------------- Launchers ----------------


@router.post("/assignment")
def launch_assignment(payload: schemas.AssignmentRunIn):
    rid = optimization.run_assignment(
        time_limit_s=payload.time_limit_s,
        workers=payload.workers, log=payload.log,
        criterion=payload.criterion,
        custom_expression=payload.custom_expression,
    )
    return {"run_id": rid}


# ---- Phase A criterion / DSL helpers ----


@router.get("/phase-a/presets",
            response_model=list[schemas.ObjectivePresetOut])
def list_phase_a_presets():
    """Return the catalogue of Phase-A optimisation presets the
    frontend renders as a radio list. Each preset carries a key, a
    label, a short user-facing summary and the underlying DSL
    expression so the user can inspect (or copy-paste it into the
    custom editor)."""
    from ..utils import objective_dsl
    return [
        {"key": k, "label": l, "summary": s, "expression": e}
        for (k, l, s, e) in objective_dsl.PRESETS
    ]


@router.post("/phase-a/validate-expression",
             response_model=schemas.ObjectiveValidateOut)
def validate_phase_a_expression(payload: schemas.ObjectiveValidateIn):
    """Live syntax / vocabulary validation of a custom Phase-A
    objective expression. Used by the frontend editor as the user
    types -- so they see "Espressione valida" or the specific error
    before launching a run."""
    from ..utils import objective_dsl
    res = objective_dsl.validate(payload.expression)
    return {
        "ok": res.ok,
        "direction": res.direction,
        "errors": res.errors,
    }


@router.post("/phase-b")
def launch_phase_b(payload: schemas.PhaseBRunIn):
    rid = optimization.run_phase_b(
        k=payload.k, time_a=payload.time_a,
        time_bridges=payload.time_bridges,
        time_cluster=payload.time_cluster,
        time_ricucitura=payload.time_ricucitura,
        time_mono=payload.time_mono,
        workers=payload.workers, log=payload.log,
        use_decomposition=payload.use_decomposition,
        optimize_rooms=payload.optimize_rooms,
        rooms_time_limit_s=payload.rooms_time_limit_s,
        rooms_prefer_home=payload.rooms_prefer_home,
    )
    return {"run_id": rid}


@router.post("/full-pipeline")
def launch_full(payload: schemas.FullPipelineIn):
    rid = optimization.run_full_pipeline(
        profile=payload.profile,
        steps=payload.steps,
        time_assign=payload.time_assign,
        phase_b_kwargs=payload.phase_b.model_dump(),
        budget_lns=payload.budget_lns,
        budget_sa=payload.budget_sa,
        budget_ts=payload.budget_ts,
        budget_ils=payload.budget_ils,
        workers=payload.workers,
        meta_optimize_rooms=payload.meta_optimize_rooms,
        meta_rooms_time_limit_s=payload.meta_rooms_time_limit_s,
        meta_rooms_prefer_home=payload.meta_rooms_prefer_home,
    )
    return {"run_id": rid}


@router.post("/place-event", response_model=schemas.PlaceEventOut)
def launch_place_event(payload: schemas.PlaceEventIn):
    """Place the lessons of the listed cattedre via the greedy
    HARD-feasible placer. See `optimization.run_place_event` for
    the lock_mode semantics."""
    if payload.lock_mode not in (
        "all_others_locked", "same_class_or_teacher_movable",
        "all_others_movable",
    ):
        raise HTTPException(400,
            f"lock_mode sconosciuto: {payload.lock_mode!r}")
    if not payload.event_ids:
        raise HTTPException(400, "event_ids non puo' essere vuoto")
    rid = optimization.run_place_event(
        event_ids=payload.event_ids,
        lock_mode=payload.lock_mode,
        prefer_pref=payload.prefer_pref,
    )
    return {"run_id": rid}


@router.post("/rooms")
def launch_rooms(payload: schemas.ClassroomAssignRunIn):
    rid = optimization.run_classroom_assignment(
        time_limit_s=payload.time_limit_s,
        workers=payload.workers, log=payload.log,
        prefer_home=payload.prefer_home,
    )
    return {"run_id": rid}


# ----- Diagnostics + specialised stages -----

@router.post("/hall-check")
def launch_hall_check(payload: schemas.HallCheckIn):
    """Synchronous: returns the Hall's theorem pre-check report."""
    return optimization.run_hall_check(
        n_samples=payload.n_samples,
        teacher_max_hours=payload.teacher_max_hours,
    )


@router.post("/column-generation")
def launch_column_generation(payload: schemas.ColumnGenerationIn):
    """Async: starts a Column Generation alternative-Phase-B run."""
    rid = optimization.run_column_generation(
        time_budget_s=payload.time_budget_s,
        patterns_per_teacher=payload.patterns_per_teacher,
        log=payload.log,
    )
    return {"run_id": rid}


# Catch-all meta stage route LAST so that explicit routes above match
# first (otherwise /rooms would be parsed as stage="rooms").
@router.post("/meta/{stage}")
def launch_meta(stage: str, payload: schemas.MetaRunIn):
    if stage not in ("lns", "sa", "ts", "ils", "alns", "vns",
                      "lagrangian"):
        raise HTTPException(400, f"unknown stage {stage}")
    rid = optimization.run_meta(
        stage,
        budget_s=payload.budget_s,
        workers=payload.workers, log=payload.log,
        n_cycles=payload.n_cycles,
        ts_budget_per_cycle=payload.ts_budget_per_cycle,
        sa_T0=payload.sa_T0, sa_alpha=payload.sa_alpha,
        tabu_size=payload.tabu_size,
        optimize_rooms=payload.optimize_rooms,
        rooms_time_limit_s=payload.rooms_time_limit_s,
        rooms_prefer_home=payload.rooms_prefer_home,
        alns_T0=payload.alns_T0,
        alns_alpha=payload.alns_alpha,
        alns_destroy=payload.alns_destroy,
        alns_repair=payload.alns_repair,
        vns_neighbourhoods=payload.vns_neighbourhoods,
        lagrangian_max_iter=payload.lagrangian_max_iter,
        lagrangian_tolerance=payload.lagrangian_tolerance,
        lagrangian_alpha_0=payload.lagrangian_alpha_0,
    )
    return {"run_id": rid}
