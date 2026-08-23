"""Ore di disposizione (standby per supplenze).

Riusa la machinery esistente: le ore piazzate sono ``Lesson`` con
``class_name=DISPOSIZIONE_CLASS`` e ``subject=DISPOSIZIONE_SUBJECT``.
Restano visibili come disponibili in Assenze e supplenze (non occupano
una classe, non prenotano un'aula) e si spostano con ``/move-lesson``.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from . import models
from .tenant import DEFAULT_TENANT_ID

DISPOSIZIONE_CLASS = "__disposizione__"
DISPOSIZIONE_SUBJECT = "Disposizione"

# Built-in slot weights when the school has not customised the grid.
# Saturday (often few teachers, frequent absences), Monday first hour,
# and first hours in general. Anything else is weight 1.
_DEFAULT_SLOT_WEIGHTS: dict[tuple[int, int], int] = {
    (6, 8): 12, (6, 9): 10, (6, 10): 8, (6, 11): 7,
    (6, 12): 6, (6, 13): 5,
    (1, 8): 10, (2, 8): 6, (3, 8): 6, (4, 8): 6, (5, 8): 6,
    (1, 9): 4, (2, 9): 3, (3, 9): 3, (4, 9): 3, (5, 9): 3,
}


def is_disposizione_lesson(class_name: str | None,
                           subject: str | None = None) -> bool:
    if class_name == DISPOSIZIONE_CLASS:
        return True
    if subject == DISPOSIZIONE_SUBJECT and (
            class_name is None or str(class_name).startswith("__")):
        return True
    return False


def is_disposizione_key(key: tuple) -> bool:
    if not key or len(key) < 3:
        return False
    return is_disposizione_lesson(key[1], key[2])


def default_slot_weight(day: int, hour: int) -> int:
    return int(_DEFAULT_SLOT_WEIGHTS.get((int(day), int(hour)), 1))


def get_or_create_config(
        db: Session, tenant_id: int = DEFAULT_TENANT_ID
        ) -> models.SchoolDisposizioneConfig:
    row = db.query(models.SchoolDisposizioneConfig).filter(
        models.SchoolDisposizioneConfig.tenant_id == tenant_id
    ).first()
    if row is None:
        row = models.SchoolDisposizioneConfig(
            tenant_id=tenant_id,
            max_total_hours=None,
            eligibility="all",
            slot_priorities_json=None,
        )
        db.add(row)
        db.flush()
    return row


def parse_slot_priorities(raw: str | None) -> dict[tuple[int, int], int]:
    if not raw:
        return dict(_DEFAULT_SLOT_WEIGHTS)
    try:
        arr = json.loads(raw)
    except Exception:
        return dict(_DEFAULT_SLOT_WEIGHTS)
    if not isinstance(arr, list) or not arr:
        return dict(_DEFAULT_SLOT_WEIGHTS)
    out: dict[tuple[int, int], int] = {}
    for it in arr:
        if not isinstance(it, dict):
            continue
        try:
            d = int(it["day"])
            h = int(it["hour"])
            w = int(it.get("weight", 1))
        except (KeyError, TypeError, ValueError):
            continue
        # Day/hour are configured calendar IDs (default seed 1..6 /
        # 8..13; custom calendars may use other IDs). Bounds match
        # DisposizioneSlotPriority.
        if d < 1 or d > 400 or h < 0 or h > 23:
            continue
        out[(d, h)] = max(0, w)
    return out or dict(_DEFAULT_SLOT_WEIGHTS)


def slot_priorities_to_list(weights: dict[tuple[int, int], int]
                            ) -> list[dict[str, int]]:
    return [
        {"day": d, "hour": h, "weight": w}
        for (d, h), w in sorted(weights.items())
        if w != 1 or (d, h) in _DEFAULT_SLOT_WEIGHTS
    ]


def config_to_out(row: models.SchoolDisposizioneConfig,
                  placed_hours: int = 0) -> dict[str, Any]:
    weights = parse_slot_priorities(row.slot_priorities_json)
    return {
        "max_total_hours": row.max_total_hours,
        "eligibility": row.eligibility or "all",
        "slot_priorities": slot_priorities_to_list(weights),
        "placed_hours": int(placed_hours),
    }


def assigned_cattedra_hours(db: Session) -> dict[int, int]:
    """Weekly cattedra hours per teacher (excludes potenziamento)."""
    out: dict[int, int] = {}
    for a in db.query(models.Assignment).all():
        if a.is_potenziamento:
            continue
        out[a.teacher_id] = out.get(a.teacher_id, 0) + int(a.hours or 0)
    return out


def eligible_teacher_ids(
        db: Session,
        eligibility: str | None,
        teachers: list[models.Teacher] | None = None,
        ) -> set[int]:
    if teachers is None:
        teachers = db.query(models.Teacher).all()
    if (eligibility or "all") != "under_contract":
        return {t.id for t in teachers}
    cattedra = assigned_cattedra_hours(db)
    out: set[int] = set()
    for t in teachers:
        used = cattedra.get(t.id, 0)
        if used < int(t.max_hours or 0):
            out.add(t.id)
    return out


def teacher_quotas(
        db: Session,
        eligibility: str | None = "all",
        max_total_hours: int | None = None,
        teachers: list[models.Teacher] | None = None,
        ) -> dict[str, int]:
    """Per-teacher hours the placer may assign, after eligibility + cap."""
    if teachers is None:
        teachers = db.query(models.Teacher).order_by(
            models.Teacher.name).all()
    allowed = eligible_teacher_ids(db, eligibility, teachers)
    quotas: dict[str, int] = {}
    for t in teachers:
        if t.id not in allowed:
            continue
        n = int(getattr(t, "disposizione_hours", 0) or 0)
        if n > 0:
            quotas[t.name] = n
    if max_total_hours is None:
        return quotas
    cap = max(0, int(max_total_hours))
    if sum(quotas.values()) <= cap:
        return quotas
    # Scale down proportionally, largest remainder, never raise a quota.
    if cap == 0 or not quotas:
        return {k: 0 for k in quotas}
    names = sorted(quotas)
    raw = [quotas[n] * cap / sum(quotas.values()) for n in names]
    floors = [int(x) for x in raw]
    leftover = cap - sum(floors)
    order = sorted(
        range(len(names)),
        key=lambda i: (raw[i] - floors[i], -quotas[names[i]], names[i]),
        reverse=True,
    )
    for i in order:
        if leftover <= 0:
            break
        if floors[i] < quotas[names[i]]:
            floors[i] += 1
            leftover -= 1
    return {names[i]: floors[i] for i in range(len(names)) if floors[i] > 0}


def _grid(db: Session | None = None) -> tuple[list[int], list[int]]:
    if db is not None:
        try:
            from . import models as _m
            rows = (
                db.query(_m.WorkingDay)
                .filter(_m.WorkingDay.is_active.is_(True))
                .order_by(_m.WorkingDay.position)
                .all()
            )
            days = [int(r.legacy_day_number) for r in rows
                    if r.legacy_day_number is not None]
            hours: list[int] = []
            for r in rows:
                hours = [
                    int(s.legacy_hour_number) for s in (r.slots or [])
                    if s.legacy_hour_number is not None
                ]
                if hours:
                    break
            if days:
                return days, hours or [8, 9, 10, 11, 12, 13]
        except Exception:
            pass
    try:
        from working_hours_config import (
            get_days, get_hours, DEFAULT_DAYS, DEFAULT_HOURS,
        )
        days = list(get_days()) or list(DEFAULT_DAYS)
        hours = list(get_hours()) or list(DEFAULT_HOURS)
        return days, hours
    except Exception:
        return [1, 2, 3, 4, 5, 6], [8, 9, 10, 11, 12, 13]


def busy_slots_from_sol(sol: dict) -> dict[str, set[tuple[int, int]]]:
    busy: dict[str, set[tuple[int, int]]] = {}
    for k, v in (sol or {}).items():
        if v != 1 or not k or len(k) < 5:
            continue
        p, _cl, _s, d, h = k[0], k[1], k[2], int(k[3]), int(k[4])
        busy.setdefault(p, set()).add((d, h))
    return busy


def place_disposizione_hours(
        sol: dict,
        quotas: dict[str, int],
        weights: dict[tuple[int, int], int] | None = None,
        *,
        days: list[int] | None = None,
        hours: list[int] | None = None,
        ) -> dict:
    """Greedy placement: highest-weight free slots first, no class/room.

    Mutates a copy of ``sol`` and returns it. Existing disposizione
    keys are dropped and re-placed from ``quotas``.
    """
    out = {k: v for k, v in (sol or {}).items()
           if v == 1 and not is_disposizione_key(k)}
    if not quotas:
        return out
    if days is None or hours is None:
        gd, gh = _grid()
        days = days or gd
        hours = hours or gh
    wmap = weights if weights is not None else dict(_DEFAULT_SLOT_WEIGHTS)
    busy = busy_slots_from_sol(out)
    ranked = sorted(
        ((int(wmap.get((d, h), 1)), d, h) for d in days for h in hours),
        key=lambda t: (-t[0], t[1], t[2]),
    )
    for tname, n in sorted(quotas.items()):
        taken = busy.setdefault(tname, set())
        placed = 0
        for _w, d, h in ranked:
            if placed >= n:
                break
            if (d, h) in taken:
                continue
            out[(tname, DISPOSIZIONE_CLASS, DISPOSIZIONE_SUBJECT, d, h)] = 1
            taken.add((d, h))
            placed += 1
    return out


def persist_disposizione_for_solution(db: Session, solution_id: int
                                      ) -> dict[str, Any]:
    """Replace disposizione lessons on ``solution_id`` from current policy."""
    cfg = get_or_create_config(db)
    quotas = teacher_quotas(
        db, cfg.eligibility, cfg.max_total_hours)
    sol = {}
    for l in db.query(models.Lesson).filter(
        models.Lesson.solution_id == solution_id
    ).all():
        sol[(l.teacher_name, l.class_name, l.subject, l.day, l.hour)] = 1
    weights = parse_slot_priorities(cfg.slot_priorities_json)
    gd, gh = _grid(db)
    new_sol = place_disposizione_hours(
        sol, quotas, weights, days=gd, hours=gh,
    )
    old_keys = {k for k in sol if is_disposizione_key(k)}
    new_keys = {k for k, v in new_sol.items()
                if v == 1 and is_disposizione_key(k)}
    to_del = old_keys - new_keys
    to_add = new_keys - old_keys
    if to_del:
        for p, cl, subj, d, h in to_del:
            db.query(models.Lesson).filter(
                models.Lesson.solution_id == solution_id,
                models.Lesson.teacher_name == p,
                models.Lesson.class_name == cl,
                models.Lesson.subject == subj,
                models.Lesson.day == int(d),
                models.Lesson.hour == int(h),
            ).delete(synchronize_session=False)
    for p, cl, subj, d, h in sorted(to_add):
        db.add(models.Lesson(
            solution_id=solution_id,
            teacher_name=p,
            class_name=cl,
            subject=subj,
            day=int(d),
            hour=int(h),
            classroom_name=None,
        ))
    db.commit()
    return {
        "placed_hours": len(new_keys),
        "requested_hours": int(sum(quotas.values())),
        "teachers": len(quotas),
    }


def apply_disposizione_to_active(db: Session) -> dict[str, Any]:
    from . import engine_io
    active = engine_io.get_active_solution(db)
    if active is None:
        return {"placed_hours": 0, "requested_hours": 0, "teachers": 0,
                "skipped": "no_active_solution"}
    return persist_disposizione_for_solution(db, active.id)
