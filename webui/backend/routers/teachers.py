"""CRUD endpoints for teachers."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..db import get_db
from ..utils.list_query import filter_and_sort, parse_query, QueryError

router = APIRouter(prefix="/api/teachers", tags=["teachers"])


DAY_TO_INT = {
    "Monday": 1, "Tuesday": 2, "Wednesday": 3,
    "Thursday": 4, "Friday": 5, "Saturday": 6,
    "Lunedi": 1, "Martedi": 2, "Mercoledi": 3,
    "Giovedi": 4, "Venerdi": 5, "Sabato": 6,
}
HOURS_FULL = list(range(8, 14))


def _autofill_free_day_cells(t: models.Teacher,
                             persisted: list[models.TeacherUnavailability]
                             ) -> list[schemas.UnavailabilitySlot]:
    """Ensure that all 6 cells of the teacher's free_day are surfaced as
    HARD red, even if not yet persisted in DB. Persisted cells take
    precedence (so the user can over-ride a single hour as 'soft' if
    needed)."""
    persisted_by_dh = {(p.day, p.hour): p for p in persisted}
    out = [
        schemas.UnavailabilitySlot(
            day=p.day, hour=p.hour, state=p.state,
            soft_penalty=p.soft_penalty, reason=p.reason
        )
        for p in persisted
    ]
    fd = DAY_TO_INT.get(t.free_day or "")
    if fd is None:
        return out
    for h in HOURS_FULL:
        if (fd, h) not in persisted_by_dh:
            out.append(schemas.UnavailabilitySlot(
                day=fd, hour=h, state="hard",
                soft_penalty=0, reason="giorno libero (auto)"
            ))
    return out


def _classroom_prefs_for_teacher(db, teacher_id: int
                                 ) -> list[schemas.TeacherClassroomPrefIn]:
    rooms = {r.id: r for r in db.query(models.Classroom).all()}
    rows = db.query(models.TeacherClassroomPreference).filter(
        models.TeacherClassroomPreference.teacher_id == teacher_id
    ).all()
    out = []
    for r in rows:
        room = rooms.get(r.classroom_id)
        if room is None:
            continue
        out.append(schemas.TeacherClassroomPrefIn(
            classroom_name=room.name,
            state=r.state or "allowed",
            weight=float(r.weight or 0.0),
        ))
    return out


def _apply_teacher_classroom_prefs(db, teacher_id: int,
                                   prefs) -> None:
    db.query(models.TeacherClassroomPreference).filter(
        models.TeacherClassroomPreference.teacher_id == teacher_id
    ).delete()
    rooms_by_name = {r.name: r for r in db.query(models.Classroom).all()}
    seen = set()
    for p in (prefs or []):
        if p.classroom_name in seen:
            continue
        seen.add(p.classroom_name)
        room = rooms_by_name.get(p.classroom_name)
        if room is None:
            continue
        st = p.state if p.state in (
            "allowed", "soft", "preferred", "forbidden", "enforced"
        ) else "allowed"
        db.add(models.TeacherClassroomPreference(
            teacher_id=teacher_id,
            classroom_id=room.id,
            state=st,
            weight=float(p.weight or 0.0),
        ))


def _to_out(t: models.Teacher, db=None) -> schemas.TeacherOut:
    return schemas.TeacherOut(
        id=t.id,
        name=t.name,
        last_name=t.last_name,
        first_name=t.first_name,
        nickname=t.nickname,
        matricola=t.matricola,
        group=t.group,
        max_hours=t.max_hours,
        completion_hours=t.completion_hours,
        exemption_hours=t.exemption_hours,
        free_day=t.free_day,
        max_consecutive=t.max_consecutive,
        notes=t.notes,
        pref_no_buchi_weight=t.pref_no_buchi_weight,
        pref_no_five_weight=t.pref_no_five_weight,
        pref_no_one_weight=t.pref_no_one_weight,
        preferred_days_csv=t.preferred_days_csv,
        subjects=[s.subject for s in t.subjects],
        unavailability=_autofill_free_day_cells(t, list(t.unavailability)),
        mandatory_free_days=[m.day for m in t.mandatory_free_days],
        compatible_classes=[c.class_name for c in t.compatible_classes],
        classroom_prefs=(_classroom_prefs_for_teacher(db, t.id)
                         if db is not None else []),
    )


@router.get("")
def list_teachers(q: str | None = Query(None,
                    description="Optional DSL filter, e.g. 'group=A026 AND max_hours>=18'"),
                  sort: str | None = Query(None,
                    description="Comma/colon sort, e.g. 'group:name,asc:max_hours,desc'"),
                  db: Session = Depends(get_db)):
    rows = db.query(models.Teacher).order_by(models.Teacher.name).all()
    # Compute extra denormalized fields for the DSL
    n_classes_by_t: dict[int, int] = {}
    sched_by_t: dict[str, int] = {}
    for a in db.query(models.Assignment).all():
        n_classes_by_t[a.teacher_id] = n_classes_by_t.get(a.teacher_id, 0) + 1
    active_sol = db.query(models.Solution).filter(
        models.Solution.is_active == True  # noqa: E712
    ).first()
    if active_sol is not None:
        for l in db.query(models.Lesson).filter(
            models.Lesson.solution_id == active_sol.id
        ).all():
            sched_by_t[l.teacher_name] = sched_by_t.get(l.teacher_name, 0) + 1
    out = []
    for t in rows:
        d = _to_out(t, db).model_dump()
        d["n_classes"] = n_classes_by_t.get(t.id, 0)
        d["scheduled_hours"] = sched_by_t.get(t.name, 0)
        d["soft_penalty_total"] = sum(
            int(c.get("soft_penalty") or 0)
            for c in d.get("unavailability", [])
            if c.get("state") == "soft"
        )
        out.append(d)
    try:
        return filter_and_sort(out, "teachers", q, sort)
    except QueryError as e:
        raise HTTPException(400, f"Errore query: {e}")


@router.get("/{teacher_id}", response_model=schemas.TeacherOut)
def get_teacher(teacher_id: int, db: Session = Depends(get_db)):
    t = db.get(models.Teacher, teacher_id)
    if t is None:
        raise HTTPException(404, "teacher not found")
    return _to_out(t, db)


def _apply_payload(t: models.Teacher, p: schemas.TeacherIn,
                   db: Session) -> None:
    t.name = p.name
    t.last_name = p.last_name
    t.first_name = p.first_name
    t.nickname = p.nickname
    t.matricola = p.matricola
    t.group = p.group
    t.max_hours = p.max_hours
    t.completion_hours = p.completion_hours
    t.exemption_hours = p.exemption_hours
    t.free_day = p.free_day
    t.max_consecutive = p.max_consecutive
    t.notes = p.notes
    t.pref_no_buchi_weight = p.pref_no_buchi_weight
    t.pref_no_five_weight = p.pref_no_five_weight
    t.pref_no_one_weight = p.pref_no_one_weight
    t.preferred_days_csv = p.preferred_days_csv
    # Replace subject set
    if t.id is not None:
        db.query(models.TeacherSubject).filter(
            models.TeacherSubject.teacher_id == t.id
        ).delete()
        db.query(models.TeacherUnavailability).filter(
            models.TeacherUnavailability.teacher_id == t.id
        ).delete()
        db.query(models.TeacherMandatoryFreeDay).filter(
            models.TeacherMandatoryFreeDay.teacher_id == t.id
        ).delete()
        db.query(models.TeacherCompatibleClass).filter(
            models.TeacherCompatibleClass.teacher_id == t.id
        ).delete()
        db.flush()
    for s in dict.fromkeys(p.subjects):
        db.add(models.TeacherSubject(teacher_id=t.id, subject=s))
    for u in p.unavailability:
        db.add(models.TeacherUnavailability(
            teacher_id=t.id, day=int(u.day), hour=int(u.hour),
            state=u.state if u.state in ("hard", "soft", "preferred", "enforced") else "hard",
            soft_penalty=int(u.soft_penalty or 100),
            reason=u.reason
        ))
    for d in dict.fromkeys(p.mandatory_free_days):
        db.add(models.TeacherMandatoryFreeDay(teacher_id=t.id, day=d))
    for cn in dict.fromkeys(p.compatible_classes):
        db.add(models.TeacherCompatibleClass(
            teacher_id=t.id, class_name=cn
        ))
    _apply_teacher_classroom_prefs(db, t.id, p.classroom_prefs)


@router.post("", response_model=schemas.TeacherOut)
def create_teacher(payload: schemas.TeacherIn,
                   db: Session = Depends(get_db)):
    if db.query(models.Teacher).filter(
        models.Teacher.name == payload.name
    ).first():
        raise HTTPException(400, "teacher with this name already exists")
    t = models.Teacher(name=payload.name)
    db.add(t)
    db.flush()
    _apply_payload(t, payload, db)
    db.commit()
    db.refresh(t)
    return _to_out(t, db)


@router.put("/{teacher_id}", response_model=schemas.TeacherOut)
def update_teacher(teacher_id: int, payload: schemas.TeacherIn,
                   db: Session = Depends(get_db)):
    t = db.get(models.Teacher, teacher_id)
    if t is None:
        raise HTTPException(404, "teacher not found")
    _apply_payload(t, payload, db)
    db.commit()
    db.refresh(t)
    return _to_out(t, db)


@router.delete("/{teacher_id}")
def delete_teacher(teacher_id: int, db: Session = Depends(get_db)):
    t = db.get(models.Teacher, teacher_id)
    if t is None:
        raise HTTPException(404, "teacher not found")
    db.delete(t)
    db.commit()
    return {"ok": True}
