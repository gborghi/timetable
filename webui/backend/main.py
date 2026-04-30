"""FastAPI app entrypoint.

Run from `webui/backend/`:
    .venv/Scripts/python -m uvicorn main:app --reload --port 8000

The app imports the engine modules in `experiments/` lazily (see
optimization.py + engine_paths.py)."""
from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

# Make this folder importable as a package even when started by uvicorn
HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from backend.db import init_db  # noqa: E402
from backend.logging_setup import configure_logging, get_logger  # noqa: E402
from backend.utils.request_logging import RequestLoggingMiddleware  # noqa: E402
from backend.routers import (  # noqa: E402
    assignments,
    bulk,
    classes,
    classrooms,
    coteaching,
    coverage,
    curricula,
    dataset,
    groups,
    imports,
    logical,
    monitor,
    optimize,
    schedule,
    students,
    subjects,
    teachers,
)

configure_logging()
log = get_logger("pitantum.main")


def _cors_allow_origins() -> list[str]:
    """CORS allow_origins. Defaults to localhost dev (127.0.0.1:5173 +
    localhost:5173). Override via env var `PITANTUM_CORS_ORIGINS` as a
    comma-separated list, or set to '*' to keep the legacy wildcard.

    Section 2.6 P1 of docs/improvements.md: restringere CORS al dev
    frontend invece di '*'.
    """
    env = os.environ.get("PITANTUM_CORS_ORIGINS")
    if env:
        return [s.strip() for s in env.split(",") if s.strip()]
    return [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:4173",
        "http://localhost:4173",
    ]


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("backend startup -- init_db()")
    init_db()
    log.info("backend ready")
    yield
    log.info("backend shutdown")


app = FastAPI(
    title="piTantum - Timetable API",
    description=(
        "piTantum (Tempus Tantum) -- "
        "Omnia, Lucili, aliena sunt, tempus tantum nostrum est. "
        "(Seneca, Ep. I,1)\n\n"
        "API REST per la gestione e l'ottimizzazione dell'orario scolastico."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(teachers.router)
app.include_router(classes.router)
app.include_router(subjects.router)
app.include_router(classrooms.router)
app.include_router(coteaching.router)
app.include_router(assignments.router)
app.include_router(dataset.router)
app.include_router(schedule.router)
app.include_router(optimize.router)
app.include_router(logical.router)
app.include_router(curricula.router)
app.include_router(students.router)
app.include_router(groups.router)
app.include_router(imports.router)
app.include_router(bulk.router)
app.include_router(coverage.router)
app.include_router(monitor.router)


@app.get("/")
def root():
    return RedirectResponse("/api/health")


@app.get("/api/health")
def health():
    return {"status": "ok", "name": "pitantum", "version": "0.1.0"}


@app.exception_handler(RuntimeError)
async def runtime_error_handler(request, exc: RuntimeError):
    return JSONResponse(
        status_code=400,
        content={"error": str(exc)},
    )
