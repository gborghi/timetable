"""Run launching + SSE log streaming."""
from __future__ import annotations

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
        "current_step": getattr(r, "current_step", None),
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


@router.get("/decomposition/recommend")
def recommend_decomposition(db: Session = Depends(get_db)):
    """Synchronous diagnostic that suggests the best decomposition
    strategy for the current school. Returns a JSON with the
    primary strategy ('spectral', 'metis', 'curriculum'), a flag
    for combining with the temporal decomposition, the measured
    modularity and density of the bipartite graph, and a
    human-readable motivation.

    Used by the frontend to show a "Suggerimento" tooltip in the
    Workflow tab next to the decomposition cards.
    """
    import sys, os
    sys.path.insert(0, os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "engine"))
    try:
        from decomposition_auto import auto_detect_decomposition_strategy
    except ImportError as e:
        raise HTTPException(500, f"decomposition_auto not importable: {e}")
    # Build the profs dict from Assignment rows (one row per teacher-
    # class-subject triple). The decomposition heuristic only needs
    # the per-teacher class membership, so we collapse over subjects.
    profs = {}
    rows = (db.query(models.Assignment, models.Teacher, models.SchoolClass)
              .join(models.Teacher,
                    models.Teacher.id == models.Assignment.teacher_id)
              .join(models.SchoolClass,
                    models.SchoolClass.id == models.Assignment.class_id)
              .all())
    for _a, t, cl in rows:
        # Stable, human-readable key. Falls back to the teacher id
        # so two homonyms cannot collapse onto the same node.
        last = (t.last_name or "").strip()
        first = (t.first_name or "").strip()
        if last or first:
            key = f"{last}_{first}".strip("_")
        else:
            key = f"teacher_{t.id}"
        profs.setdefault(key, {"classi": []})
        profs[key]["classi"].append(cl.name)
    for v in profs.values():
        v["classi"] = sorted(set(v["classi"]))
    if not profs:
        raise HTTPException(
            409,
            "no teacher-class assignments yet -- run Phase A first")
    rec = auto_detect_decomposition_strategy(profs)
    return rec.to_dict()


