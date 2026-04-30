"""Per-request structured logging middleware.

Logs one line per request with method, path, status, latency, and
client IP. Wires into FastAPI / Starlette's middleware chain.
"""
from __future__ import annotations

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("pitantum.access")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Logs request method, path, status, latency_ms, request_id.

    Adds an `X-Request-Id` header to the response so the frontend can
    show a server-side correlation id in errors.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex[:12]
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            logger.exception(
                "request_failed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "latency_ms": round(elapsed_ms, 1),
                },
            )
            raise
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        # Write structured log
        # Suppress access logs for the high-frequency health probe so the
        # console isn't drowned by it.
        path = request.url.path
        if path != "/api/health":
            logger.info(
                "request",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": path,
                    "status": response.status_code,
                    "latency_ms": round(elapsed_ms, 1),
                    "client": request.client.host if request.client else None,
                },
            )
        response.headers["X-Request-Id"] = request_id
        return response
