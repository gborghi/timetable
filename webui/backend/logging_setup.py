"""Centralised logging configuration for the backend.

The backend has two distinct log channels:

  1. **Engine -> SSE protocol** (run_manager.capture_stdout): the
     `print()` calls in `optimization.py` feed the live log stream the
     frontend's RunLogPanel polls via `/api/optimize/runs/<id>/log`.
     These are intentional and stay as `print()` (changing them to
     `logging` would silently break the frontend log panel).

  2. **Infrastructure / request logs**: everything else
     (request access log, DB migration messages, lifespan events,
     unexpected exceptions). These use the standard `logging` module
     configured here.

Set the env var `PITANTUM_LOG_LEVEL` to override the default INFO.
Set `PITANTUM_LOG_JSON=1` to switch the formatter to a single-line
JSON record (useful when shipping logs to Loki / CloudWatch).
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time

_LEVEL = os.environ.get("PITANTUM_LOG_LEVEL", "INFO").upper()
_JSON = os.environ.get("PITANTUM_LOG_JSON", "0") == "1"


class _JsonFormatter(logging.Formatter):
    """Compact one-line JSON formatter for structured log shipping."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S",
                                time.gmtime(record.created)),
            "lvl": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # Surface any "extra" structured fields attached to the record.
        for k, v in record.__dict__.items():
            if k in ("args", "msg", "levelname", "levelno", "pathname",
                     "filename", "module", "exc_info", "exc_text",
                     "stack_info", "lineno", "funcName", "created",
                     "msecs", "relativeCreated", "thread", "threadName",
                     "processName", "process", "name"):
                continue
            try:
                json.dumps(v)
            except TypeError:
                v = str(v)
            payload[k] = v
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging() -> None:
    """Idempotent: safe to call multiple times. Replaces any existing
    handlers on the root logger with a single stdout handler."""
    root = logging.getLogger()
    if getattr(root, "_pitantum_configured", False):
        return
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(sys.stdout)
    if _JSON:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            fmt=("%(asctime)s %(levelname)-7s %(name)-22s "
                 "%(message)s"),
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
    root.addHandler(handler)
    root.setLevel(_LEVEL)
    # Tame uvicorn's noisy default access log -- RequestLoggingMiddleware
    # produces the structured per-request log we want.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    root._pitantum_configured = True   # type: ignore[attr-defined]


def get_logger(name: str) -> logging.Logger:
    """Convenience wrapper. Does NOT auto-call configure_logging() so
    callers can decide; main.py calls configure_logging() during the
    lifespan startup."""
    return logging.getLogger(name)
