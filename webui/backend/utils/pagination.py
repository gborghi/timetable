"""Opt-in pagination helper.

Long-list endpoints (students, monitor/events, lessons, ...) accept
optional `?limit=N&offset=M` query params. When EITHER is provided the
endpoint returns the paginated envelope:

    {
      "items":  [...],
      "total":  <int>,        # full count BEFORE pagination
      "limit":  <int|None>,
      "offset": <int>,
    }

When NEITHER is provided the endpoint returns the bare list (legacy
shape, what the frontend `SortableQueryableList` already consumes).
This way old clients don't break and new clients can opt in.
"""
from __future__ import annotations

from typing import Any


def paginated_or_list(
    rows: list[Any],
    limit: int | None,
    offset: int | None,
) -> list[Any] | dict:
    """If `limit` or `offset` is set, returns the paginated envelope;
    otherwise returns `rows` as-is.

    `rows` is the FULL filtered+sorted list. We slice in Python because
    most of these endpoints already do filter_and_sort post-query (which
    means we can't push limit/offset into the SQLAlchemy query without a
    refactor); for the volumes piTantum handles this is fine.
    """
    if limit is None and offset is None:
        return rows
    total = len(rows)
    o = max(int(offset or 0), 0)
    if limit is None:
        sliced = rows[o:]
    else:
        L = max(int(limit), 0)
        sliced = rows[o:o + L]
    return {
        "items": sliced,
        "total": total,
        "limit": int(limit) if limit is not None else None,
        "offset": o,
    }
