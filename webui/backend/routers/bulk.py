"""Bulk operations on multiple entities with conflict detection.

The user selects N rows in a list view (via shift/ctrl click) and asks to
apply the same constraint to all of them. The endpoint runs a dry-run
first that flags any pre-existing conflicting setting, and returns the
list of conflicts plus the list of clean candidates.

The frontend then asks the user how to handle the conflicts:
  override : replace the existing setting
  skip     : leave the conflicting entity untouched
  cancel   : abort the bulk operation entirely

A second call with `on_conflict='override'` or `'skip'` actually applies
the change.

Endpoints:
  POST /api/bulk/{entity}/dry-run
       -> { candidates: [...], conflicts: [{id, name, reason}] }
  POST /api/bulk/{entity}/apply
       -> ImportReport-style result

`{entity}` is one of teachers/classes/classrooms.
`action` describes the kind of bulk change. Currently supported:
  - add_logical: add a logical-unavailability rule to each entity
  - set_field: set a single boolean/numeric/string field on each entity
  - add_unavailability: add one (day, hour) HARD/SOFT cell to each entity
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models
from ..db import get_db
from ..utils.logic_parser import LogicError, parse_to_dnf

router = APIRouter(prefix="/api/bulk", tags=["bulk"])


ENTITY_MODEL = {
    "teachers": models.Teacher,
    "classes": models.SchoolClass,
    "classrooms": models.Classroom,
}
ENTITY_TYPE_LOGIC = {
    "teachers": "teacher",
    "classes": "class",
    "classrooms": "classroom",
}
ENTITY_UNAV_MODEL = {
    "teachers": (models.TeacherUnavailability, "teacher_id"),
    "classes": (models.ClassUnavailability, "class_id"),
    "classrooms": (models.ClassroomUnavailability, "classroom_id"),
}


class BulkRequest(BaseModel):
    entity_ids: list[int]
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)
    on_conflict: str = "dry_run"  # dry_run | override | skip


class BulkConflict(BaseModel):
    id: int
    name: str
    reason: str


class BulkDryRunOut(BaseModel):
    action: str
    n_targets: int
    candidates: list[BulkConflict] = Field(default_factory=list)
    conflicts: list[BulkConflict] = Field(default_factory=list)


class BulkApplyOut(BaseModel):
    ok: bool
    action: str
    n_applied: int = 0
    n_overridden: int = 0
    n_skipped: int = 0
    messages: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def _check_entity_kind(entity: str) -> None:
    if entity not in ENTITY_MODEL:
        raise HTTPException(404, f"entity '{entity}' non supportata")


def _name_of(obj: Any) -> str:
    return getattr(obj, "name", str(getattr(obj, "id", "?")))


def _detect_conflict(action: str, payload: dict, entity: str,
                     obj: Any, db: Session) -> str | None:
    """Return a human-readable conflict reason, or None if the change is
    a clean apply."""
    if action == "add_logical":
        expr = (payload.get("expression") or "").strip()
        if not expr:
            return "expression vuota"
        existing = db.query(models.LogicalUnavailability).filter(
            models.LogicalUnavailability.entity_type == ENTITY_TYPE_LOGIC[entity],
            models.LogicalUnavailability.entity_id == obj.id,
        ).all()
        for r in existing:
            if (r.expression or "").strip() == expr:
                return f"vincolo logico identico gia presente (id {r.id})"
        return None

    if action == "set_field":
        field = payload.get("field")
        value = payload.get("value")
        if field is None:
            return "field non specificato"
        if not hasattr(obj, field):
            return f"campo '{field}' inesistente su {entity}"
        cur = getattr(obj, field)
        if cur != value and cur not in (None, "", 0, False):
            return f"campo '{field}' gia valorizzato a {cur!r}"
        return None

    if action == "add_unavailability":
        d = payload.get("day")
        h = payload.get("hour")
        if d is None or h is None:
            return "day/hour mancante"
        Model, fk = ENTITY_UNAV_MODEL[entity]
        existing = db.query(Model).filter(
            getattr(Model, fk) == obj.id,
            Model.day == int(d), Model.hour == int(h),
        ).first()
        if existing:
            new_state = payload.get("state", "hard")
            if existing.state == new_state:
                return None  # idempotent: same cell already set
            return (f"slot ({d},{h}) gia HARD/SOFT come "
                    f"'{existing.state}' (richiesto '{new_state}')")
        return None

    return f"action '{action}' sconosciuta"


def _apply_one(action: str, payload: dict, entity: str,
               obj: Any, db: Session, override: bool) -> str | None:
    """Apply the change to a single entity. Returns an error string on
    failure, None on success."""
    if action == "add_logical":
        expr = (payload.get("expression") or "").strip()
        try:
            parsed = parse_to_dnf(expr)
        except LogicError as e:
            return f"sintassi: {e}"
        if not parsed.clauses:
            return "espressione vuota"
        if override:
            db.query(models.LogicalUnavailability).filter(
                models.LogicalUnavailability.entity_type
                == ENTITY_TYPE_LOGIC[entity],
                models.LogicalUnavailability.entity_id == obj.id,
                models.LogicalUnavailability.expression == expr,
            ).delete()
        db.add(models.LogicalUnavailability(
            entity_type=ENTITY_TYPE_LOGIC[entity],
            entity_id=obj.id,
            expression=expr,
            parsed_dnf_json=json.dumps(parsed.clauses),
            is_hard=bool(payload.get("is_hard", True)),
            soft_penalty=int(payload.get("soft_penalty", 100)),
        ))
        return None

    if action == "set_field":
        field = payload.get("field")
        value = payload.get("value")
        if not hasattr(obj, field):
            return f"campo '{field}' inesistente"
        try:
            setattr(obj, field, value)
        except Exception as e:
            return f"set fallito: {e}"
        return None

    if action == "add_unavailability":
        Model, fk = ENTITY_UNAV_MODEL[entity]
        d = int(payload.get("day"))
        h = int(payload.get("hour"))
        existing = db.query(Model).filter(
            getattr(Model, fk) == obj.id,
            Model.day == d, Model.hour == h,
        ).first()
        if existing and override:
            existing.state = payload.get("state", "hard")
            existing.soft_penalty = int(payload.get("soft_penalty", 100))
            existing.reason = payload.get("reason")
            return None
        if existing and not override:
            return None  # idempotent same-state path
        kw = {fk: obj.id, "day": d, "hour": h,
              "state": payload.get("state", "hard"),
              "soft_penalty": int(payload.get("soft_penalty", 100)),
              "reason": payload.get("reason")}
        db.add(Model(**kw))
        return None

    return f"action '{action}' sconosciuta"


def _resolve_targets(entity: str, ids: list[int],
                     db: Session) -> list[Any]:
    Model = ENTITY_MODEL[entity]
    rows = db.query(Model).filter(Model.id.in_(ids)).all()
    return rows


@router.post("/{entity}/dry-run", response_model=BulkDryRunOut)
def dry_run(entity: str, req: BulkRequest,
            db: Session = Depends(get_db)):
    _check_entity_kind(entity)
    targets = _resolve_targets(entity, req.entity_ids, db)
    out = BulkDryRunOut(action=req.action, n_targets=len(targets))
    for obj in targets:
        reason = _detect_conflict(req.action, req.payload, entity, obj, db)
        rec = BulkConflict(id=obj.id, name=_name_of(obj),
                           reason=reason or "ok")
        if reason is None:
            out.candidates.append(rec)
        else:
            out.conflicts.append(rec)
    return out


@router.post("/{entity}/apply", response_model=BulkApplyOut)
def apply_bulk(entity: str, req: BulkRequest,
               db: Session = Depends(get_db)):
    _check_entity_kind(entity)
    if req.on_conflict not in ("override", "skip"):
        raise HTTPException(400, "on_conflict deve essere override o skip")
    targets = _resolve_targets(entity, req.entity_ids, db)
    out = BulkApplyOut(ok=True, action=req.action)
    for obj in targets:
        reason = _detect_conflict(req.action, req.payload, entity, obj, db)
        if reason is not None:
            if req.on_conflict == "skip":
                out.n_skipped += 1
                out.messages.append(f"{_name_of(obj)}: skip ({reason})")
                continue
            err = _apply_one(req.action, req.payload, entity, obj, db,
                             override=True)
            if err:
                out.errors.append(f"{_name_of(obj)}: {err}")
                continue
            out.n_overridden += 1
            out.messages.append(f"{_name_of(obj)}: override ({reason})")
        else:
            err = _apply_one(req.action, req.payload, entity, obj, db,
                             override=False)
            if err:
                out.errors.append(f"{_name_of(obj)}: {err}")
                continue
            out.n_applied += 1
    db.commit()
    if out.errors:
        out.ok = False
    return out
