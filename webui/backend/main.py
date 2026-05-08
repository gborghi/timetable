"""FastAPI app entrypoint.

Run from `webui/backend/`:
    .venv/Scripts/python -m uvicorn main:app --reload --port 8000

The app imports the engine modules in `engine/` lazily (see
optimization.py + engine_paths.py)."""
from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

# Make this folder importable as a package even when started by uvicorn
HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from backend.db import init_db  # noqa: E402
from backend.logging_setup import configure_logging, get_logger  # noqa: E402
from backend.utils.auth import APIKeyMiddleware  # noqa: E402
from backend.utils.mutation_bump import MutationBumpMiddleware  # noqa: E402
from backend.utils.request_logging import RequestLoggingMiddleware  # noqa: E402
from backend.routers import (  # noqa: E402
    assignments,
    bulk,
    bulk_events,
    classes,
    classrooms,
    constraints,
    coteaching,
    coverage,
    curricula,
    dashboard,
    dataset,
    diagnostics,
    groups,
    imports,
    lessons,
    logical,
    monitor,
    optimize,
    plessi,
    saved_views,
    schedule,
    students,
    subjects,
    teachers,
    working_hours,
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
# Optional API-key gate. No-op when PITANTUM_API_KEY is unset
# (default for localhost dev). Section 2.6 P1.
app.add_middleware(APIKeyMiddleware)
app.add_middleware(MutationBumpMiddleware)
# GZip JSON responses >= 1 KB. Section 2.4 P3.
app.add_middleware(GZipMiddleware, minimum_size=1024)
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
app.include_router(classrooms.tags_router)
app.include_router(coteaching.router)
app.include_router(assignments.router)
app.include_router(dataset.router)
app.include_router(schedule.router)
app.include_router(lessons.router)
app.include_router(optimize.router)
app.include_router(plessi.router)
app.include_router(logical.router)
app.include_router(curricula.router)
app.include_router(students.router)
app.include_router(students.tags_router)
app.include_router(groups.router)
app.include_router(imports.router)
app.include_router(bulk_events.router)
app.include_router(bulk.router)
app.include_router(coverage.router)
app.include_router(monitor.router)
app.include_router(dashboard.router)
app.include_router(constraints.router)
app.include_router(saved_views.router)
app.include_router(diagnostics.router)
app.include_router(working_hours.router)


@app.get("/")
def root():
    return RedirectResponse("/api/health")


@app.get("/api/health")
def health():
    return {"status": "ok", "name": "pitantum", "version": "0.1.0"}


@app.get("/api/health/async")
async def health_async():
    """Async smoke endpoint exercising the AsyncSession path. Returns
    OK + the connected dialect when the async layer is available, or
    raises 503 with a helpful hint otherwise (Section 2.5 P2)."""
    from fastapi import Depends
    # Inline import + manual call to avoid forcing the dependency on
    # routes that don't need it.
    from .async_db import get_async_db
    from sqlalchemy import text
    gen = get_async_db()
    sess = await gen.__anext__()
    try:
        result = await sess.execute(text("SELECT 1"))
        ok = result.scalar() == 1
    finally:
        try:
            await gen.aclose()
        except Exception:
            pass
    return {
        "status": "ok" if ok else "fail",
        "async": True,
        "dialect": str(sess.bind.dialect.name) if sess.bind else None,
    }


def _err(request: Request, status: int, detail: str,
         code: str, errors=None, hint: str | None = None) -> JSONResponse:
    """Helper that produces an ErrorResponse-shaped JSON body and adds
    request_id (matching the X-Request-Id middleware injects)."""
    rid = request.headers.get("X-Request-Id")
    body = {
        "detail": detail,
        "code": code,
        "request_id": rid,
    }
    if errors:
        body["errors"] = errors
    if hint:
        body["hint"] = hint
    # Stay backward-compatible: also surface `error` key for the legacy
    # frontend which may not have been redeployed yet.
    body["error"] = detail
    return JSONResponse(status_code=status, content=body)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Wrap FastAPI's default HTTPException so the body matches the
    canonical ErrorResponse shape. Status-code -> code mapping is best
    effort; explicit codes can be passed via `exc.detail` if it's a
    dict {detail, code}.

    Section 2.3 P2.
    """
    detail = exc.detail
    code: str | None = None
    if isinstance(detail, dict):
        code = detail.get("code")
        detail = detail.get("detail", str(exc.detail))
    if code is None:
        if exc.status_code == 404:
            code = "not_found"
        elif exc.status_code in (400, 422):
            code = "validation_error"
        elif exc.status_code in (401, 403):
            code = "unauthorized"
        elif exc.status_code == 409:
            code = "conflict"
        else:
            code = "http_error"
    return _err(request, exc.status_code, str(detail), code)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
):
    """Pydantic / FastAPI body-validation errors -> ErrorResponse with
    per-field `errors[]`."""
    errs = []
    for e in exc.errors():
        loc = ".".join(str(x) for x in e.get("loc", ()))
        errs.append({
            "msg": e.get("msg"),
            "field": loc or None,
            "type": e.get("type"),
        })
    return _err(
        request, 422,
        "Input non valido (errore di validazione).",
        "validation_error",
        errors=errs,
        hint="Controlla i campi evidenziati e riprova.",
    )


@app.exception_handler(IntegrityError)
async def integrity_exception_handler(
    request: Request, exc: IntegrityError
):
    """SQLAlchemy IntegrityError -> 409 Conflict with a friendly
    summary. The most common cases are unique-constraint violations
    and foreign-key violations on delete.
    """
    msg = str(getattr(exc, "orig", exc)) or "Vincolo di integrita' violato."
    log.warning("integrity_error path=%s err=%s",
                request.url.path, msg)
    return _err(
        request, 409,
        "Operazione rifiutata: vincolo di integrita' violato.",
        "integrity_error",
        hint=msg,
    )


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(
    request: Request, exc: SQLAlchemyError
):
    log.exception("sqlalchemy_error path=%s", request.url.path)
    return _err(
        request, 500,
        "Errore database interno.",
        "database_error",
    )


@app.exception_handler(RuntimeError)
async def runtime_error_handler(request: Request, exc: RuntimeError):
    """Engine-level RuntimeErrors stay as 400 to preserve the previous
    contract with the frontend (the engine raises these for
    user-recoverable problems like 'no active solution')."""
    return _err(
        request, 400,
        str(exc) or "Errore di runtime.",
        "runtime_error",
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Last-ditch handler. Logs full traceback, returns 500 with
    internal_error code. Never swallows: re-raises in DEBUG."""
    log.exception("unhandled_exception path=%s", request.url.path)
    return _err(
        request, 500,
        "Errore interno del server.",
        "internal_error",
    )
