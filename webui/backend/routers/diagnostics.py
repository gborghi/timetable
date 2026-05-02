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


# ---------- Hall (sync, fast: < 100ms) ----------

class HallCheckIn(BaseModel):
    n_samples: int = 256
    teacher_max_hours: int = 18


@router.post("/hall-check")
def hall_check(payload: HallCheckIn,
               db: Session = Depends(get_db)):
    """Hall pre-check stays SYNC: it's <100ms and the user wants the
    answer immediately on the Phase A card."""
    from diagnostics import hall_check as hc  # type: ignore
    return hc.hall_check_from_db(
        db, n_samples=payload.n_samples,
        teacher_max_hours=payload.teacher_max_hours,
    )


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


# ---------- Distributions (async run) ----------

@router.post("/distributions")
def distributions():
    rid = optimization.run_diag_distributions()
    return {"run_id": rid}
