"""Tab Ore -- engine-side accessors for the working hours config.

The webui (`webui.backend.routers.working_hours`) is the source of
truth: it stores the user's WorkingDay rows + per-day
WorkingHourSlot rows in the SQLite/Postgres timetable DB.

This module exposes a small read-only API for the engine and the
non-webui tooling that wants to consume the same configuration:

  - get_days()        -> list[int]   legacy day numbers (e.g. [1..6])
  - get_hours()       -> list[int]   uniform engine hour codes
                                     (e.g. [8..13]) of length max_slots
  - get_slot_label(d, slot) -> "08:00-09:00"
  - get_config_dict() -> dict       raw config bundle
  - reload()                        -- invalidate cache (useful in
                                       tests or when the API mutates
                                       the config mid-process)

Backwards compatibility
-----------------------
If the DB does not have a working_days table yet (very old dev DBs
that haven't run alembic / lightweight migrations), or the table is
empty, every accessor falls back to the legacy hardcoded defaults:

   DAYS  = [1, 2, 3, 4, 5, 6]   (lun .. sab)
   HOURS = [8, 9, 10, 11, 12, 13]

This guarantees that nothing breaks when the user has never visited
the Ore tab. The exact same values are also seeded into the DB by
both the alembic migration and the lightweight migration in
``webui/backend/db.py``, so the post-default behaviour is identical
whether the engine reads the DB or falls back to the literals.

V1 scope
--------
The webui editor allows per-day variable slot counts (e.g. lun..ven
6 slots, sab 4 slots), but the engine consumes a UNIFORM HOURS
length equal to ``max(slots_per_day)``. Days with fewer slots leave
their last slot indices effectively unused (no lessons can land
there because the per-day slot count constraint will be tight via
the legacy ``DAY_HOURS_MAX`` knob). Plumbing the engine to a fully
heterogeneous slot grid is a v2 follow-up.
"""
from __future__ import annotations

import os
import threading
from typing import Any


_LEGACY_DAYS = [1, 2, 3, 4, 5, 6]   # lun .. sab
_LEGACY_HOURS = [8, 9, 10, 11, 12, 13]

# Public re-exports: callers that just need the default Italian-school
# grid can import these constants instead of hardcoding range(1,7) /
# range(8,14).  Prefer get_days() / get_hours() when a DB connection is
# available — they read the actual Tab Ore config.
DEFAULT_DAYS = _LEGACY_DAYS
DEFAULT_HOURS = _LEGACY_HOURS


_CACHE: dict[str, Any] | None = None
_CACHE_LOCK = threading.Lock()


def _resolve_db_path() -> str | None:
    """Pick the SQLite path the way ``webui/backend/db.py`` does.

    Returns None when the env var points at a non-SQLite URL
    (Postgres, MySQL, ...): in that case we fall back to the legacy
    constants because reading the config would require pulling in the
    full SQLAlchemy stack from inside the engine, which we don't want
    to do for a read-only helper that runs deep in the solver.

    The engine still works correctly on Postgres -- the user is just
    on the legacy default unless they explicitly override DAYS/HOURS
    elsewhere. The webui side reads the config via SQLAlchemy and
    passes it down through the standard pkl payload path.
    """
    env_url = os.environ.get("PITANTUM_DB_URL")
    if env_url and not env_url.strip().startswith("sqlite:"):
        return None
    if env_url and env_url.startswith("sqlite:///"):
        return env_url[len("sqlite:///"):]
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.normpath(os.path.join(here, "..", "webui", "data",
                                      "timetable.db")),
        os.path.normpath(os.path.join(here, "..", "..", "webui",
                                      "data", "timetable.db")),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def _load_from_sqlite() -> dict[str, Any] | None:
    db_path = _resolve_db_path()
    if not db_path or not os.path.isfile(db_path):
        return None
    import sqlite3
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='working_days'"
        )
        if not cur.fetchone():
            return None
        days_rows = conn.execute(
            "SELECT id, code, label, position, legacy_day_number, "
            "       is_active "
            "FROM working_days WHERE tenant_id=1 "
            "ORDER BY position"
        ).fetchall()
        if not days_rows:
            return None
        days_out = []
        max_slots = 0
        for d_id, code, label, position, legacy, is_active in days_rows:
            slot_rows = conn.execute(
                "SELECT slot_index, start_time, end_time, label, "
                "       legacy_hour_number "
                "FROM working_hour_slots "
                "WHERE day_id=? ORDER BY slot_index",
                (d_id,),
            ).fetchall()
            slots = [
                {
                    "slot_index": s[0],
                    "start_time": s[1],
                    "end_time": s[2],
                    "label": s[3],
                    "legacy_hour_number": s[4],
                }
                for s in slot_rows
            ]
            if is_active and len(slots) > max_slots:
                max_slots = len(slots)
            days_out.append({
                "id": d_id,
                "code": code,
                "label": label,
                "position": position,
                "legacy_day_number": legacy,
                "is_active": bool(is_active),
                "slots": slots,
            })
        return {"days": days_out, "max_slots_per_day": max_slots}
    except Exception:
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _build_legacy_fallback() -> dict[str, Any]:
    days = [
        {
            "id": -1,
            "code": code,
            "label": label,
            "position": pos,
            "legacy_day_number": legacy,
            "is_active": True,
            "slots": [
                {
                    "slot_index": i,
                    "start_time": f"{8+i:02d}:00",
                    "end_time":   f"{9+i:02d}:00",
                    "label":      f"{i+1}ª ora",
                    "legacy_hour_number": 8 + i,
                }
                for i in range(6)
            ],
        }
        for code, label, pos, legacy in (
            ("MON", "Lunedi",    0, 1),
            ("TUE", "Martedi",   1, 2),
            ("WED", "Mercoledi", 2, 3),
            ("THU", "Giovedi",   3, 4),
            ("FRI", "Venerdi",   4, 5),
            ("SAT", "Sabato",    5, 6),
        )
    ]
    return {"days": days, "max_slots_per_day": 6}


