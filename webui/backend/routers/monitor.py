"""Monitor and Vincoli views.

Two flat list endpoints + per-row mutation endpoints.

  /api/monitor/events       -> see _build_events docstring below
  /api/monitor/summary      -> counts of incomplete events
  /api/monitor/constraints  -> every user-defined constraint flattened
                               into a single sortable/searchable list.
                               Source kinds:
                                 teacher_cell / class_cell / room_cell
                                 logical_teacher / logical_class /
                                   logical_room / logical_curriculum
                                 coteach
                                 subject_room_pref / teacher_room_pref
                                 class_hard_flag / curriculum_subject_hours
  /api/monitor/constraints/{kind}/{id} - DELETE
  /api/monitor/constraints/{kind}/{id} - PUT (subset of writable fields)

Monitor view (events).

For each event we compute:
  expected_hours    -- from the Assignment row
  assigned_hours    -- count of Lesson rows in the active solution that
                       match (teacher, class, subject)
  lessons_with_room -- count of those Lesson rows whose classroom_name
                       is set
  missing_hours     -- max(expected - assigned, 0)
  missing_room      -- assigned_hours - lessons_with_room
  group_name        -- the StudyGroup whose subject_hours include this
                       subject AND whose members include any student of
                       the class (best-effort heuristic; otherwise None)
  status            -- 'ok' if nothing is missing, otherwise a short
                       summary string

Endpoint:
  GET /api/monitor/events?q=...&sort=...
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel as _BM

from .. import models, engine_io, schemas
from ..db import get_db
from ..utils.list_query import filter_and_sort, QueryError

router = APIRouter(prefix="/api/monitor", tags=["monitor"])


def _teacher_display(t: models.Teacher) -> str:
    if t.nickname:
        return t.nickname
    if t.last_name and t.first_name:
        return f"{t.last_name} {t.first_name}"
    if t.last_name:
        return t.last_name
    if t.first_name:
        return t.first_name
    return t.name or f"docente #{t.id}"


def _build_events(db: Session) -> list[dict]:
    teachers_by_id = {t.id: t for t in db.query(models.Teacher).all()}
    classes_by_id = {c.id: c for c in db.query(models.SchoolClass).all()}
    students_by_class: dict[int, set[int]] = {}
    for s in db.query(models.Student).all():
        if s.class_id is not None:
            students_by_class.setdefault(s.class_id, set()).add(s.id)

    # Group lookup: subject -> [(group_id, group_name, member_set)]
    group_by_subject: dict[str, list[tuple[int, str, set[int]]]] = {}
    groups = {g.id: g for g in db.query(models.StudyGroup).all()}
    members_by_group: dict[int, set[int]] = {}
    for m in db.query(models.GroupMembership).all():
        members_by_group.setdefault(m.group_id, set()).add(m.student_id)
    for sh in db.query(models.GroupSubjectHours).all():
        g = groups.get(sh.group_id)
        if g is None:
            continue
        group_by_subject.setdefault(sh.subject, []).append(
            (g.id, g.name, members_by_group.get(g.id, set()))
        )

    active = engine_io.get_active_solution(db)
    lessons_by_key: dict[tuple, list[models.Lesson]] = {}
    if active is not None:
        for l in db.query(models.Lesson).filter(
            models.Lesson.solution_id == active.id
        ).all():
            key = (l.teacher_name, l.class_name, l.subject)
            lessons_by_key.setdefault(key, []).append(l)

    out: list[dict] = []
    for a in db.query(models.Assignment).all():
        t = teachers_by_id.get(a.teacher_id)
        c = classes_by_id.get(a.class_id)
        if t is None or c is None:
            continue
        key = (t.name, c.name, a.subject)
        lessons = lessons_by_key.get(key, [])
        assigned_hours = len(lessons)
        lessons_with_room = sum(1 for l in lessons if l.classroom_name)
        missing_hours = max(int(a.hours) - assigned_hours, 0)
        missing_room = max(assigned_hours - lessons_with_room, 0)

        # Best-effort group lookup
        group_name = None
        class_student_ids = students_by_class.get(c.id, set())
        for g_id, g_name, member_ids in group_by_subject.get(a.subject, []):
            if class_student_ids and member_ids & class_student_ids:
                group_name = g_name
                break
        # If subject typically requires a group (the subject has at least
        # one StudyGroup that covers it) but this event isn't covered by
        # any group, flag missing_group=True. Otherwise the event is
        # treated as "doesn't need a group" and missing_group=False.
        subject_has_groups = a.subject in group_by_subject
        missing_group = bool(subject_has_groups and group_name is None)

        # status
        bits = []
        if missing_hours:
            bits.append(f"{missing_hours} ore")
        if missing_room:
            bits.append(f"{missing_room} aule")
        if missing_group:
            bits.append("gruppo")
        status = "ok" if not bits else ", ".join(bits)

        out.append({
            "assignment_id": a.id,
            "teacher_id": t.id,
            "teacher_name": t.name,
            "teacher_display": _teacher_display(t),
            "class_id": c.id,
            "class_name": c.name,
            "class_nickname": c.nickname,
            "subject": a.subject,
            "expected_hours": int(a.hours),
            "assigned_hours": assigned_hours,
            "missing_hours": missing_hours,
            "lessons_with_room": lessons_with_room,
            "missing_room": missing_room,
            "group_name": group_name,
            "missing_group": missing_group,
            "is_complete": (missing_hours == 0 and missing_room == 0
                            and not missing_group),
            "status": status,
            "locked": bool(a.locked),
        })
    return out


_DAY_NAMES_IT_FULL = {
    1: "Lunedi", 2: "Martedi", 3: "Mercoledi",
    4: "Giovedi", 5: "Venerdi", 6: "Sabato",
}


def _build_event_rows(db: Session) -> list[dict]:
    """Lesson-level events with placeholder rows for unscheduled hours.

    Returns ONE row per Lesson in the active solution PLUS one
    placeholder row for every "missing hour" of every Assignment
    (Assignment.hours - existing Lessons). Each row has all the
    attributes the user can group by:

        teacher_name, class_name, subject, day, hour, classroom_name,
        group_name, day_name, is_scheduled, is_complete, status

    Placeholder rows have day=None, hour=None, classroom_name=None,
    is_scheduled=False. They power the red panel and are also the
    primary way "incomplete" cattedre show up in the new grouped view.
    """
    # Re-use the Assignment-level summary so we share group lookup +
    # status computation logic.
    summary_rows = _build_events(db)
    summary_by_aid = {r["assignment_id"]: r for r in summary_rows}

    teachers_by_id = {t.id: t for t in db.query(models.Teacher).all()}
    classes_by_id = {c.id: c for c in db.query(models.SchoolClass).all()}

    active = engine_io.get_active_solution(db)
    lessons_by_key: dict[tuple, list[models.Lesson]] = {}
    if active is not None:
        for l in db.query(models.Lesson).filter(
            models.Lesson.solution_id == active.id
        ).all():
            key = (l.teacher_name, l.class_name, l.subject)
            lessons_by_key.setdefault(key, []).append(l)

    out: list[dict] = []
    for a in db.query(models.Assignment).all():
        t = teachers_by_id.get(a.teacher_id)
        c = classes_by_id.get(a.class_id)
        if t is None or c is None:
            continue
        sumrow = summary_by_aid.get(a.id, {})
        group_name = sumrow.get("group_name")
        is_complete = bool(sumrow.get("is_complete"))
        status = sumrow.get("status", "")
        teacher_disp = _teacher_display(t)
        key = (t.name, c.name, a.subject)
        lessons = lessons_by_key.get(key, [])

        # One row per existing Lesson.
        for l in lessons:
            out.append({
                "assignment_id": a.id,
                "lesson_id": l.id,
                "teacher_name": t.name,
                "teacher_display": teacher_disp,
                "class_name": c.name,
                "class_nickname": c.nickname,
                "subject": a.subject,
                "day": l.day,
                "day_name": _DAY_NAMES_IT_FULL.get(l.day, ""),
                "hour": l.hour,
                "classroom_name": l.classroom_name or "",
                "group_name": group_name or "",
                "is_scheduled": True,
                "is_complete": is_complete,
                "is_locked": bool(a.locked),
                "status": ("ok" if l.classroom_name
                           else "no aula"),
                "locked": bool(a.locked),
            })

        # Placeholder rows for missing hours (Assignment.hours - len(lessons)).
        missing = max(int(a.hours) - len(lessons), 0)
        for i in range(missing):
            out.append({
                "assignment_id": a.id,
                "lesson_id": None,
                "teacher_name": t.name,
                "teacher_display": teacher_disp,
                "class_name": c.name,
                "class_nickname": c.nickname,
                "subject": a.subject,
                "day": None,
                "day_name": "",
                "hour": None,
                "classroom_name": "",
                "group_name": group_name or "",
                "is_scheduled": False,
                "is_complete": False,
                "is_locked": bool(a.locked),
                "status": "non schedulato",
                "locked": bool(a.locked),
            })
    return out


@router.get("/event-rows")
def list_event_rows(q: str | None = Query(None,
                      description="DSL filter, e.g. 'docente contains "
                                  "Rossi' or 'is_complete = 0 AND aula "
                                  "= LabFisica'"),
                    sort: str | None = Query(None,
                      description="DSL sort, e.g. 'docente' or "
                                  "'classe,giorno,ora'"),
                    limit: int | None = Query(None, ge=1, le=10000),
                    offset: int | None = Query(None, ge=0),
                    db: Session = Depends(get_db)):
    """Lesson-granular events for the grouped Monitor view. See
    `_build_event_rows` for the row shape; q/sort use the same DSL
    as the docenti / aule / classi tabs (see list_query.py).

    Pagination via `limit` + `offset` (default: no slicing -- returns
    all rows). For big schools the frontend should paginate at
    50/100/200 rows per page so the table stays responsive.

    Cache-Control: no-store so the browser doesn't return a stale
    response when the URL changes only via q/sort parameters."""
    from fastapi.responses import JSONResponse
    rows = _build_event_rows(db)
    n_total = len(rows)
    n_unscheduled = sum(1 for r in rows if not r["is_scheduled"])
    try:
        rows = filter_and_sort(rows, "event_rows", q, sort)
    except QueryError as e:
        raise HTTPException(400, f"Errore query: {e}")
    n_filtered = len(rows)
    if limit is not None:
        off = int(offset or 0)
        rows = rows[off:off + int(limit)]
    return JSONResponse(
        content={"items": rows, "n_total": n_total,
                 "n_filtered": n_filtered,
                 "n_unscheduled": n_unscheduled,
                 "limit": limit, "offset": int(offset or 0)},
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@router.delete("/lesson/{lesson_id}")
def delete_lesson(lesson_id: int, db: Session = Depends(get_db)):
    """Delete a single Lesson row from the active solution. The parent
    Assignment is preserved -- so the cattedra remains and surfaces
    as 'incomplete' in the red panel until rescheduled."""
    l = db.get(models.Lesson, lesson_id)
    if l is None:
        raise HTTPException(404, "lezione non trovata")
    active = engine_io.get_active_solution(db)
    if active is None or l.solution_id != active.id:
        raise HTTPException(
            400, "lezione non appartiene alla soluzione attiva"
        )
    db.delete(l)
    db.commit()
    return {"ok": True}


def _delete_lessons_of_assignment(db: Session, a: models.Assignment) -> int:
    """Helper: delete every Lesson in the active solution that realises
    this Assignment (matches teacher_name + class_name + subject). The
    Assignment itself is preserved -- this is the "Dissocia" semantic:
    cattedra stays, all hours go back to missing."""
    t = db.get(models.Teacher, a.teacher_id)
    c = db.get(models.SchoolClass, a.class_id)
    if t is None or c is None:
        return 0
    active = engine_io.get_active_solution(db)
    if active is None:
        return 0
    n = db.query(models.Lesson).filter(
        models.Lesson.solution_id == active.id,
        models.Lesson.teacher_name == t.name,
        models.Lesson.class_name == c.name,
        models.Lesson.subject == a.subject,
    ).delete(synchronize_session=False)
    return int(n)


class EventLockIn(_BM):
    locked: bool = True


class EventBatchIn(_BM):
    """Body for batch operations. Identifies events by Assignment ids."""
    event_ids: list[int]


class EventBatchLockIn(_BM):
    event_ids: list[int]
    # If None, the endpoint computes a TOGGLE per Giovanni's spec:
    # if any selected event is unlocked -> lock all; else unlock all.
    locked: bool | None = None


class TempLockIn(_BM):
    """Temporarily lock the Assignments NOT in `event_ids` per
    `lock_mode`, so a chained "Piazza" pipeline (greedy + phase_b +
    meta...) doesn't reshuffle events the user wanted to keep.

    Returns the list of aids that were newly locked -- the caller is
    responsible for unlocking them at the end of the pipeline (or on
    error) by POSTing /events/lock-batch with locked=false.

    `lock_mode`:
        all_others_locked              every non-target -> locked
        same_class_or_teacher_movable  non-targets that don't share
                                       teacher/class with a target are
                                       locked; siblings stay movable
        all_others_movable             nothing locked (no-op)
    """
    event_ids: list[int]
    lock_mode: str = "all_others_locked"


@router.post("/event/{assignment_id}/dissociate")
def dissociate_event(assignment_id: int, db: Session = Depends(get_db)):
    """Dissocia: keep the cattedra, delete all its Lessons in the active
    solution. The cattedra surfaces as `incomplete` with all hours
    needing re-assignment. Use this from the per-row Dissocia button
    in /monitor."""
    a = db.get(models.Assignment, assignment_id)
    if a is None:
        raise HTTPException(404, "cattedra non trovata")
    n = _delete_lessons_of_assignment(db, a)
    db.commit()
    return {"ok": True, "deleted_lessons": n,
            "assignment_id": assignment_id}


@router.post("/events/dissociate-batch")
def dissociate_events_batch(payload: EventBatchIn,
                             db: Session = Depends(get_db)):
    """Bulk dissociate. Same semantic as /event/{aid}/dissociate but
    over a list of Assignment ids."""
    n_total = 0
    n_assignments = 0
    for aid in payload.event_ids:
        a = db.get(models.Assignment, int(aid))
        if a is None:
            continue
        n_total += _delete_lessons_of_assignment(db, a)
        n_assignments += 1
    db.commit()
    return {"ok": True, "n_assignments": n_assignments,
            "deleted_lessons": n_total}


@router.post("/event/{assignment_id}/lock")
def lock_event(assignment_id: int, payload: EventLockIn,
               db: Session = Depends(get_db)):
    """Toggle (or explicitly set) the lock flag on an Assignment.
    Locked events are honoured natively by every solver path: Phase A
    pins their day-count floor, Phase B pins their slot, ALNS / VNS /
    SA / TS / ILS / Lagrangian destroy operators refuse to touch
    them, column generation pre-places them in every pattern, and
    the classroom assignment step forces the locked classroom_name."""
    a = db.get(models.Assignment, assignment_id)
    if a is None:
        raise HTTPException(404, "cattedra non trovata")
    a.locked = bool(payload.locked)
    db.commit()
    return {"ok": True, "assignment_id": assignment_id,
            "locked": bool(a.locked)}


@router.post("/events/temp-lock")
def temp_lock_events(payload: TempLockIn,
                      db: Session = Depends(get_db)):
    """Apply temporary locks per `lock_mode`. Returns the list of
    Assignment ids that were just locked (so the caller can unlock
    them later via /events/lock-batch with locked=false)."""
    if payload.lock_mode not in (
        "all_others_locked", "same_class_or_teacher_movable",
        "all_others_movable",
    ):
        raise HTTPException(400, f"lock_mode sconosciuto: {payload.lock_mode!r}")
    if payload.lock_mode == "all_others_movable":
        return {"locked_aids": [], "lock_mode": payload.lock_mode}

    target_ids = set(int(x) for x in payload.event_ids)
    target_assigns = db.query(models.Assignment).filter(
        models.Assignment.id.in_(target_ids)
    ).all()
    target_teachers = {a.teacher_id for a in target_assigns}
    target_classes = {a.class_id for a in target_assigns}

    rows = db.query(models.Assignment).filter(
        ~models.Assignment.id.in_(target_ids),
        models.Assignment.locked == False,  # noqa: E712
    ).all()
    to_lock: list[int] = []
    for a in rows:
        if payload.lock_mode == "all_others_locked":
            to_lock.append(a.id)
        elif payload.lock_mode == "same_class_or_teacher_movable":
            touches = (a.teacher_id in target_teachers
                       or a.class_id in target_classes)
            if not touches:
                to_lock.append(a.id)
    if to_lock:
        db.query(models.Assignment).filter(
            models.Assignment.id.in_(to_lock)
        ).update({"locked": True}, synchronize_session=False)
        db.commit()
    return {"locked_aids": to_lock, "lock_mode": payload.lock_mode}


@router.post("/events/lock-batch")
def lock_events_batch(payload: EventBatchLockIn,
                       db: Session = Depends(get_db)):
    """Batch lock/unlock with the toggle semantic from the spec: if
    `locked` is None, we COMPUTE the new state -- if at least one
    selected event is unlocked, we lock all; otherwise we unlock all."""
    rows = [db.get(models.Assignment, int(aid)) for aid in payload.event_ids]
    rows = [r for r in rows if r is not None]
    if not rows:
        return {"ok": True, "n_assignments": 0, "locked": False}
    if payload.locked is None:
        new_state = any(not bool(r.locked) for r in rows)
    else:
        new_state = bool(payload.locked)
    for r in rows:
        r.locked = new_state
    db.commit()
    return {"ok": True, "n_assignments": len(rows), "locked": new_state}


@router.delete("/event/{assignment_id}")
def delete_event(assignment_id: int, db: Session = Depends(get_db)):
    """Delete an entire cattedra (Assignment) AND every Lesson in the
    active solution that realised it. Use this from the grouped
    Monitor view when the user wants to remove a placeholder
    (unscheduled) event entirely.
    """
    a = db.get(models.Assignment, assignment_id)
    if a is None:
        raise HTTPException(404, "cattedra non trovata")
    t = db.get(models.Teacher, a.teacher_id)
    c = db.get(models.SchoolClass, a.class_id)
    if t is not None and c is not None:
        active = engine_io.get_active_solution(db)
        if active is not None:
            db.query(models.Lesson).filter(
                models.Lesson.solution_id == active.id,
                models.Lesson.teacher_name == t.name,
                models.Lesson.class_name == c.name,
                models.Lesson.subject == a.subject,
            ).delete(synchronize_session=False)
    db.delete(a)
    db.commit()
    return {"ok": True}


@router.get("/events")
def list_events(q: str | None = Query(None,
                  description="DSL filter, e.g. 'is_complete = 0' or "
                              "'subject = Matematica AND missing_hours > 0'"),
                sort: str | None = Query(None),
                limit: int | None = Query(None, ge=0, le=10000),
                offset: int | None = Query(None, ge=0),
                db: Session = Depends(get_db)):
    """Section 2.3 P1: pagination opt-in via ?limit=N&offset=M.
    When either is set, returns `{items, total, limit, offset}`."""
    rows = _build_events(db)
    try:
        filtered = filter_and_sort(rows, "events", q, sort)
    except QueryError as e:
        raise HTTPException(400, f"Errore query: {e}")
    from ..utils.pagination import paginated_or_list
    return paginated_or_list(filtered, limit, offset)


@router.get("/event/{assignment_id}/lessons")
def event_lessons(assignment_id: int, db: Session = Depends(get_db)):
    """Detail of all individual lessons that realise this assignment in
    the active solution. Returns for each: lesson_id, day, hour,
    classroom_name."""
    a = db.get(models.Assignment, assignment_id)
    if a is None:
        raise HTTPException(404, "assignment non trovata")
    t = db.get(models.Teacher, a.teacher_id)
    c = db.get(models.SchoolClass, a.class_id)
    if t is None or c is None:
        raise HTTPException(404, "assignment con docente/classe mancante")
    active = engine_io.get_active_solution(db)
    if active is None:
        return {"assignment_id": assignment_id, "lessons": [],
                "expected_hours": int(a.hours), "active_solution": None}
    lessons = db.query(models.Lesson).filter(
        models.Lesson.solution_id == active.id,
        models.Lesson.teacher_name == t.name,
        models.Lesson.class_name == c.name,
        models.Lesson.subject == a.subject,
    ).order_by(models.Lesson.day, models.Lesson.hour).all()
    out = []
    for l in lessons:
        out.append({
            "lesson_id": l.id,
            "day": l.day,
            "hour": l.hour,
            "classroom_name": l.classroom_name,
        })
    return {
        "assignment_id": assignment_id,
        "active_solution": active.id,
        "teacher_name": t.name,
        "class_name": c.name,
        "subject": a.subject,
        "expected_hours": int(a.hours),
        "lessons": out,
    }


from pydantic import BaseModel as _BM


# ---------------------------------------------------------------------
# Shared conflict helpers (used by reassign_lesson and add_event)
# ---------------------------------------------------------------------

# Strategy aliases. 'unassign' / 'optimize' are the legacy names from
# the old monitor flow; the user-facing UI now uses 'svincola' (unbind)
# and 'elimina' (delete) per Giovanni's spec.
_RESOLUTION_ALIASES = {
    "unassign": "delete",
    "optimize": "delete",
    "svincola": "unbind",
    "elimina":  "delete",
}


def _summarise_lessons(rows: list[models.Lesson]) -> list[dict]:
    # `locked` travels so the conflict modal can mark a pinned row: both
    # resolutions below ('unbind' and 'delete') destroy the conflicting
    # lesson, and a pin is exactly the thing the school asked not to lose
    # by accident.
    return [{"lesson_id": r.id, "teacher_name": r.teacher_name,
             "class_name": r.class_name, "subject": r.subject,
             "day": r.day, "hour": r.hour,
             "classroom_name": r.classroom_name,
             "locked": bool(r.locked)}
            for r in rows]


def _add_event_conflicts(
    db: Session,
    active_id: int,
    teacher_name: str | None,
    class_name: str | None,
    classroom_name: str | None,
    day: int,
    hour: int,
    exclude_lesson_id: int | None = None,
) -> dict:
    """Generic conflict probe at (day, hour) for any of the three
    dimensions. Used for new-lesson insertion (no `target` Lesson)."""
    qry = db.query(models.Lesson).filter(
        models.Lesson.solution_id == active_id,
        models.Lesson.day == int(day),
        models.Lesson.hour == int(hour),
    )
    if exclude_lesson_id is not None:
        qry = qry.filter(models.Lesson.id != int(exclude_lesson_id))
    rows = qry.all()
    teacher_busy: list[models.Lesson] = []
    class_busy: list[models.Lesson] = []
    room_busy: list[models.Lesson] = []
    for r in rows:
        if teacher_name and r.teacher_name == teacher_name:
            teacher_busy.append(r)
        if class_name and r.class_name == class_name:
            class_busy.append(r)
        if (classroom_name and r.classroom_name == classroom_name
                and classroom_name != ""):
            room_busy.append(r)
    return {
        "teacher_busy": teacher_busy,
        "class_busy": class_busy,
        "room_busy": room_busy,
    }


def _apply_conflict_resolution(db: Session, cinfo: dict, strategy: str) -> None:
    """In-place: apply 'unbind' (svincola) or 'delete' (elimina) to
    the conflicting Lessons in `cinfo`. Caller commits."""
    deleted: set[int] = set()
    if strategy == "delete":
        for bucket in ("teacher_busy", "class_busy", "room_busy"):
            for r in cinfo[bucket]:
                if r.id in deleted:
                    continue
                deleted.add(r.id)
                db.delete(r)
    else:  # 'unbind' (svincola)
        # teacher/class conflicts cannot be partially unbound: delete.
        for bucket in ("teacher_busy", "class_busy"):
            for r in cinfo[bucket]:
                if r.id in deleted:
                    continue
                deleted.add(r.id)
                db.delete(r)
        # room-only conflicts: clear the classroom field, keep the row.
        for r in cinfo["room_busy"]:
            if r.id in deleted:
                continue
            r.classroom_name = None
    db.flush()


class LessonReassignIn(_BM):
    """Move/edit a single lesson realising an assignment.

    Either day+hour (re-time) or classroom_name (re-room) or both can
    change. `on_conflict` accepts (after alias normalisation):
        'dry_run' - just report; do not persist.
        'cancel'  - abort with the conflict report.
        'unbind'  - svincola: room conflicts -> clear conflicting
                    classroom_name only; teacher/class conflicts ->
                    delete the conflicting Lesson rows (no per-attribute
                    unbind possible).
        'delete'  - elimina: delete every conflicting Lesson row.

    Backward-compat aliases: 'unassign' -> 'delete', 'optimize' ->
    'delete'.

    `unlock` confirms re-timing a lesson pinned to its slot
    (`Lesson.locked`). Without it a re-time of a pinned lesson is
    refused with `needs_unlock`, matching /schedule's drag-and-drop:
    same lesson, same user, two pages, one semantics.
    """
    day: int | None = None
    hour: int | None = None
    unlock: bool = False
    classroom_name: str | None = None  # None = leave as-is; '' = clear
    on_conflict: str = "dry_run"


def _conflict_lessons(db, active_id: int, target: models.Lesson,
                      new_day: int, new_hour: int,
                      new_room: str | None) -> dict:
    """Look for HARD conflicts at the destination (day, hour) excluding
    `target` itself. Returns dict with three buckets."""
    return _add_event_conflicts(
        db, active_id, target.teacher_name, target.class_name,
        new_room, new_day, new_hour, exclude_lesson_id=target.id,
    )


@router.put("/event/{assignment_id}/lesson/{lesson_id}")
def reassign_lesson(assignment_id: int, lesson_id: int,
                    payload: LessonReassignIn,
                    db: Session = Depends(get_db)):
    """Move a single lesson to a new (day, hour) and/or classroom,
    detecting conflicts and offering resolutions."""
    a = db.get(models.Assignment, assignment_id)
    if a is None:
        raise HTTPException(404, "assignment non trovata")
    target = db.get(models.Lesson, lesson_id)
    if target is None:
        raise HTTPException(404, "lezione non trovata")
    active = engine_io.get_active_solution(db)
    if active is None or target.solution_id != active.id:
        raise HTTPException(400, "lezione non appartiene alla soluzione attiva")

    new_day = int(payload.day) if payload.day is not None else target.day
    new_hour = int(payload.hour) if payload.hour is not None else target.hour
    if new_day not in _DAYS or new_hour not in _HOURS:
        raise HTTPException(400, "day/hour fuori range")
    new_room = (target.classroom_name if payload.classroom_name is None
                else (payload.classroom_name or None))

    # Same slot + same room ? noop
    if (new_day == target.day and new_hour == target.hour
            and new_room == target.classroom_name):
        return {"ok": True, "no_change": True}

    # A pin is refusable-but-overridable: ask, don't relocate it silently.
    # Only a RE-TIME trips this -- `Lesson.locked` pins the lesson to its
    # (day, hour), so re-rooming in place does not touch what was pinned.
    # Checked ahead of the conflict probe so the confirmation round-trip
    # stays a single cheap question, and so a pinned lesson is never
    # reported as a conflict-resolution problem when the real question is
    # whether the pin should go at all.
    retimed = (new_day != target.day or new_hour != target.hour)
    if retimed and target.locked and not payload.unlock:
        return {"ok": False, "needs_unlock": True,
                "reason": ("La lezione e` bloccata in questo slot. "
                           "Spostarla la sblocchera`.")}

    cinfo = _conflict_lessons(db, active.id, target, new_day, new_hour,
                              new_room)
    has_conflict = bool(cinfo["teacher_busy"] or cinfo["class_busy"]
                         or cinfo["room_busy"])

    conflict_payload = {
        "teacher_busy": _summarise_lessons(cinfo["teacher_busy"]),
        "class_busy": _summarise_lessons(cinfo["class_busy"]),
        "room_busy": _summarise_lessons(cinfo["room_busy"]),
    }
    strategy = _RESOLUTION_ALIASES.get(
        payload.on_conflict, payload.on_conflict,
    )

    if has_conflict and payload.on_conflict == "dry_run":
        return {"ok": False, "conflict": True, "details": conflict_payload}

    if has_conflict and payload.on_conflict == "cancel":
        return {"ok": False, "cancelled": True, "conflict": True,
                "details": conflict_payload}

    if has_conflict:
        if strategy not in ("unbind", "delete"):
            raise HTTPException(
                400, f"on_conflict sconosciuto: {payload.on_conflict!r}",
            )
        _apply_conflict_resolution(db, cinfo, strategy)

    # Apply the move
    target.day = new_day
    target.hour = new_hour
    # The confirmed re-time consumes the pin: it pinned the OLD slot, and
    # carrying it to the new one would silently re-pin a slot the school
    # never chose. /schedule lands the same move unpinned (there because
    # the row is recreated under a new key); do it explicitly here.
    unlocked = retimed and bool(target.locked)
    if unlocked:
        target.locked = False
    if payload.classroom_name is not None:
        target.classroom_name = (payload.classroom_name or None)
    db.commit()

    return {
        "ok": True,
        "conflict": has_conflict,
        "resolution": (strategy if has_conflict else None),
        "details": conflict_payload,
        "unlocked": unlocked,
        "moved_to": {"day": new_day, "hour": new_hour,
                     "classroom_name": target.classroom_name},
    }


@router.get("/incomplete-events")
def list_incomplete_events(db: Session = Depends(get_db)):
    """Events whose Assignment lacks at least one Lesson row (missing
    temporal assignment). Powers the red/toggleable panel on /monitor.

    An event is "incomplete by time" when `missing_hours > 0`, i.e.
    when the active solution does not (yet) realise all hours of the
    Assignment. We also surface events with `assigned_hours == 0` so
    that brand-new assignments without any Lesson row appear here.
    """
    rows = _build_events(db)
    out = [r for r in rows
           if int(r.get("missing_hours") or 0) > 0
           or int(r.get("assigned_hours") or 0) == 0]
    out.sort(key=lambda r: (r["class_name"], r["subject"], r["teacher_name"]))
    return {
        "n_total": len(rows),
        "n_incomplete": len(out),
        "items": out,
    }


@router.post("/event", response_model=schemas.AddEventOut)
def add_event(payload: schemas.AddEventIn,
              db: Session = Depends(get_db)) -> dict:
    """Create a new Assignment (event), optionally also creating one
    Lesson row at (day, hour). When day/hour are omitted the
    Assignment is created in "incomplete" state and surfaces in the
    red panel of /monitor.

    Conflict resolution semantics for the optional Lesson placement
    mirror /api/schedule/lesson:
        dry_run | cancel | unbind | delete (+ aliases unassign/optimize).
    """
    # Validate refs
    cls = db.query(models.SchoolClass).filter(
        models.SchoolClass.name == payload.class_name).first()
    if cls is None:
        raise HTTPException(404, f"classe {payload.class_name!r} non trovata")
    t = db.query(models.Teacher).filter(
        models.Teacher.name == payload.teacher_name).first()
    if t is None:
        raise HTTPException(404, f"docente {payload.teacher_name!r} non trovato")
    if not payload.subject or not payload.subject.strip():
        raise HTTPException(400, "subject obbligatorio")
    if int(payload.hours) <= 0:
        raise HTTPException(400, "hours deve essere > 0")

    # An Assignment is unique on (class_id, subject). If one already
    # exists for this (class, subject) and is owned by ANOTHER teacher,
    # we don't crash anymore (per Giovanni's spec): we return a
    # `warning='cattedra_clash'` so the frontend can ask the user to
    # confirm. On confirmation it re-posts with `force=True`, which
    # SKIPS the Assignment creation entirely and creates an "orphan"
    # Lesson at (day, hour). Without day+hour the orphan path is
    # meaningless, so force=True without day/hour returns 400.
    existing = db.query(models.Assignment).filter(
        models.Assignment.class_id == cls.id,
        models.Assignment.subject == payload.subject,
    ).first()
    cattedra_clash = (existing is not None
                      and existing.teacher_id != t.id)
    if cattedra_clash and not payload.force:
        other_t = db.get(models.Teacher, existing.teacher_id)
        return {
            "ok": False,
            "warning": "cattedra_clash",
            "details": {
                "class_name": cls.name,
                "subject": payload.subject,
                "owned_by_teacher_name": (other_t.name if other_t else None),
                "owned_by_teacher_display": (
                    _teacher_display(other_t) if other_t else None
                ),
                "existing_assignment_id": existing.id,
            },
        }
    if cattedra_clash and payload.force:
        if payload.day is None or payload.hour is None:
            raise HTTPException(
                400,
                "force=True senza giorno/ora non ha effetto: la "
                "cattedra esiste gia' di un altro docente. Specifica "
                "almeno (day, hour) per creare un evento orfano."
            )

    # Optionally place an initial Lesson; detect conflicts only if both
    # a day/hour AND an active solution are present.
    place_lesson = payload.day is not None and payload.hour is not None
    active = engine_io.get_active_solution(db) if place_lesson else None
    conflict_payload: dict = {}
    has_conflict = False
    strategy = (_RESOLUTION_ALIASES.get(payload.on_conflict, payload.on_conflict)
                if place_lesson else payload.on_conflict)
    if place_lesson:
        if int(payload.day) not in _DAYS or int(payload.hour) not in _HOURS:
            raise HTTPException(400, "day/hour fuori range")
        if active is not None:
            cinfo = _add_event_conflicts(
                db, active.id, payload.teacher_name, payload.class_name,
                payload.classroom_name, int(payload.day), int(payload.hour),
            )
            has_conflict = bool(
                cinfo["teacher_busy"] or cinfo["class_busy"]
                or cinfo["room_busy"]
            )
            if has_conflict:
                conflict_payload = {
                    "teacher_busy": _summarise_lessons(cinfo["teacher_busy"]),
                    "class_busy": _summarise_lessons(cinfo["class_busy"]),
                    "room_busy": _summarise_lessons(cinfo["room_busy"]),
                }
                if payload.on_conflict == "dry_run":
                    return {"ok": False, "conflict": True,
                            "details": conflict_payload}
                if payload.on_conflict == "cancel":
                    return {"ok": False, "conflict": True,
                            "resolution": "cancel",
                            "details": conflict_payload}
                if strategy not in ("unbind", "delete"):
                    raise HTTPException(
                        400, f"on_conflict sconosciuto: {payload.on_conflict!r}",
                    )
                _apply_conflict_resolution(db, cinfo, strategy)

    # Persist Assignment unless we're in the "orphan lesson" path
    # (cattedra already exists with another teacher and force=True).
    a_id: int | None = None
    if not cattedra_clash:
        a = models.Assignment(
            class_id=cls.id, teacher_id=t.id,
            subject=payload.subject, hours=int(payload.hours),
            locked=bool(payload.locked),
        )
        db.add(a)
        db.flush()
        a_id = a.id

    # Persist optional initial Lesson. NOTE: a Lesson is identified by
    # (teacher_name, class_name, subject) -- it does NOT FK-link to an
    # Assignment, so creating an orphan Lesson is supported by the
    # data model.
    lesson_id: int | None = None
    if place_lesson and active is not None:
        l = models.Lesson(
            solution_id=active.id,
            teacher_name=t.name, class_name=cls.name,
            subject=payload.subject,
            day=int(payload.day), hour=int(payload.hour),
            classroom_name=payload.classroom_name or None,
        )
        db.add(l)
        db.flush()
        lesson_id = l.id

    db.commit()
    return {
        "ok": True,
        "conflict": has_conflict,
        "warning": "cattedra_orphan_lesson" if cattedra_clash else None,
        "assignment_id": a_id,
        "lesson_id": lesson_id,
        "resolution": (strategy if (place_lesson and has_conflict) else None),
        "details": conflict_payload,
    }


@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    """Section 2.4 P1: cached 15s with mutation invalidation. Plus
    Cache-Control: no-store so browser doesn't keep a stale copy after
    an import."""
    from fastapi.responses import JSONResponse
    from ..utils.ttl_cache import cached as ttl_cached

    def _compute():
        rows = _build_events(db)
        n = len(rows)
        n_incomplete = sum(1 for r in rows if not r["is_complete"])
        # Also expose lesson-granularity counts for the segmented
        # control in /monitor (Tutti / Incompleti / Lockati).
        event_rows = _build_event_rows(db)
        n_rows = len(event_rows)
        n_rows_locked = sum(1 for r in event_rows if r.get("is_locked"))
        n_rows_unscheduled = sum(1 for r in event_rows
                                 if not r.get("is_scheduled"))
        return {
            "n_events": n,
            "n_incomplete": n_incomplete,
            "n_missing_hours": sum(1 for r in rows if r["missing_hours"]),
            "n_missing_room": sum(1 for r in rows if r["missing_room"]),
            "n_missing_group": sum(1 for r in rows if r["missing_group"]),
            "n_rows": n_rows,
            "n_rows_locked": n_rows_locked,
            "n_rows_unscheduled": n_rows_unscheduled,
        }
    body = ttl_cached(
        "monitor.summary", ttl_s=15.0, mutation_aware=True,
        compute=_compute,
    )
    return JSONResponse(
        content=body,
        headers={"Cache-Control": "no-store, max-age=0"},
    )


# ---------- Constraints view ----------


_DAY_CODE = {1: "lun", 2: "mar", 3: "mer", 4: "gio", 5: "ven", 6: "sab"}
_DAYS = (1, 2, 3, 4, 5, 6)
_HOURS = (8, 9, 10, 11, 12, 13)


def _slot_label(day: int, hour: int) -> str:
    return f"{_DAY_CODE.get(day, '?')}{hour}"


def _build_constraints(db: Session) -> list[dict]:
    out: list[dict] = []
    teachers = {t.id: t for t in db.query(models.Teacher).all()}
    classes = {c.id: c for c in db.query(models.SchoolClass).all()}
    rooms = {r.id: r for r in db.query(models.Classroom).all()}

    # Availability cells -- teacher / class / classroom
    for u in db.query(models.TeacherUnavailability).all():
        t = teachers.get(u.teacher_id)
        if t is None:
            continue
        out.append({
            "kind": "teacher_cell",
            "id": u.id,
            "scope": "docente",
            "owner_id": t.id,
            "owner_name": _teacher_display(t),
            "level": u.state,
            "weight": int(u.soft_penalty or 0),
            "detail": _slot_label(u.day, u.hour),
            "extra": u.reason or "",
            "editable": True,
        })
    for u in db.query(models.ClassUnavailability).all():
        c = classes.get(u.class_id)
        if c is None:
            continue
        out.append({
            "kind": "class_cell",
            "id": u.id,
            "scope": "classe",
            "owner_id": c.id,
            "owner_name": c.name,
            "level": u.state,
            "weight": int(u.soft_penalty or 0),
            "detail": _slot_label(u.day, u.hour),
            "extra": u.reason or "",
            "editable": True,
        })
    for u in db.query(models.ClassroomUnavailability).all():
        r = rooms.get(u.classroom_id)
        if r is None:
            continue
        out.append({
            "kind": "room_cell",
            "id": u.id,
            "scope": "aula",
            "owner_id": r.id,
            "owner_name": r.name,
            "level": u.state,
            "weight": int(u.soft_penalty or 0),
            "detail": _slot_label(u.day, u.hour),
            "extra": u.reason or "",
            "editable": True,
        })

    # Logical constraints (teacher/class/classroom)
    import json as _json
    for r in db.query(models.LogicalUnavailability).all():
        scope_map = {"teacher": "docente", "class": "classe",
                     "classroom": "aula"}
        owner_name = ""
        if r.entity_type == "teacher":
            t = teachers.get(r.entity_id)
            if t: owner_name = _teacher_display(t)
        elif r.entity_type == "class":
            c = classes.get(r.entity_id)
            if c: owner_name = c.name
        elif r.entity_type == "classroom":
            cr = rooms.get(r.entity_id)
            if cr: owner_name = cr.name
        try:
            clauses = _json.loads(r.parsed_dnf_json or "[]")
        except Exception:
            clauses = []
        from ..utils.logic_parser import dnf_to_pretty
        pretty = dnf_to_pretty(clauses) or r.expression
        out.append({
            "kind": f"logical_{r.entity_type}",
            "id": r.id,
            "scope": scope_map.get(r.entity_type, r.entity_type),
            "owner_id": r.entity_id,
            "owner_name": owner_name or f"#{r.entity_id}",
            "level": r.kind or ("hard" if r.is_hard
                                else ("preferred"
                                      if (r.soft_penalty or 0) < 0 else "soft")),
            "weight": int(r.soft_penalty or 0),
            "detail": pretty,
            "extra": r.expression,
            "editable": True,
        })

    # Curriculum logical constraints
    curr_by_id = {c.id: c for c in db.query(models.Curriculum).all()}
    for r in db.query(models.CurriculumLogicalConstraint).all():
        c = curr_by_id.get(r.curriculum_id)
        owner_name = c.code if c else f"#{r.curriculum_id}"
        try:
            clauses = _json.loads(r.parsed_dnf_json or "[]")
        except Exception:
            clauses = []
        from ..utils.logic_parser import dnf_to_pretty
        pretty = dnf_to_pretty(clauses) or r.expression
        out.append({
            "kind": "logical_curriculum",
            "id": r.id,
            "scope": "indirizzo",
            "owner_id": r.curriculum_id,
            "owner_name": owner_name,
            "level": r.kind or ("hard" if r.is_hard
                                else ("preferred"
                                      if (r.soft_penalty or 0) < 0 else "soft")),
            "weight": int(r.soft_penalty or 0),
            "detail": (r.label + ": " if r.label else "") + pretty
                       + (f" [anno {r.year_filter}]" if r.year_filter else ""),
            "extra": r.expression,
            "editable": True,
        })

    # Co-teaching rules
    for ct in db.query(models.CoTeachingRule).all():
        c = classes.get(ct.class_id)
        if c is None:
            continue
        out.append({
            "kind": "coteach",
            "id": ct.id,
            "scope": "classe",
            "owner_id": c.id,
            "owner_name": c.name,
            "subject": ct.subject,
            "level": "hard" if ct.required else "soft",
            "weight": int(ct.weight or 0),
            "detail": (f"{ct.subject}: {ct.n_teachers} docenti"
                       + (f" ({ct.teacher_csv})" if ct.teacher_csv else "")),
            "extra": ct.subject,
            "editable": True,
        })

    # Subject <-> Classroom prefs (only non-default)
    for sp in db.query(models.ClassroomSubjectPreference).all():
        if (sp.state or "allowed") == "allowed":
            continue
        room = rooms.get(sp.classroom_id)
        if room is None:
            continue
        out.append({
            "kind": "subject_room_pref",
            "id": sp.id,
            "scope": "materia/aula",
            "owner_id": sp.classroom_id,
            "owner_name": f"{sp.subject} <-> {room.name}",
            "subject": sp.subject,
            "level": sp.state,
            "weight": int(sp.weight or 0),
            "detail": room.name,
            "extra": sp.subject,
            "editable": True,
        })

    # Teacher <-> Classroom prefs
    for tp in db.query(models.TeacherClassroomPreference).all():
        if (tp.state or "allowed") == "allowed":
            continue
        t = teachers.get(tp.teacher_id)
        room = rooms.get(tp.classroom_id)
        if t is None or room is None:
            continue
        out.append({
            "kind": "teacher_room_pref",
            "id": tp.id,
            "scope": "docente/aula",
            "owner_id": tp.teacher_id,
            "owner_name": f"{_teacher_display(t)} <-> {room.name}",
            "secondary_owner_id": tp.classroom_id,
            "level": tp.state,
            "weight": int(tp.weight or 0),
            "detail": room.name,
            "extra": "",
            "editable": True,
        })

    return out


def _detect_conflicts(rows: list[dict], db: Session) -> list[dict]:
    """Best-effort conflict detector across the flattened constraint list.

    Each conflict is a dict with `kind`, `reason`, and `members` (a list
    of {kind, id, owner_name, detail}). Detection covers:
      - matrix HARD + ENFORCED on the same (owner, slot)
      - ENFORCED on a free_day for teachers
      - logical HARD/ENFORCED rules that no slot configuration could
        satisfy given the other matrix HARD cells of the same owner
    """
    conflicts: list[dict] = []

    # Group cells by (kind/owner, slot)
    by_owner_slot: dict[tuple[str, str, str], list[dict]] = {}
    for r in rows:
        if r["kind"] in ("teacher_cell", "class_cell", "room_cell"):
            key = (r["scope"], r["owner_name"], r["detail"])
            by_owner_slot.setdefault(key, []).append(r)

    for (scope, owner, slot), group in by_owner_slot.items():
        levels = {g["level"] for g in group}
        if "hard" in levels and "enforced" in levels:
            conflicts.append({
                "kind": "matrix_hard_enforced",
                "reason": (f"{scope} {owner}: cella {slot} marcata sia HARD "
                           f"(non disponibile) sia ENFORCED (deve esserci)."),
                "members": group,
            })

    # Free_day vs enforced (teacher only)
    teachers = {t.id: t for t in db.query(models.Teacher).all()}
    free_day_int = {
        "Monday": 1, "Tuesday": 2, "Wednesday": 3,
        "Thursday": 4, "Friday": 5, "Saturday": 6,
        "Lunedi": 1, "Martedi": 2, "Mercoledi": 3,
        "Giovedi": 4, "Venerdi": 5, "Sabato": 6,
    }
    for u in db.query(models.TeacherUnavailability).filter(
        models.TeacherUnavailability.state == "enforced"
    ).all():
        t = teachers.get(u.teacher_id)
        if t is None or not t.free_day:
            continue
        d = free_day_int.get(t.free_day)
        if d == u.day:
            members = [r for r in rows
                       if r["kind"] == "teacher_cell"
                       and r["id"] == u.id]
            conflicts.append({
                "kind": "enforced_on_free_day",
                "reason": (f"docente {_teacher_display(t)}: cella ENFORCED in "
                           f"{_slot_label(u.day, u.hour)} ma il suo "
                           f"giorno libero e' {t.free_day}."),
                "members": members,
            })

    # Logical HARD/ENFORCED rules over slot literals: check if any clause
    # is satisfiable given the owner's HARD-availability matrix.
    import json as _json
    from ..utils.logic_parser import evaluate_against_unavailable

    def _hard_set_for(scope: str, owner_id: int) -> set[tuple[int, int]]:
        out: set[tuple[int, int]] = set()
        if scope == "teacher":
            rows_q = db.query(models.TeacherUnavailability).filter(
                models.TeacherUnavailability.teacher_id == owner_id,
                models.TeacherUnavailability.state == "hard",
            ).all()
        elif scope == "class":
            rows_q = db.query(models.ClassUnavailability).filter(
                models.ClassUnavailability.class_id == owner_id,
                models.ClassUnavailability.state == "hard",
            ).all()
        elif scope == "classroom":
            rows_q = db.query(models.ClassroomUnavailability).filter(
                models.ClassroomUnavailability.classroom_id == owner_id,
                models.ClassroomUnavailability.state == "hard",
            ).all()
        else:
            rows_q = []
        for r in rows_q:
            out.add((r.day, r.hour))
        return out

    for r in db.query(models.LogicalUnavailability).all():
        if (r.kind or ("hard" if r.is_hard else "")) not in ("hard", "enforced"):
            continue
        try:
            clauses = _json.loads(r.parsed_dnf_json or "[]")
        except Exception:
            clauses = []
        unav = _hard_set_for(r.entity_type, r.entity_id)
        ok = evaluate_against_unavailable(clauses, unav)
        if ok:
            continue
        # Match the row in the flat list
        target = None
        for x in rows:
            if x["kind"] == f"logical_{r.entity_type}" and x["id"] == r.id:
                target = x
                break
        if target is None:
            continue
        conflicts.append({
            "kind": "logical_unsatisfiable",
            "reason": (f"vincolo logico {target['level'].upper()} su "
                       f"{target['scope']} {target['owner_name']} "
                       f"non soddisfatto dalla matrice HARD attuale: "
                       f"{target['detail']}."),
            "members": [target],
        })

    return conflicts


@router.get("/conflicts")
def list_conflicts(db: Session = Depends(get_db)):
    rows = _build_constraints(db)
    return _detect_conflicts(rows, db)


@router.get("/constraints")
def list_constraints(q: str | None = Query(None),
                     sort: str | None = Query(None),
                     db: Session = Depends(get_db)):
    rows = _build_constraints(db)
    try:
        return filter_and_sort(rows, "constraints", q, sort)
    except QueryError as e:
        raise HTTPException(400, f"Errore query: {e}")


@router.delete("/constraints/{kind}/{cid}")
def delete_constraint(kind: str, cid: int, db: Session = Depends(get_db)):
    """Remove the underlying row pointed to by (kind, id)."""
    if kind == "teacher_cell":
        row = db.get(models.TeacherUnavailability, cid)
    elif kind == "class_cell":
        row = db.get(models.ClassUnavailability, cid)
    elif kind == "room_cell":
        row = db.get(models.ClassroomUnavailability, cid)
    elif kind in ("logical_teacher", "logical_class", "logical_classroom"):
        row = db.get(models.LogicalUnavailability, cid)
    elif kind == "logical_curriculum":
        row = db.get(models.CurriculumLogicalConstraint, cid)
    elif kind == "coteach":
        row = db.get(models.CoTeachingRule, cid)
    elif kind == "subject_room_pref":
        row = db.get(models.ClassroomSubjectPreference, cid)
    elif kind == "teacher_room_pref":
        row = db.get(models.TeacherClassroomPreference, cid)
    else:
        raise HTTPException(400, f"kind sconosciuto: {kind}")
    if row is None:
        raise HTTPException(404, "vincolo non trovato")
    db.delete(row)
    db.commit()
    return {"ok": True}


from pydantic import BaseModel


class ConstraintPatchIn(BaseModel):
    """Subset of writable fields. Only the fields relevant to the
    constraint kind are honoured.

    `owner_id` re-points the vincolo at a different entity:
        teacher_cell / logical_teacher  -> teachers.id
        class_cell   / logical_class    -> school_classes.id
        room_cell    / logical_classroom -> classrooms.id
        logical_curriculum               -> curricula.id
        coteach                          -> school_classes.id
        subject_room_pref / teacher_room_pref -> classrooms.id
            (for teacher_room_pref the secondary teacher_id is read
             from the optional `secondary_owner_id` field)
    `subject` is honoured by subject_room_pref / coteach.
    """
    level: str | None = None        # hard|soft|preferred|enforced|allowed|forbidden
    weight: int | None = None
    expression: str | None = None
    reason: str | None = None
    owner_id: int | None = None
    secondary_owner_id: int | None = None
    subject: str | None = None


@router.put("/constraints/{kind}/{cid}")
def update_constraint(kind: str, cid: int,
                      payload: ConstraintPatchIn,
                      db: Session = Depends(get_db)):
    if kind in ("teacher_cell", "class_cell", "room_cell"):
        Model = {"teacher_cell": models.TeacherUnavailability,
                 "class_cell":   models.ClassUnavailability,
                 "room_cell":    models.ClassroomUnavailability}[kind]
        owner_field = {"teacher_cell": "teacher_id",
                       "class_cell":   "class_id",
                       "room_cell":    "classroom_id"}[kind]
        row = db.get(Model, cid)
        if row is None:
            raise HTTPException(404, "vincolo non trovato")
        if payload.level is not None and payload.level in (
            "hard", "soft", "preferred", "enforced"
        ):
            row.state = payload.level
        if payload.weight is not None:
            row.soft_penalty = int(payload.weight)
        if payload.reason is not None:
            row.reason = payload.reason
        if payload.owner_id is not None:
            setattr(row, owner_field, int(payload.owner_id))
        db.commit()
        return {"ok": True}

    if kind in ("logical_teacher", "logical_class", "logical_classroom"):
        row = db.get(models.LogicalUnavailability, cid)
        if row is None:
            raise HTTPException(404, "vincolo non trovato")
        if payload.expression is not None and payload.expression.strip():
            from ..utils.logic_parser import parse_to_dnf, LogicError
            try:
                parsed = parse_to_dnf(payload.expression)
            except LogicError as e:
                raise HTTPException(400, f"sintassi non valida: {e}")
            import json as _json
            row.expression = payload.expression
            row.parsed_dnf_json = _json.dumps(parsed.clauses)
        if payload.level is not None and payload.level in (
            "hard", "soft", "preferred", "enforced"
        ):
            row.kind = payload.level
            if payload.level == "hard" or payload.level == "enforced":
                row.is_hard = True
            else:
                row.is_hard = False
        if payload.weight is not None:
            pen = int(payload.weight)
            if (row.kind or "soft") == "preferred" and pen > 0:
                pen = -abs(pen)
            if (row.kind or "soft") == "soft" and pen < 0:
                pen = abs(pen)
            row.soft_penalty = pen
        if payload.owner_id is not None:
            row.entity_id = int(payload.owner_id)
        db.commit()
        return {"ok": True}

    if kind == "logical_curriculum":
        row = db.get(models.CurriculumLogicalConstraint, cid)
        if row is None:
            raise HTTPException(404, "vincolo non trovato")
        if payload.expression is not None and payload.expression.strip():
            from ..utils.logic_parser import parse_to_dnf, LogicError
            try:
                parsed = parse_to_dnf(payload.expression)
            except LogicError as e:
                raise HTTPException(400, f"sintassi non valida: {e}")
            import json as _json
            row.expression = payload.expression
            row.parsed_dnf_json = _json.dumps(parsed.clauses)
        if payload.level is not None and payload.level in (
            "hard", "soft", "preferred", "enforced"
        ):
            row.kind = payload.level
            row.is_hard = payload.level in ("hard", "enforced")
        if payload.weight is not None:
            pen = int(payload.weight)
            if (row.kind or "soft") == "preferred" and pen > 0:
                pen = -abs(pen)
            if (row.kind or "soft") == "soft" and pen < 0:
                pen = abs(pen)
            row.soft_penalty = pen
        if payload.owner_id is not None:
            row.curriculum_id = int(payload.owner_id)
        db.commit()
        return {"ok": True}

    if kind == "subject_room_pref":
        row = db.get(models.ClassroomSubjectPreference, cid)
        if row is None:
            raise HTTPException(404, "vincolo non trovato")
        if payload.level is not None and payload.level in (
            "allowed", "soft", "preferred", "forbidden", "enforced"
        ):
            row.state = payload.level
            row.required = (payload.level == "enforced")
        if payload.weight is not None:
            row.weight = float(payload.weight)
        if payload.owner_id is not None:
            row.classroom_id = int(payload.owner_id)
        if payload.subject is not None and payload.subject.strip():
            row.subject = payload.subject.strip()
        db.commit()
        return {"ok": True}

    if kind == "teacher_room_pref":
        row = db.get(models.TeacherClassroomPreference, cid)
        if row is None:
            raise HTTPException(404, "vincolo non trovato")
        if payload.level is not None and payload.level in (
            "allowed", "soft", "preferred", "forbidden", "enforced"
        ):
            row.state = payload.level
        if payload.weight is not None:
            row.weight = float(payload.weight)
        if payload.owner_id is not None:
            row.teacher_id = int(payload.owner_id)
        if payload.secondary_owner_id is not None:
            row.classroom_id = int(payload.secondary_owner_id)
        db.commit()
        return {"ok": True}

    if kind == "coteach":
        row = db.get(models.CoTeachingRule, cid)
        if row is None:
            raise HTTPException(404, "vincolo non trovato")
        if payload.level is not None:
            row.required = (payload.level == "hard")
        if payload.weight is not None:
            row.weight = float(payload.weight)
        if payload.owner_id is not None:
            row.class_id = int(payload.owner_id)
        if payload.subject is not None and payload.subject.strip():
            row.subject = payload.subject.strip()
        db.commit()
        return {"ok": True}

    raise HTTPException(400, f"kind sconosciuto: {kind}")
