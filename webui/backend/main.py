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


def _is_production() -> bool:
    """True when PITANTUM_ENV is set to a production-like value.

    Used to gate fail-fast checks (CORS wildcard, missing API key) that
    are acceptable in local dev but must block startup in prod.
    """
    val = os.environ.get("PITANTUM_ENV", "").strip().lower()
    return val in ("prod", "production")


def _cors_allow_origins() -> list[str]:
    """CORS allow_origins. Defaults to localhost dev (127.0.0.1:5173 +
    localhost:5173). Override via env var `PITANTUM_CORS_ORIGINS` as a
    comma-separated list.

    Wildcard '*' is REFUSED when PITANTUM_ENV indicates production --
    combined with allow_credentials=False the wildcard was technically
    safe, but it widens the attack surface (any origin can issue
    requests to /api/optimize, /api/dataset/clear, etc.) for no good
    reason in a production deploy.
    """
    env = os.environ.get("PITANTUM_CORS_ORIGINS")
    if env:
        items = [s.strip() for s in env.split(",") if s.strip()]
        if "*" in items:
            if _is_production():
                raise RuntimeError(
                    "CORS wildcard '*' rifiutato in produzione. "
                    "Settare PITANTUM_CORS_ORIGINS con l'elenco "
                    "esplicito dei front-end ammessi."
                )
            log.warning(
                "CORS allow_origins contiene '*' -- accettato solo "
                "in dev/test; in produzione verra' rifiutato."
            )
        return items
    return [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:4173",
        "http://localhost:4173",
    ]


def _check_production_security() -> None:
    """Fail-fast checks at startup when PITANTUM_ENV=production.

    Refuse to boot if obvious production-security misconfigurations are
    present (no API key, debug-only flags enabled). Keeps the dev
    workflow untouched while preventing accidental deploy of an
    unauthenticated backend.
    """
    if not _is_production():
        return
    if not os.environ.get("PITANTUM_API_KEY", "").strip():
        raise RuntimeError(
            "PITANTUM_ENV=production ma PITANTUM_API_KEY non e' "
            "impostata. Rifiuto di avviare un backend senza "
            "autenticazione in produzione."
        )
    if os.environ.get("PITANTUM_ALLOW_PICKLE_UPLOAD", "").strip().lower() in (
        "1", "true", "yes", "on",
    ):
        # Warn loudly but don't block: an admin who really wants to
        # accept pickles in prod has to keep both flags set.
        log.warning(
            "PITANTUM_ALLOW_PICKLE_UPLOAD attivo in produzione. "
            "Questo endpoint esegue pickle.loads su input utente "
            "-- vulnerabilita RCE se non strettamente controllato."
        )
    if not os.environ.get("PITANTUM_CORS_ORIGINS", "").strip():
        raise RuntimeError(
            "PITANTUM_ENV=production ma PITANTUM_CORS_ORIGINS non e' "
            "impostato. Impostare l'elenco esplicito degli origin "
            "front-end ammessi invece di usare i default localhost."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("backend startup -- init_db()")
    _check_production_security()
    init_db()
    # Sweep runs left 'running'/'pending' by a previous crash/restart
    # into a terminal 'failed' state so they stop looking active
    # (undeletable ghosts with never-ending SSE streams).
    try:
        from backend.run_manager import reconcile_orphaned_runs
        reconcile_orphaned_runs()
    except Exception:
        log.exception("startup: orphan-run reconciliation failed")
    # Run state (log buffers, worker threads, cancel set, concurrency
    # semaphore) lives in THIS process's memory. A multi-worker deploy
    # (gunicorn -w >1) therefore breaks SSE log streaming, progress, and
    # cancellation for any request routed to a different worker than the
    # one running the solve. Scale with container replicas, each single
    # worker. Surface the constraint loudly; if we can tell we're under
    # gunicorn, warn harder (it may be misconfigured with >1 worker).
    if os.environ.get("SERVER_SOFTWARE", "").startswith("gunicorn"):
        log.warning(
            "running under gunicorn: the run orchestrator requires a "
            "SINGLE worker (-w 1). With -w >1, SSE log streaming and run "
            "cancellation break. Scale with container replicas instead."
        )
    else:
        log.info(
            "run orchestrator uses per-process state -- deploy single "
            "worker; scale with container replicas."
        )
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
# Single-tenant firewall: reject spoofed X-Tenant-Id headers universally
# while multi-tenant is disabled (the default). See tenant.py.
from backend.tenant import SingleTenantGuardMiddleware  # noqa: E402
app.add_middleware(SingleTenantGuardMiddleware)
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


# ── CSP (Content-Security-Policy) ──────────────────────────────────
class _CSPMiddleware:
    """Add a basic CSP header to every response.

    The policy is deliberately permissive (self-origin for scripts and
    styles; images and media from anywhere) because the deployed frontend
    is a static SPA.  Tighten ``PITANTUM_CSP`` via env var when a stricter
    policy is needed.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def _send(message):
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                if b"content-security-policy" not in headers:
                    csp = os.environ.get(
                        "PITANTUM_CSP",
                        "default-src 'self'; "
                        "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
                        "style-src 'self' 'unsafe-inline'; "
                        "img-src 'self' data: blob:; "
                        "font-src 'self' data:; "
                        "connect-src 'self'",
                    )
                    headers[b"content-security-policy"] = csp.encode()
                message["headers"] = list(headers.items())
            await send(message)

        await self.app(scope, receive, _send)


app.add_middleware(_CSPMiddleware)

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


_INTEGRITY_HINTS: tuple[tuple[str, str], ...] = (
    ("unique", "Valore gia' esistente: viola un vincolo di unicita'."),
    ("foreign key", "Riferimento mancante o ancora in uso (FK)."),
    ("not null", "Campo obbligatorio mancante."),
    ("check", "Valore fuori dai limiti consentiti."),
)


def _safe_integrity_hint(exc: IntegrityError) -> str:
    """Map a raw SQLAlchemy IntegrityError to a generic, user-facing
    hint. Never returns the raw `exc.orig` text -- that leaks schema
    details (table/column names, dialect, sometimes values in conflict)
    to the client.
    """
    raw = str(getattr(exc, "orig", "")).lower()
    for needle, hint in _INTEGRITY_HINTS:
        if needle in raw:
            return hint
    return "Vincolo di integrita' violato."


@app.exception_handler(IntegrityError)
async def integrity_exception_handler(
    request: Request, exc: IntegrityError
):
    """SQLAlchemy IntegrityError -> 409 Conflict. The raw exception is
    logged server-side (with full schema details) for debugging; the
    client receives only a generic hint mapped from the error
    category, never the underlying SQL or column names.
    """
    raw = str(getattr(exc, "orig", exc)) or "integrity error"
    log.warning("integrity_error path=%s err=%s",
                request.url.path, raw)
    return _err(
        request, 409,
        "Operazione rifiutata: vincolo di integrita' violato.",
        "integrity_error",
        hint=_safe_integrity_hint(exc),
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
