"""Middleware that auto-bumps the global mutation counter after any
successful mutation request (POST / PUT / PATCH / DELETE returning 2xx).

Used by ttl_cache.cached(..., mutation_aware=True) to invalidate
cached read-only responses as soon as something changes.
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .ttl_cache import bump_mutation

_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class MutationBumpMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        if (request.method in _MUTATING_METHODS
                and 200 <= response.status_code < 300):
            # Skip GET-shaped writes and SSE/streaming endpoints (they
            # don't materially change cached read counters in piTantum).
            path = request.url.path
            if not path.startswith("/api/optimize/runs/"):
                bump_mutation()
        return response
