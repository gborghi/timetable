"""Dashboard endpoints: dataset state already lives in routers/dataset.py;
this router hosts the `/api/dashboard/graph` endpoint that powers the
Network panel."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..services.graph import build_graph
from ..utils.ttl_cache import cached as ttl_cached

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/graph")
def get_graph(
    mode: str = Query(
        "classes",
        description=(
            "'classes' -> nodes are SchoolClass, edges weighted by shared "
            "teachers; 'teachers' -> nodes are Teacher, edges weighted by "
            "shared classes."
        ),
        pattern="^(classes|teachers)$",
    ),
    db: Session = Depends(get_db),
):
    """Network graph. Server-side cache 60s + mutation-aware; plus
    Cache-Control: no-store on response so the browser never serves a
    stale frame after an import."""
    try:
        body = ttl_cached(
            f"dashboard.graph.{mode}",
            ttl_s=60.0,
            mutation_aware=True,
            compute=lambda: build_graph(db, mode),
        )
        return JSONResponse(
            content=body,
            headers={"Cache-Control": "no-store, max-age=0"},
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
