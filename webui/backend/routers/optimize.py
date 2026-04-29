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


@router.get("/runs")
def list_runs(limit: int = 50, db: Session = Depends(get_db)):
    rows = db.query(models.Run).order_by(
        models.Run.id.desc()
    ).limit(limit).all()
    out = []
    for r in rows:
        try:
            params = json.loads(r.params_json or "{}")
        except Exception:
            params = {}
        try:
            metrics = json.loads(r.metrics_json or "{}")
        except Exception:
            metrics = {}
        out.append({
            "id": r.id, "kind": r.kind, "name": r.name,
            "profile": r.profile, "params": params,
            "status": r.status, "progress": r.progress,
            "obj_value": r.obj_value, "metrics": metrics,
            "error": r.error,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "solution_id": r.solution_id,
        })
    return out


@router.get("/runs/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db)):
    r = db.get(models.Run, run_id)
    if r is None:
        raise HTTPException(404, "run not found")
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
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "solution_id": r.solution_id,
    }


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
    )
    return {"run_id": rid}


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
    )
    return {"run_id": rid}


@router.post("/full-pipeline")
def launch_full(payload: schemas.FullPipelineIn):
    rid = optimization.run_full_pipeline(
        profile=payload.profile,
        time_assign=payload.time_assign,
        phase_b_kwargs=payload.phase_b.model_dump(),
        budget_lns=payload.budget_lns,
        budget_sa=payload.budget_sa,
        budget_ts=payload.budget_ts,
        budget_ils=payload.budget_ils,
        workers=payload.workers,
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


# Catch-all meta stage route LAST so that explicit routes above match
# first (otherwise /rooms would be parsed as stage="rooms").
@router.post("/meta/{stage}")
def launch_meta(stage: str, payload: schemas.MetaRunIn):
    if stage not in ("lns", "sa", "ts", "ils"):
        raise HTTPException(400, f"unknown stage {stage}")
    rid = optimization.run_meta(
        stage,
        budget_s=payload.budget_s,
        workers=payload.workers, log=payload.log,
        n_cycles=payload.n_cycles,
        ts_budget_per_cycle=payload.ts_budget_per_cycle,
        sa_T0=payload.sa_T0, sa_alpha=payload.sa_alpha,
        tabu_size=payload.tabu_size,
    )
    return {"run_id": rid}
