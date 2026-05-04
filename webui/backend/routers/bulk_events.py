"""Bulk operations on events / lessons selected from /monitor.

Mirrors the dry-run + apply flow of bulk.py but operates on the rows
returned by /api/monitor/event-rows, where a row is either a real
Lesson (lesson_id != None) or a placeholder for a missing-hour
Assignment (lesson_id is None).

Supported actions:
  - set_classroom    payload: {classroom_name: str}
                     conflicts: room busy in same slot (HARD) /
                                ClassroomUnavailability hard (HARD) /
                                capacity < class.n_students (WARN)
  - clear_classroom  payload: {}    no conflicts possible
  - set_lock         payload: {locked: bool}    op on Assignment.locked

Placeholder rows (lesson_id None) are silently skipped for set_classroom
and clear_classroom; they ARE valid targets for set_lock (lock lives on
the Assignment, which exists for placeholders).

Endpoints:
  POST /api/bulk/events/dry-run  -> {action, n_targets, candidates,
                                     conflicts}
  POST /api/bulk/events/apply    -> {ok, n_applied, n_overridden,
                                     n_skipped, messages, errors}
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models
from ..db import get_db

router = APIRouter(prefix="/api/bulk/events", tags=["bulk"])


_ALLOWED_ACTIONS = {"set_classroom", "clear_classroom", "set_lock"}
_PLACEHOLDER_REASON = "evento non schedulato (nessuna lezione da modificare)"


class EventRowRef(BaseModel):
    lesson_id: int | None = None
    assignment_id: int | None = None


class BulkEventsRequest(BaseModel):
    rows: list[EventRowRef]
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)
    on_conflict: str = "dry_run"  # dry_run | override | skip


class BulkEventsConflict(BaseModel):
    lesson_id: int | None = None
    assignment_id: int | None = None
    name: str
    reason: str


class BulkEventsDryRunOut(BaseModel):
    action: str
    n_targets: int
    candidates: list[BulkEventsConflict] = Field(default_factory=list)
    conflicts: list[BulkEventsConflict] = Field(default_factory=list)


class BulkEventsApplyOut(BaseModel):
    ok: bool
    action: str
    n_applied: int = 0
    n_overridden: int = 0
    n_skipped: int = 0
    messages: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def _row_label(lesson: models.Lesson | None,
               assignment: models.Assignment | None) -> str:
    if lesson is not None:
        slot = f"d{lesson.day}h{lesson.hour}"
        return (f"{lesson.subject} {lesson.class_name} {slot}"
                + (f" [{lesson.classroom_name}]"
                   if lesson.classroom_name else ""))
    if assignment is not None:
        return (f"#{assignment.id} (cattedra non schedulata)")
    return "?"


def _resolve_row(
    ref: EventRowRef, db: Session,
) -> tuple[models.Lesson | None, models.Assignment | None]:
    lesson = (db.get(models.Lesson, int(ref.lesson_id))
              if ref.lesson_id is not None else None)
    aid = ref.assignment_id
    assignment = (db.get(models.Assignment, int(aid))
                  if aid is not None else None)
    return lesson, assignment


def _detect_classroom_conflicts(
    db: Session, lesson: models.Lesson, classroom_name: str,
) -> str | None:
    """HARD-then-WARN conflict reason for moving `lesson` into
    `classroom_name`. Returns None when the change is clean.

    HARD checks (in order):
      - same (day, hour) already has another Lesson in this room AND
        the room is not configured as multi_class with spare capacity;
      - the Classroom has a HARD ClassroomUnavailability for this slot.

    WARN checks (after HARD):
      - Classroom.capacity < SchoolClass.n_students for the class.
    """
    target_room = (db.query(models.Classroom)
                   .filter(models.Classroom.name == classroom_name)
                   .first())
    if target_room is None:
        return f"aula '{classroom_name}' inesistente"

    # Room busy at (day, hour) by some OTHER lesson -- check multi_class.
    busy = db.query(models.Lesson).filter(
        models.Lesson.solution_id == lesson.solution_id,
        models.Lesson.day == lesson.day,
        models.Lesson.hour == lesson.hour,
        models.Lesson.classroom_name == classroom_name,
        models.Lesson.id != lesson.id,
    ).all()
    if busy:
        if target_room.multi_class:
            cur = len(busy) + 1  # +1 for the lesson we're moving in
            cap = int(target_room.multi_class_max or 1)
            if cur > cap:
                return (f"aula {classroom_name} occupata "
                        f"({len(busy)} lezioni gia' presenti, "
                        f"max {cap} multi_class)")
        else:
            other = busy[0]
            return (f"aula {classroom_name} occupata da "
                    f"{other.subject} {other.class_name} "
                    f"d{lesson.day}h{lesson.hour}")

    # Hard unavailability for this slot on the room.
    unav = db.query(models.ClassroomUnavailability).filter(
        models.ClassroomUnavailability.classroom_id == target_room.id,
        models.ClassroomUnavailability.day == lesson.day,
        models.ClassroomUnavailability.hour == lesson.hour,
        models.ClassroomUnavailability.state == "hard",
    ).first()
    if unav is not None:
        return (f"aula {classroom_name} HARD non disponibile in "
                f"d{lesson.day}h{lesson.hour}"
                + (f" ({unav.reason})" if unav.reason else ""))

    # Capacity warning (non-fatal but flagged).
    cls = (db.query(models.SchoolClass)
           .filter(models.SchoolClass.name == lesson.class_name)
           .first())
    if cls is not None and target_room.capacity:
        n_students = int(cls.n_students or 0)
        cap = int(target_room.capacity or 0)
        if cap and n_students and cap < n_students:
            return (f"capienza aula {classroom_name} ({cap}) < "
                    f"studenti classe {lesson.class_name} ({n_students})")

    return None


def _detect_conflict(
    action: str, payload: dict, db: Session,
    lesson: models.Lesson | None,
    assignment: models.Assignment | None,
) -> str | None:
    if action == "set_classroom":
        if lesson is None:
            return _PLACEHOLDER_REASON
        new_room = (payload.get("classroom_name") or "").strip()
        if not new_room:
            return "classroom_name vuoto"
        if (lesson.classroom_name or "") == new_room:
            return None  # already there, idempotent
        return _detect_classroom_conflicts(db, lesson, new_room)

    if action == "clear_classroom":
        if lesson is None:
            return _PLACEHOLDER_REASON
        return None

    if action == "set_lock":
        if assignment is None:
            return "assignment non trovata"
        target = bool(payload.get("locked", True))
        if bool(assignment.locked) == target:
            return None  # already in target state -- treat as idempotent
        return None

    return f"action '{action}' sconosciuta"


def _apply_one(
    action: str, payload: dict, db: Session,
    lesson: models.Lesson | None,
    assignment: models.Assignment | None,
    override: bool,
) -> str | None:
    """Apply on a single resolved row. Returns error string or None."""
    if action == "set_classroom":
        if lesson is None:
            return "lezione mancante"
        new_room = (payload.get("classroom_name") or "").strip()
        if not new_room:
            return "classroom_name vuoto"
        lesson.classroom_name = new_room
        return None

    if action == "clear_classroom":
        if lesson is None:
            return "lezione mancante"
        lesson.classroom_name = None
        return None

    if action == "set_lock":
        if assignment is None:
            return "assignment mancante"
        assignment.locked = bool(payload.get("locked", True))
        return None

    return f"action '{action}' sconosciuta"


def _check_action(action: str) -> None:
    if action not in _ALLOWED_ACTIONS:
        raise HTTPException(
            400, f"action '{action}' sconosciuta. "
                 f"Validi: {sorted(_ALLOWED_ACTIONS)}",
        )


@router.post("/dry-run", response_model=BulkEventsDryRunOut)
def dry_run(req: BulkEventsRequest, db: Session = Depends(get_db)):
    _check_action(req.action)
    out = BulkEventsDryRunOut(action=req.action, n_targets=len(req.rows))
    for ref in req.rows:
        lesson, assignment = _resolve_row(ref, db)
        reason = _detect_conflict(req.action, req.payload, db,
                                   lesson, assignment)
        rec = BulkEventsConflict(
            lesson_id=ref.lesson_id,
            assignment_id=ref.assignment_id,
            name=_row_label(lesson, assignment),
            reason=reason or "ok",
        )
        if reason is None:
            out.candidates.append(rec)
        else:
            out.conflicts.append(rec)
    return out


@router.post("/apply", response_model=BulkEventsApplyOut)
def apply_bulk(req: BulkEventsRequest, db: Session = Depends(get_db)):
    _check_action(req.action)
    if req.on_conflict not in ("override", "skip"):
        raise HTTPException(400, "on_conflict deve essere override o skip")

    out = BulkEventsApplyOut(ok=True, action=req.action)
    seen_assignments: set[int] = set()  # dedup for set_lock writes
    for ref in req.rows:
        lesson, assignment = _resolve_row(ref, db)
        label = _row_label(lesson, assignment)

        # Placeholder rows on set_classroom / clear_classroom are ALWAYS
        # skipped, regardless of on_conflict: there is no Lesson to
        # mutate, override is meaningless.
        if (req.action in ("set_classroom", "clear_classroom")
                and lesson is None):
            out.n_skipped += 1
            out.messages.append(f"{label}: skip ({_PLACEHOLDER_REASON})")
            continue

        # set_lock: dedup repeated assignment_ids (e.g. multiple lesson
        # rows of the same cattedra) so we don't double-account writes.
        if req.action == "set_lock":
            if assignment is None:
                out.errors.append(f"{label}: assignment non trovata")
                continue
            if assignment.id in seen_assignments:
                continue
            seen_assignments.add(assignment.id)

        reason = _detect_conflict(req.action, req.payload, db,
                                   lesson, assignment)
        if reason is not None:
            if req.on_conflict == "skip":
                out.n_skipped += 1
                out.messages.append(f"{label}: skip ({reason})")
                continue
            err = _apply_one(req.action, req.payload, db, lesson,
                             assignment, override=True)
            if err:
                out.errors.append(f"{label}: {err}")
                continue
            out.n_overridden += 1
            out.messages.append(f"{label}: override ({reason})")
        else:
            err = _apply_one(req.action, req.payload, db, lesson,
                             assignment, override=False)
            if err:
                out.errors.append(f"{label}: {err}")
                continue
            out.n_applied += 1

    db.commit()
    if out.errors:
        out.ok = False
    return out
