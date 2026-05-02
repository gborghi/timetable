"""Opt-in pagination + export helper.

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

When `?format=xlsx` or `?format=csv` is given, `paginated_or_list` is
bypassed and the rows are streamed as a binary file (see
`utils.list_exporters`). Always exports the full filtered+sorted set
(ignoring limit/offset) -- the user gets exactly the view they're
looking at.
"""
from __future__ import annotations

from typing import Any


def paginated_or_list(
    rows: list[Any],
    limit: int | None,
    offset: int | None,
    *,
    fmt: str | None = None,
    entity: str | None = None,
    columns: list[str] | None = None,
) -> Any:
    """If `limit` or `offset` is set, returns the paginated envelope;
    otherwise returns `rows` as-is.

    `rows` is the FULL filtered+sorted list. We slice in Python because
    most of these endpoints already do filter_and_sort post-query (which
    means we can't push limit/offset into the SQLAlchemy query without a
    refactor); for the volumes piTantum handles this is fine.

    When `fmt in ('xlsx', 'csv')` is given, the rows are streamed as a
    binary file via `utils.list_exporters.respond_export`.
    """
    if fmt in ("xlsx", "csv"):
        from .list_exporters import respond_export
        return respond_export(rows, entity or "rows", fmt, columns)
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
