"""Async SQLAlchemy session factory.

Section 2.5 P2 of docs/improvements.md. Selective async layer wired
alongside the sync one. Used by read-mostly endpoints that don't need
the full ORM lifecycle (just `select(Model)` queries).

The async URL is derived automatically from the sync `DB_URL`:
- sqlite:///file.db    -> sqlite+aiosqlite:///file.db   (needs aiosqlite)
- postgresql+psycopg://...  -> postgresql+asyncpg://...      (needs asyncpg)

If the corresponding async driver is not installed, `async_engine` is
None and `get_async_db()` raises a 503 explaining how to enable async.
"""
from __future__ import annotations

import os

from .db import DB_URL


def _to_async_url(sync_url: str) -> str | None:
    """Translate a sync URL to its async-driver equivalent."""
    if sync_url.startswith("sqlite:///"):
        return sync_url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    if sync_url.startswith("postgresql+psycopg://"):
        return sync_url.replace(
            "postgresql+psycopg://", "postgresql+asyncpg://", 1
        )
    if sync_url.startswith("postgresql://"):
        return sync_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return None


ASYNC_DB_URL = _to_async_url(DB_URL)

async_engine = None
AsyncSessionLocal = None
_async_init_error: str | None = None


def _try_init_async() -> None:
    """Lazy init: only run if a route actually needs the async session.
    Catches missing driver imports and stashes the error for the
    dependency to surface."""
    global async_engine, AsyncSessionLocal, _async_init_error
    if async_engine is not None or _async_init_error is not None:
        return
    if ASYNC_DB_URL is None:
        _async_init_error = (
            f"DB_URL '{DB_URL}' has no known async-driver equivalent. "
            f"Set PITANTUM_DB_URL to a sqlite:/// or postgresql:// URL."
        )
        return
    try:
        from sqlalchemy.ext.asyncio import (  # noqa: WPS433  (lazy import)
            create_async_engine,
            async_sessionmaker,
        )
    except ImportError as e:
        _async_init_error = (
            "SQLAlchemy async support not available. "
            f"Original error: {e}"
        )
        return
    try:
        async_engine = create_async_engine(
            ASYNC_DB_URL,
            echo=False,
            future=True,
        )
        AsyncSessionLocal = async_sessionmaker(
            bind=async_engine, expire_on_commit=False, autoflush=False,
        )
    except Exception as e:
        # Most common cause: aiosqlite or asyncpg not installed.
        _async_init_error = (
            f"Async engine init failed: {e}. "
            f"Install the async driver: "
            f"`pip install aiosqlite` (for SQLite) or "
            f"`pip install asyncpg` (for Postgres)."
        )


async def get_async_db():
    """FastAPI dependency for async session. Yields AsyncSession."""
    from fastapi import HTTPException
    _try_init_async()
    if AsyncSessionLocal is None:
        raise HTTPException(
            503,
            {
                "detail":
                    "Async DB layer not available: "
                    + (_async_init_error or "unknown error"),
                "code": "async_unavailable",
                "hint":
                    "This endpoint requires aiosqlite (SQLite) or asyncpg "
                    "(Postgres). Install with `pip install aiosqlite` and "
                    "restart the backend.",
            },
        )
    async with AsyncSessionLocal() as s:
        try:
            yield s
        except Exception:
            await s.rollback()
            raise
