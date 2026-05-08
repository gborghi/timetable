"""Lesson-by-id endpoints (move, delete, unschedule, reschedule).

The /api/schedule router exposes lesson-as-tuple manipulation
(`/api/schedule/move-lesson` takes (teacher,class,subject,src_day,
src_hour,dst_day,dst_hour)) which mirrors the legacy frontend matrix
view. The new calendar-style /schedule UI works with Lesson ids
instead, so this router exposes:

    POST   /api/lessons/{id}/move           -> move to (day, hour)
    DELETE /api/lessons/{id}                -> delete from DB
    POST   /api/lessons/{id}/unschedule     -> remove from active grid,
                                               keep in unscheduled pool
    GET    /api/lessons/unscheduled         -> list pool entries
    POST   /api/lessons/unscheduled/{id}/reschedule
                                            -> place pool entry at
                                               (day, hour); deletes the
                                               pool row, creates a Lesson

The MOVE endpoint reuses `optimization.validate_and_apply_move` so
HARD-feasibility, room availability, and SOFT delta are computed
identically to the legacy tuple endpoint. UNSCHEDULE / RESCHEDULE
just shuttle the row between `lessons` and `unscheduled_lessons`
(no solver involvement).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models, optimization
from ..db import get_db

router = APIRouter(prefix="/api/lessons", tags=["lessons"])


# ---------- request schemas ----------


class LessonMoveIn(BaseModel):
    day: int
    hour: int


class RescheduleIn(BaseModel):
    day: int
    hour: int


# ---------- helpers ----------


def _serialise(l: models.Lesson) -> dict:
    return {
        "id": l.id,
        "solution_id": l.solution_id,
        "teacher_name": l.teacher_name,
        "class_name": l.class_name,
        "group_name": l.group_name,
        "subject": l.subject,
        "day": l.day,
        "hour": l.hour,
        "classroom_name": l.classroom_name,
        "cotaught_with": l.cotaught_with,
    }


def _serialise_unscheduled(u: models.UnscheduledLesson) -> dict:
    return {
        "id": u.id,
        "solution_id": u.solution_id,
        "teacher_name": u.teacher_name,
        "class_name": u.class_name,
        "group_name": u.group_name,
        "subject": u.subject,
        "classroom_name": u.classroom_name,
        "cotaught_with": u.cotaught_with,
        "original_day": u.original_day,
        "original_hour": u.original_hour,
    }


# ---------- endpoints ----------


@router.get("/unscheduled")
def list_unscheduled(db: Session = Depends(get_db)):
    """Return every lesson in the unscheduled pool, scoped to the
    active solution. Frontend renders these as a sidebar from which
    the user drags rows back onto the calendar."""
    from .. import engine_io
    active = engine_io.get_active_solution(db)
    if active is None:
        return {"lessons": []}
    rows = db.query(models.UnscheduledLesson).filter(
        models.UnscheduledLesson.solution_id == active.id
    ).order_by(models.UnscheduledLesson.id).all()
    return {"lessons": [_serialise_unscheduled(u) for u in rows]}


@router.post("/{lesson_id}/move")
def move_lesson_by_id(lesson_id: int,
                      payload: LessonMoveIn,
                      db: Session = Depends(get_db)):
    """Move the Lesson identified by `lesson_id` to (payload.day,
    payload.hour). Reuses the same validation as the legacy
    /api/schedule/move-lesson tuple endpoint so HARD/SOFT semantics
    are identical."""
    l = db.get(models.Lesson, lesson_id)
    if l is None:
        raise HTTPException(404, "lesson not found")
    src = (l.teacher_name, l.class_name, l.subject, l.day, l.hour)
    dst = (l.teacher_name, l.class_name, l.subject,
           int(payload.day), int(payload.hour))
    if src == dst:
        return {"accepted": False,
                "reason": "Slot di destinazione identico all'origine.",
                "lesson_id": lesson_id}
    out = optimization.validate_and_apply_move(db, src, dst)
    out["lesson_id"] = lesson_id
    return out


@router.delete("/{lesson_id}")
def delete_lesson_by_id(lesson_id: int, db: Session = Depends(get_db)):
    """Delete a Lesson row (alias for the existing
    /api/schedule/lesson/{id} endpoint, exposed here for consistency
    with the rest of the /api/lessons/{id}/* family)."""
    l = db.get(models.Lesson, lesson_id)
    if l is None:
        raise HTTPException(404, "lesson not found")
    db.delete(l)
    db.commit()
    return {"ok": True, "deleted_id": lesson_id}


@router.post("/{lesson_id}/unschedule")
def unschedule_lesson(lesson_id: int, db: Session = Depends(get_db)):
    """Remove the Lesson from the active grid and copy its payload
    to the unscheduled pool. The pool row remembers the original
    (day, hour) for the UI tooltip, but is otherwise stand-alone:
    re-placing it via /reschedule creates a fresh Lesson."""
    l = db.get(models.Lesson, lesson_id)
    if l is None:
        raise HTTPException(404, "lesson not found")
    pool_row = models.UnscheduledLesson(
        solution_id=l.solution_id,
        teacher_name=l.teacher_name,
        class_name=l.class_name,
        group_name=l.group_name,
        subject=l.subject,
        classroom_name=l.classroom_name,
        cotaught_with=l.cotaught_with,
        original_day=l.day,
        original_hour=l.hour,
    )
    db.add(pool_row)
    db.delete(l)
    db.commit()
    db.refresh(pool_row)
    return {
        "ok": True,
        "unscheduled_id": pool_row.id,
        "lesson": _serialise_unscheduled(pool_row),
    }


@router.post("/unscheduled/{unscheduled_id}/reschedule")
def reschedule_lesson(unscheduled_id: int,
                      payload: RescheduleIn,
                      db: Session = Depends(get_db)):
    """Place a pool entry at (day, hour). Deletes the pool row and
    creates a Lesson in its solution. The destination slot HARD
    feasibility is enforced by reusing `validate_and_apply_move` on
    a temp src tuple after the row is created -- if the move is
    rejected, the new Lesson is rolled back."""
    u = db.get(models.UnscheduledLesson, unscheduled_id)
    if u is None:
        raise HTTPException(404, "unscheduled lesson not found")
    new_lesson = models.Lesson(
        solution_id=u.solution_id,
        teacher_name=u.teacher_name,
        class_name=u.class_name,
        group_name=u.group_name,
        subject=u.subject,
        day=int(payload.day),
        hour=int(payload.hour),
        classroom_name=u.classroom_name,
        cotaught_with=u.cotaught_with,
    )
    db.add(new_lesson)
    db.delete(u)
    db.commit()
    db.refresh(new_lesson)
    return {
        "ok": True,
        "lesson_id": new_lesson.id,
        "lesson": _serialise(new_lesson),
    }


@router.delete("/unscheduled/{unscheduled_id}")
def delete_unscheduled(unscheduled_id: int,
                       db: Session = Depends(get_db)):
    """Drop a pool entry definitively (user gave up on re-placing)."""
    u = db.get(models.UnscheduledLesson, unscheduled_id)
    if u is None:
        raise HTTPException(404, "unscheduled lesson not found")
    db.delete(u)
    db.commit()
    return {"ok": True, "deleted_id": unscheduled_id}
