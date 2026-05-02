"""Diagnostic endpoints used by the /diagnostics tab and by the
inline pre-check in the Workflow card.

The HEAVY analyses (Monte Carlo, bipartite, correlations,
distributions) are now SPAWNED AS ASYNC RUNS (kind=diag_*) so
they show up in the /runs tab and don't block the FastAPI event
loop -- this fixes the "everything freezes when I launch Monte
Carlo" pathology.

The HALL pre-check stays synchronous because it's <100ms even on
superhuge schools.

Async diagnostics flow:
  1. POST /api/diagnostics/<x>     -> {run_id}
  2. Frontend polls /api/optimize/runs/<run_id> until status=='done'
  3. The result lives in run.metrics (the run_diagnostic_async
     helper stores the diagnostic dict there).
"""
from __future__ import annotations

import os
import sys

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import optimization
from ..db import get_db


router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])


# Make the experiments/ package importable
_HERE = os.path.dirname(os.path.abspath(__file__))
_EXPERIMENTS = os.path.normpath(os.path.join(_HERE, "..", "..", "..",
                                              "experiments"))
if _EXPERIMENTS not in sys.path:
    sys.path.insert(0, _EXPERIMENTS)


# ---------- Hall (async run by default, sync available) ----------

class HallCheckIn(BaseModel):
    n_samples: int = 256
    teacher_max_hours: int = 18
    sync: bool = False     # opt-in for the legacy <100ms inline path


@router.post("/hall-check")
def hall_check(payload: HallCheckIn,
               db: Session = Depends(get_db)):
    """By default Hall is now spawned as an async run (kind='diag_hall')
    so the result shows up in /runs alongside MC / bipartite /
    correlations / distributions.

    For UI surfaces that want the inline answer (e.g. the green/red
    pre-check button on the Phase A card), pass `sync=true` to get
    the diagnostic dict back directly without a run row.
    """
    if payload.sync:
        from diagnostics import hall_check as hc  # type: ignore
        return hc.hall_check_from_db(
            db, n_samples=payload.n_samples,
            teacher_max_hours=payload.teacher_max_hours,
        )
    rid = optimization.run_diag_hall_check(
        n_samples=payload.n_samples,
        teacher_max_hours=payload.teacher_max_hours,
    )
    return {"run_id": rid}


# ---------- Monte Carlo (async run) ----------

class MonteCarloIn(BaseModel):
    n_samples: int = Field(100, ge=1, le=1000)
    seed: int = 0


@router.post("/montecarlo")
def montecarlo(payload: MonteCarloIn):
    """Spawns kind='diag_montecarlo' run; result lives in metrics
    when status='done'."""
    rid = optimization.run_diag_montecarlo(
        n_samples=payload.n_samples, seed=payload.seed,
    )
    return {"run_id": rid}


# ---------- Bipartite analysis (async run) ----------

class BipartiteIn(BaseModel):
    mode: str = "classes"  # 'classes' | 'teachers'


@router.post("/bipartite")
def bipartite(payload: BipartiteIn):
    rid = optimization.run_diag_bipartite(mode=payload.mode)
    return {"run_id": rid}


# ---------- Correlations + regressions (async run) ----------

class CorrelationModel(BaseModel):
    kind: str = "ols"     # 'ols' | 'logit'
    scope: str = "teachers"
    x: str
    y: str
    label: str | None = None


class CorrelationsIn(BaseModel):
    models: list[CorrelationModel] | None = None


@router.post("/correlations")
def correlations(payload: CorrelationsIn | None = None):
    """Spawns a kind='diag_correlations' run.

    If `payload.models` is None or empty, uses the canonical
    3-model panel (back-compat). Otherwise the user chooses which
    regressions to run; see GET /api/diagnostics/correlations/variables
    for the menu of available x / y / scope combinations.
    """
    spec = None
    if payload and payload.models:
        spec = [m.model_dump() for m in payload.models]
    rid = optimization.run_diag_correlations(models_spec=spec)
    return {"run_id": rid}


@router.get("/correlations/variables")
def correlations_variables():
    """Variable picker metadata for the UI: which scopes exist,
    which variables can be picked as x or y for each scope, and
    what type each variable is (continuous / integer / binary
    drives whether OLS or Logit makes sense)."""
    from diagnostics import correlations as co  # type: ignore
    return co.available_variables()


# ---------- Distributions (async run, parametrizable) ----------

class DistributionsIn(BaseModel):
    include: list[str] | None = None
    params: dict[str, dict] | None = None


@router.post("/distributions")
def distributions(payload: DistributionsIn | None = None):
    """Spawns a kind='diag_distributions' run.

    The optional `payload` lets the user pick which distributions
    to compute and tweak per-distribution params:

      {include: ["teacher_loads", ...],
       params: {teacher_loads: {bins: 24}, ...}}

    See GET /api/diagnostics/distributions/menu for the catalog.
    """
    spec = None
    if payload and (payload.include or payload.params):
        spec = {
            "include": payload.include or [],
            "params": payload.params or {},
        }
    rid = optimization.run_diag_distributions(spec=spec)
    return {"run_id": rid}


@router.get("/distributions/menu")
def distributions_menu():
    """List of available distribution kinds + per-kind parameter
    metadata, for the UI form."""
    from diagnostics import distributions as ds  # type: ignore
    return ds.available_distributions()