def _load() -> dict[str, Any]:
    global _CACHE
    with _CACHE_LOCK:
        if _CACHE is not None:
            return _CACHE
        cfg = _load_from_sqlite()
        if cfg is None:
            cfg = _build_legacy_fallback()
        _CACHE = cfg
        return _CACHE


def reload() -> None:
    """Drop the in-process cache. The next accessor call re-reads
    the DB. Useful in tests and after a router mutation in the same
    process."""
    global _CACHE
    with _CACHE_LOCK:
        _CACHE = None


def get_config_dict() -> dict[str, Any]:
    """Return the full parsed config bundle. Cached."""
    return _load()


def get_days() -> list[int]:
    """Legacy day numbers for ACTIVE days, in position order.

    Defaults to [1, 2, 3, 4, 5, 6] (lun..sab). Callers that previously
    used the cv2.DAYS module constant should call this function so
    the user's customisation takes effect on the engine's day_idx
    enumeration.
    """
    cfg = _load()
    return [
        d["legacy_day_number"] for d in cfg["days"] if d["is_active"]
    ]


def get_hours() -> list[int]:
    """Uniform engine hour codes of length ``max_slots_per_day``.

    Defaults to [8, 9, 10, 11, 12, 13]. The values are derived from
    the legacy_hour_number of the FIRST active day's slots so the
    legacy *_unavailability tables continue to align. Days with
    fewer slots than the maximum keep the same hour codes for the
    indices they DO have; the engine treats the surplus indices as
    "no class can be scheduled there" via the existing per-day load
    cap (DAY_HOURS_MAX).
    """
    cfg = _load()
    active = [d for d in cfg["days"] if d["is_active"]]
    if not active:
        return list(_LEGACY_HOURS)
    base = active[0]["slots"]
    max_n = cfg.get("max_slots_per_day", len(base))
    if len(base) >= max_n:
        return [s["legacy_hour_number"] for s in base[:max_n]]
    out = [s["legacy_hour_number"] for s in base]
    last = out[-1] if out else 8
    while len(out) < max_n:
        last += 1
        out.append(last)
    return out


def get_slot_label(day_legacy_number: int, slot_index: int) -> str:
    """Return 'HH:MM-HH:MM' for the slot at the given (legacy day,
    slot index). Returns '' on any miss (the UI falls back to the
    legacy hardcoded label in that case)."""
    cfg = _load()
    for d in cfg["days"]:
        if d["legacy_day_number"] == day_legacy_number:
            for s in d["slots"]:
                if s["slot_index"] == slot_index:
                    return f"{s['start_time']}-{s['end_time']}"
    return ""


def get_active_day_count() -> int:
    return sum(1 for d in _load()["days"] if d["is_active"])


def get_max_slots_per_day() -> int:
    return _load().get("max_slots_per_day", len(_LEGACY_HOURS))


def is_uniform_slot_count() -> bool:
    cfg = _load()
    counts = [len(d["slots"]) for d in cfg["days"] if d["is_active"]]
    if not counts:
        return True
    target = max(counts)
    return all(c == target for c in counts)


def get_slots_per_day_map() -> dict[int, int]:
    """Map ``legacy_day_number -> active slot count`` for active days.

    Drives the CP-SAT slot-count constraint in solve_phase_a /
    solve_phase_b_for_day / MonolithicSolver: a day with fewer slots
    than ``max_slots_per_day`` caps the per-day load and forces the
    surplus slot vars to 0 so no lesson lands on a non-existent
    afternoon hour.

    Defaults (legacy fallback): every day gets ``len(_LEGACY_HOURS) = 6``
    slots so the constraint reduces to a no-op vs the legacy behaviour.
    """
    cfg = _load()
    out: dict[int, int] = {}
    for d in cfg["days"]:
        if not d["is_active"]:
            continue
        out[int(d["legacy_day_number"])] = len(d["slots"])
    return out
