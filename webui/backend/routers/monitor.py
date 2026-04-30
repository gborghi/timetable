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

from .. import models, engine_io
from ..db import get_db
from ..utils.list_query import filter_and_sort, QueryError

router = APIRouter(prefix="/api/monitor", tags=["monitor"])


def _teacher_display(t: models.Teacher) -> str:
    if t.nickname:
        return t.nickname
    if t.last_name and t.first_name:
        return f"{t.last_name} {t.first_name}"
    return t.name


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


@router.get("/events")
def list_events(q: str | None = Query(None,
                  description="DSL filter, e.g. 'is_complete = 0' or "
                              "'subject = Matematica AND missing_hours > 0'"),
                sort: str | None = Query(None),
                db: Session = Depends(get_db)):
    rows = _build_events(db)
    try:
        return filter_and_sort(rows, "events", q, sort)
    except QueryError as e:
        raise HTTPException(400, f"Errore query: {e}")


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


class LessonReassignIn(_BM):
    """Move/edit a single lesson realising an assignment.

    Either day+hour (re-time) or classroom_name (re-room) or both can
    change. Set on_conflict to choose how to handle a clash:
        'dry_run'    - just report; do not persist
        'unassign'   - clear the conflicting lesson(s) at dst (or evict
                       the room from another lesson when only the room
                       conflicts)
        'cancel'     - 400 with no change
        'optimize'   - same as 'unassign' for now; the UI is expected
                       to follow up by launching the optimizer on the
                       freed slot. We do not auto-launch here.
    """
    day: int | None = None
    hour: int | None = None
    classroom_name: str | None = None  # None = leave as-is; '' = clear
    on_conflict: str = "dry_run"


def _conflict_lessons(db, active_id: int, target: models.Lesson,
                      new_day: int, new_hour: int,
                      new_room: str | None) -> dict:
    """Look for HARD conflicts at the destination (day, hour).
    Returns dict with sets of conflict lessons."""
    teacher_busy: list[models.Lesson] = []
    class_busy: list[models.Lesson] = []
    room_busy: list[models.Lesson] = []
    rows = db.query(models.Lesson).filter(
        models.Lesson.solution_id == active_id,
        models.Lesson.day == new_day,
        models.Lesson.hour == new_hour,
        models.Lesson.id != target.id,
    ).all()
    for r in rows:
        if r.teacher_name == target.teacher_name:
            teacher_busy.append(r)
        if r.class_name == target.class_name:
            class_busy.append(r)
        if (new_room and r.classroom_name == new_room
                and (new_room or "") != ""):
            room_busy.append(r)
    return {
        "teacher_busy": teacher_busy,
        "class_busy": class_busy,
        "room_busy": room_busy,
    }


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

    cinfo = _conflict_lessons(db, active.id, target, new_day, new_hour,
                              new_room)
    has_conflict = (cinfo["teacher_busy"] or cinfo["class_busy"]
                    or cinfo["room_busy"])

    def _summarise(rows: list[models.Lesson]) -> list[dict]:
        return [{"lesson_id": r.id, "teacher_name": r.teacher_name,
                 "class_name": r.class_name, "subject": r.subject,
                 "day": r.day, "hour": r.hour,
                 "classroom_name": r.classroom_name}
                for r in rows]

    conflict_payload = {
        "teacher_busy": _summarise(cinfo["teacher_busy"]),
        "class_busy": _summarise(cinfo["class_busy"]),
        "room_busy": _summarise(cinfo["room_busy"]),
    }

    if has_conflict and payload.on_conflict == "dry_run":
        return {"ok": False, "conflict": True, "details": conflict_payload}

    if has_conflict and payload.on_conflict == "cancel":
        return {"ok": False, "cancelled": True, "details": conflict_payload}

    if has_conflict and payload.on_conflict in ("unassign", "optimize"):
        # Same teacher/class busy: those lessons CANNOT coexist with the
        # target on the same slot. We delete them (they become
        # un-scheduled, surfacing as missing_hours in /monitor).
        for r in cinfo["teacher_busy"]:
            db.delete(r)
        for r in cinfo["class_busy"]:
            # Avoid double-delete (some lessons may be in both sets)
            if r in cinfo["teacher_busy"]:
                continue
            db.delete(r)
        # Room conflict: only clear the room of the conflicting lesson;
        # don't delete the lesson, just free its classroom.
        for r in cinfo["room_busy"]:
            if r in cinfo["teacher_busy"] or r in cinfo["class_busy"]:
                continue
            r.classroom_name = None
        db.flush()

    # Apply the move
    target.day = new_day
    target.hour = new_hour
    if payload.classroom_name is not None:
        target.classroom_name = (payload.classroom_name or None)
    db.commit()

    return {
        "ok": True,
        "conflict": bool(has_conflict),
        "resolution": payload.on_conflict if has_conflict else None,
        "details": conflict_payload,
        "moved_to": {"day": new_day, "hour": new_hour,
                     "classroom_name": target.classroom_name},
    }


@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    rows = _build_events(db)
    n = len(rows)
    n_incomplete = sum(1 for r in rows if not r["is_complete"])
    return {
        "n_events": n,
        "n_incomplete": n_incomplete,
        "n_missing_hours": sum(1 for r in rows if r["missing_hours"]),
        "n_missing_room": sum(1 for r in rows if r["missing_room"]),
        "n_missing_group": sum(1 for r in rows if r["missing_group"]),
    }


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
            "level": "hard" if ct.required else "soft",
            "weight": int(ct.weight or 0),
            "detail": (f"{ct.subject}: {ct.n_teachers} docenti"
                       + (f" ({ct.teacher_csv})" if ct.teacher_csv else "")),
            "extra": ct.subject,
            "editable": False,
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
            "level": sp.state,
            "weight": int(sp.weight or 0),
            "detail": room.name,
            "extra": sp.subject,
            "editable": False,
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
            "level": tp.state,
            "weight": int(tp.weight or 0),
            "detail": room.name,
            "extra": "",
            "editable": False,
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


from pydantic import BaseModel, Field


class ConstraintPatchIn(BaseModel):
    """Subset of writable fields. Only the fields relevant to the
    constraint kind are honoured."""
    level: str | None = None        # hard|soft|preferred|enforced|allowed|forbidden
    weight: int | None = None
    expression: str | None = None
    reason: str | None = None


@router.put("/constraints/{kind}/{cid}")
def update_constraint(kind: str, cid: int,
                      payload: ConstraintPatchIn,
                      db: Session = Depends(get_db)):
    if kind in ("teacher_cell", "class_cell", "room_cell"):
        Model = {"teacher_cell": models.TeacherUnavailability,
                 "class_cell":   models.ClassUnavailability,
                 "room_cell":    models.ClassroomUnavailability}[kind]
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
        db.commit()
        return {"ok": True}

    raise HTTPException(400, f"kind sconosciuto: {kind}")