@router.post("/decomposition/{method}")
def launch_decomposition(method: str, payload: dict | None = None):
    """Launch a decomposition-driven Phase B run.

    method is one of: spectral, temporal, metis, curriculum,
    combined.
    - spectral: delegates to the standard Phase B pipeline (the
      existing /optimize/phase-b endpoint already handles the
      spectral path through `use_decomposition=True`).
    - temporal: master CP-SAT (cv2.solve_phase_a) + 6 day-solvers
      in ProcessPoolExecutor (cv2.solve_phase_b_for_day per day).
      Optional ALNS finishing.
    - metis, curriculum: partitioning logic implemented; solve
      loop wiring to cpsat_v2_timetable still pending (501 with
      explicit roadmap hint).
    - combined: spectral + temporal pipeline (501 today).
    """
    if method not in ("spectral", "temporal", "metis",
                      "curriculum", "combined"):
        raise HTTPException(400, f"unknown method '{method}'")
    body = payload or {}
    if method == "spectral":
        # Spectral runs through the standard /optimize/phase-b
        # endpoint. The flag use_decomposition=true on that
        # endpoint enables exactly the spectral path (the
        # historical implementation, see run_phase_b in
        # optimization.py). We forward the user there with a
        # short JSON hint instead of returning 501.
        return {
            "redirect": "/api/optimize/phase-b",
            "hint": ("Use POST /api/optimize/phase-b with "
                     "use_decomposition=true to run the spectral "
                     "decomposition. This endpoint is preserved "
                     "for compatibility."),
        }
    if method == "temporal":
        rid = optimization.run_decomposition_temporal(
            time_a=float(body.get("time_a", 60.0)),
            time_day=float(body.get("time_day", 30.0)),
            n_workers=body.get("n_workers"),
            cpsat_workers_per_day=int(body.get("cpsat_workers_per_day", 2)),
            parallel=bool(body.get("parallel", True)),
            enforce_no_holes=bool(body.get("enforce_no_holes", True)),
            run_alns=bool(body.get("run_alns", False)),
            alns_budget_s=float(body.get("alns_budget_s", 300.0)),
            alns_T0=float(body.get("alns_T0", 5.0)),
            alns_alpha=float(body.get("alns_alpha", 0.995)),
        )
        return {"run_id": rid}
    if method == "metis":
        rid = optimization.run_decomposition_metis(
            time_a=float(body.get("time_a", 60.0)),
            time_bridges=float(body.get("time_bridges", 30.0)),
            time_per_cluster=float(body.get("time_per_cluster", 30.0)),
            time_ricucitura=float(body.get("time_ricucitura", 60.0)),
            time_mono=float(body.get("time_mono", 120.0)),
            workers=int(body.get("workers", 8)),
            k=body.get("k"),
            imbalance=float(body.get("imbalance", 1.05)),
            run_alns=bool(body.get("run_alns", False)),
            alns_budget_s=float(body.get("alns_budget_s", 300.0)),
        )
        return {"run_id": rid}
    if method == "curriculum":
        rid = optimization.run_decomposition_curriculum(
            time_a=float(body.get("time_a", 60.0)),
            time_bridges=float(body.get("time_bridges", 30.0)),
            time_per_cluster=float(body.get("time_per_cluster", 30.0)),
            time_ricucitura=float(body.get("time_ricucitura", 60.0)),
            time_mono=float(body.get("time_mono", 120.0)),
            workers=int(body.get("workers", 8)),
            manual_groupings=body.get("manual_groupings"),
            min_cluster_size=int(body.get("min_cluster_size", 3)),
            run_alns=bool(body.get("run_alns", False)),
            alns_budget_s=float(body.get("alns_budget_s", 300.0)),
        )
        return {"run_id": rid}
    if method == "combined":
        # Combined isn't a separate orchestrator: the user enables
        # both spectral (in phase_b) and temporal as separate
        # pipeline steps. We surface that as a hint, not as a 501.
        return {
            "hint": ("Combined non e' un orchestrator dedicato. "
                     "Per spectral + temporal, ticka entrambi gli "
                     "step nella card Pipeline (decomp_spectral + "
                     "decomp_temporal). Vedi "
                     "docs/optimization_strategies.md, sezione "
                     "'Pipeline a piu' stadi'."),
        }
    raise HTTPException(400, f"unknown method '{method}'")


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


@router.get("/scenario-presets")
def list_scenario_presets():
    """Named Phase-B scenario configurations. The engine is general; this
    catalogue tells a school which scope/phase_a_mode combination fits its
    staff so it doesn't hit the default 'day'+'always' trap on a part-time
    or inclusive school (finding 20). The frontend renders it as a radio
    list and copies the chosen `params` into the Phase-B run payload."""
    return optimization.SCENARIO_PRESETS


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
        cp_sat_scope=payload.cp_sat_scope,
        phase_a_mode=payload.phase_a_mode,
        respect_room_capacity=payload.respect_room_capacity,
        thoroughness=payload.thoroughness,
        joint_vars=(payload.joint_vars.model_dump()
                    if payload.joint_vars else None),
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
    """Async: starts a Column Generation alternative-Phase-B run.

    All fields of ColumnGenerationIn are forwarded to the engine.
    `mode` selects iterative-diversified vs real branch-and-price;
    `granularity` picks the BP sub-problem unit (see schema).
    """
    rid = optimization.run_column_generation(
        time_budget_s=payload.time_budget_s,
        patterns_per_teacher=payload.patterns_per_teacher,
        mode=payload.mode,
        granularity=payload.granularity,
        branching_strategy=payload.branching_strategy,
        max_iterations=payload.max_iterations,
        bp_max_iterations=payload.bp_max_iterations,
        pricer_time_limit=payload.pricer_time_limit,
        pricer_workers=payload.pricer_workers,
        parallel=payload.parallel,
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
