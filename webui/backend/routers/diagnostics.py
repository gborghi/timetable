"""Diagnostic endpoints used by the new /diagnostics tab and by the
inline pre-check in the Workflow card.

Each handler is intentionally thin: it builds the inputs, calls the
matching `experiments/diagnostics/*.py` module, and returns the
structured report as JSON. No database mutation.
"""
from __future__ import annotations

import os
import sys
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db


router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])


# Make the experiments/ package importable
_HERE = os.path.dirname(os.path.abspath(__file__))
_EXPERIMENTS = os.path.normpath(os.path.join(_HERE, "..", "..", "..",
                                              "experiments"))
if _EXPERIMENTS not in sys.path:
    sys.path.insert(0, _EXPERIMENTS)


# ---------- Hall ----------

class HallCheckIn(BaseModel):
    n_samples: int = 256
    teacher_max_hours: int = 18


@router.post("/hall-check")
def hall_check(payload: HallCheckIn,
               db: Session = Depends(get_db)):
    from diagnostics import hall_check as hc  # type: ignore
    return hc.hall_check_from_db(
        db, n_samples=payload.n_samples,
        teacher_max_hours=payload.teacher_max_hours,
    )


# ---------- Monte Carlo sensitivity ----------

class MonteCarloIn(BaseModel):
    n_samples: int = Field(100, ge=1, le=1000)
    seed: int = 0


@router.post("/montecarlo")
def montecarlo(payload: MonteCarloIn,
               db: Session = Depends(get_db)):
    from diagnostics import montecarlo_sensitivity as mc  # type: ignore
    return mc.run_montecarlo_from_db(
        db, n_samples=payload.n_samples, seed=payload.seed,
    )


# ---------- Bipartite analysis (modularity / betweenness / density) ----------

class BipartiteIn(BaseModel):
    mode: str = "classes"  # 'classes' | 'teachers'


@router.post("/bipartite")
def bipartite(payload: BipartiteIn,
              db: Session = Depends(get_db)):
    from diagnostics import bipartite_analysis as ba  # type: ignore
    return ba.analyze_from_db(db, mode=payload.mode)


# ---------- Correlations + regressions ----------

@router.post("/correlations")
def correlations(db: Session = Depends(get_db)):
    from diagnostics import correlations as co  # type: ignore
    return co.run_from_db(db)


# ---------- Distributions ----------

@router.post("/distributions")
def distributions(db: Session = Depends(get_db)):
    from diagnostics import distributions as ds  # type: ignore
    return ds.run_from_db(db)
