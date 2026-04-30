"""Optional API-key authentication.

Section 2.6 P1. Default: NO auth (single-user localhost). Enable by
setting the env var `PITANTUM_API_KEY` to a non-empty value; clients
must then send `X-API-Key: <value>` (or `Authorization: Bearer <value>`)
on every request to /api/*.

Routes exempted from the check (always reachable):
  - /api/health
  - / (root redirect)
  - /docs, /openapi.json, /redoc

When the env var is unset (default), the middleware is a no-op so
existing setups keep working with zero changes.
"""
from __future__ import annotations

import os
import secrets

from fastapi import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


_EXEMPT = {
    "/",
    "/api/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/favicon.ico",
}


def _expected_key() -> str | None:
    v = os.environ.get("PITANTUM_API_KEY", "")
    return v.strip() or None


class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        expected = _expected_key()
        # No key configured -> auth disabled, behave as before.
        if not expected:
            return await call_next(request)
        path = request.url.path
        # Exempt non-API paths (FastAPI docs, root) and health probes.
        if path in _EXEMPT or path.startswith("/static/"):
            return await call_next(request)
        if not path.startswith("/api/"):
            return await call_next(request)

        # CORS preflight should pass through without auth (the browser
        # doesn't include credentials on OPTIONS by default).
        if request.method == "OPTIONS":
            return await call_next(request)

        provided = request.headers.get("X-API-Key")
        if not provided:
            auth = request.headers.get("Authorization", "")
            if auth.lower().startswith("bearer "):
                provided = auth[7:].strip()

        if not provided or not secrets.compare_digest(provided, expected):
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "API key mancante o non valida.",
                    "code": "unauthorized",
                    "error": "API key mancante o non valida.",
                    "hint": "Includere l'header `X-API-Key: <chiave>` "
                            "su ogni chiamata API.",
                },
            )
        return await call_next(request)
