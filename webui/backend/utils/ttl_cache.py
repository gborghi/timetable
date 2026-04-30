"""Tiny TTL cache with mutation-based invalidation.

Used for endpoints whose response is "cheap to compute on a fresh DB
but called frequently": `/api/dataset/state`, `/api/monitor/summary`,
`/api/dataset/available-profiles`. Section 2.4 P1.

The cache holds results for `ttl_s` seconds, OR until the global
mutation counter changes (which the mutation endpoints bump after a
successful commit). Whichever happens first invalidates the entry.

Threadsafe via a single module-level lock around the dict.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, int, Any]] = {}
_MUTATION_COUNTER = 0


def bump_mutation() -> None:
    """Mutation endpoints call this on successful commit; invalidates
    every cached entry whose key was set with `mutation_aware=True`."""
    global _MUTATION_COUNTER
    with _LOCK:
        _MUTATION_COUNTER += 1


def cached(key: str, ttl_s: float, mutation_aware: bool,
           compute: Callable[[], Any]) -> Any:
    """Return cached value if fresh (within ttl_s AND mutation counter
    matches when mutation_aware=True), else recompute and cache."""
    now = time.monotonic()
    with _LOCK:
        entry = _CACHE.get(key)
        cur_mut = _MUTATION_COUNTER
        if entry is not None:
            ts, mut, val = entry
            if (now - ts) < ttl_s and (
                    not mutation_aware or mut == cur_mut):
                return val
    # Compute outside the lock so a slow `compute` doesn't block other
    # readers.
    val = compute()
    with _LOCK:
        _CACHE[key] = (time.monotonic(), _MUTATION_COUNTER, val)
    return val


def clear() -> None:
    """Test helper: drop everything."""
    with _LOCK:
        _CACHE.clear()
