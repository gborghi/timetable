"""CRUD endpoints for teachers."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..db import get_db
from ..utils.list_query import filter_and_sort, parse_query, QueryError
from ..utils.pagination import paginated_or_list

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
    """Ensure that all 6 cells of the teacher's free_day(s) are surfaced
    as HARD/SOFT red/amber, even if not yet persisted in DB. Persisted
    cells take precedence so the user can override a single hour.

    Sources for auto-fill (all merged):
      - legacy `free_day: str` (HARD)
      - new `preferred_free_days_json` entries:
          - is_hard=True   -> 6 HARD cells
          - is_hard=False  -> 6 SOFT cells with `soft_penalty`
    """
    persisted_by_dh = {(p.day, p.hour): p for p in persisted}
    out = [
        schemas.UnavailabilitySlot(
            day=p.day, hour=p.hour, state=p.state,
            soft_penalty=p.soft_penalty, reason=p.reason
        )
        for p in persisted
    ]
    autofilled: set[tuple[int, int]] = set()
    fd = DAY_TO_INT.get(t.free_day or "")
    if fd is not None:
        for h in HOURS_FULL:
            if (fd, h) not in persisted_by_dh and (fd, h) not in autofilled:
                out.append(schemas.UnavailabilitySlot(
                    day=fd, hour=h, state="hard",
                    soft_penalty=0,
                    reason="giorno libero (auto, free_day legacy)"
                ))
                autofilled.add((fd, h))
    # New: preferred_free_days_json
    raw = getattr(t, "preferred_free_days_json", None) or ""
    if raw:
        try:
            import json as _json
            arr = _json.loads(raw)
            if isinstance(arr, list):
                for idx, it in enumerate(arr[:3]):
                    if not isinstance(it, dict):
                        continue
                    d = int(it.get("day", 0))
                    if d < 1 or d > 6:
                        continue
                    is_hard = bool(it.get("is_hard", True))
                    pen = it.get("soft_penalty")
                    state = "hard" if is_hard else "soft"
                    label = ["1a", "2a", "3a"][idx] if idx < 3 else f"{idx+1}a"
                    for h in HOURS_FULL:
                        if (d, h) in persisted_by_dh:
                            continue
                        if (d, h) in autofilled:
                            continue
                        out.append(schemas.UnavailabilitySlot(
                            day=d, hour=h, state=state,
                            soft_penalty=int(pen) if pen is not None else 0,
                            reason=f"giorno libero {label} preferenza (auto)",
                        ))
                        autofilled.add((d, h))
        except Exception:
            pass
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
    # Decode preferred_free_days_json (defensive — best-effort).
    import json as _json
    pfd_list: list[schemas.FreeDayPref] = []
    raw = getattr(t, "preferred_free_days_json", None) or ""
    if raw:
        try:
            arr = _json.loads(raw)
            if isinstance(arr, list):
                for it in arr[:3]:
                    if isinstance(it, dict) and "day" in it:
                        pfd_list.append(schemas.FreeDayPref(
                            day=int(it["day"]),
                            is_hard=bool(it.get("is_hard", True)),
                            soft_penalty=(int(it["soft_penalty"])
                                          if it.get("soft_penalty") is not None
                                          else None),
                        ))
        except Exception:
            pass
    fdp_rows = sorted(
        (getattr(t, "free_day_preferences", None) or []),
        key=lambda r: int(r.priority))
    free_day_priorities = [
        schemas.FreeDayPriorityPref(
            day=int(r.day), priority=int(r.priority))
        for r in fdp_rows
    ]
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
        graduatoria_score=t.graduatoria_score,
        free_day=t.free_day,
        preferred_free_days=pfd_list,
        min_free_days=int(
            getattr(t, "min_free_days", 1) or 1
        ),
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
        free_day_priorities=free_day_priorities,
    )


@router.get("")
def list_teachers(q: str | None = Query(None,
                    description="Optional DSL filter, e.g. 'group=A026 AND max_hours>=18'"),
                  sort: str | None = Query(None,
                    description="Comma/colon sort, e.g. 'group:name,asc:max_hours,desc'"),
                  format: str | None = Query(None,
                    description="If set to 'xlsx' or 'csv', returns the "
                                "filtered+sorted list as a binary file."),
                  limit: int | None = Query(None, ge=0, le=10000),
                  offset: int | None = Query(None, ge=0),
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
        filtered = filter_and_sort(out, "teachers", q, sort)
    except QueryError as e:
        raise HTTPException(400, f"Errore query: {e}")
    return paginated_or_list(filtered, limit, offset,
                              fmt=format, entity="teachers")


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
    t.graduatoria_score = p.graduatoria_score
    t.free_day = p.free_day
    t.max_consecutive = p.max_consecutive
    t.notes = p.notes
    t.pref_no_buchi_weight = p.pref_no_buchi_weight
    t.pref_no_five_weight = p.pref_no_five_weight
    t.pref_no_one_weight = p.pref_no_one_weight
    t.preferred_days_csv = p.preferred_days_csv
    # Preferred-free-day list (up to 3) is JSON-encoded.
    import json as _json
    pfd = []
    seen_days: set[int] = set()
    for it in (p.preferred_free_days or [])[:3]:
        d = int(it.day)
        if d in seen_days or d < 1 or d > 6:
            continue
        seen_days.add(d)
        pfd.append({
            "day": d,
            "is_hard": bool(it.is_hard),
            "soft_penalty": (int(it.soft_penalty)
                              if it.soft_penalty is not None else None),
        })
    t.preferred_free_days_json = _json.dumps(pfd) if pfd else None
    # Min free days per week (HARD floor). Default 1, range 0..6.
    rc = int(p.min_free_days if p.min_free_days is not None
             else 1)
    rc = max(0, min(6, rc))
    t.min_free_days = rc
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


# ====================================================================
# Phase-A only: class preferences + curriculum preferences
# (5-state per (teacher, class) and per (teacher, curriculum))
# ====================================================================


def _ensure_teacher(db: Session, tid: int) -> models.Teacher:
    t = db.get(models.Teacher, tid)
    if t is None:
        raise HTTPException(404, "teacher not found")
    return t


@router.get(
    "/{teacher_id}/class-preferences",
    response_model=list[schemas.TeacherClassPrefOut],
)
def list_class_prefs(teacher_id: int, db: Session = Depends(get_db)):
    _ensure_teacher(db, teacher_id)
    rows = db.query(models.TeacherClassPreference).filter(
        models.TeacherClassPreference.teacher_id == teacher_id
    ).all()
    return rows


@router.put(
    "/{teacher_id}/class-preferences",
    response_model=list[schemas.TeacherClassPrefOut],
)
def replace_class_prefs(
    teacher_id: int,
    payload: list[schemas.TeacherClassPrefIn],
    db: Session = Depends(get_db),
):
    """Replace the full set of preferences for this teacher.
    'allowed' rows with soft_penalty=0 are dropped (default state)."""
    _ensure_teacher(db, teacher_id)
    db.query(models.TeacherClassPreference).filter(
        models.TeacherClassPreference.teacher_id == teacher_id
    ).delete()
    out = []
    for p in payload:
        if p.state == "allowed" and p.soft_penalty == 0.0:
            continue
        row = models.TeacherClassPreference(
            teacher_id=teacher_id,
            class_name=p.class_name,
            state=p.state,
            soft_penalty=p.soft_penalty,
        )
        db.add(row)
        out.append(row)
    db.commit()
    for r in out:
        db.refresh(r)
    return out


@router.get(
    "/{teacher_id}/curriculum-preferences",
    response_model=list[schemas.TeacherCurriculumPrefOut],
)
def list_curr_prefs(teacher_id: int, db: Session = Depends(get_db)):
    _ensure_teacher(db, teacher_id)
    return db.query(models.TeacherCurriculumPreference).filter(
        models.TeacherCurriculumPreference.teacher_id == teacher_id
    ).all()


@router.put(
    "/{teacher_id}/curriculum-preferences",
    response_model=list[schemas.TeacherCurriculumPrefOut],
)
def replace_curr_prefs(
    teacher_id: int,
    payload: list[schemas.TeacherCurriculumPrefIn],
    db: Session = Depends(get_db),
):
    _ensure_teacher(db, teacher_id)
    db.query(models.TeacherCurriculumPreference).filter(
        models.TeacherCurriculumPreference.teacher_id == teacher_id
    ).delete()
    out = []
    for p in payload:
        if p.state == "allowed" and p.soft_penalty == 0.0:
            continue
        row = models.TeacherCurriculumPreference(
            teacher_id=teacher_id,
            curriculum_code=p.curriculum_code,
            state=p.state,
            soft_penalty=p.soft_penalty,
        )
        db.add(row)
        out.append(row)
    db.commit()
    for r in out:
        db.refresh(r)
    return out


# ====================================================================
# 3-priority free-day preferences
# (TeacherFreeDayPreference table; weights 30/20/10 for 1st/2nd/3rd)
# ====================================================================


@router.get(
    "/{teacher_id}/free-day-preferences",
    response_model=list[schemas.FreeDayPriorityPref],
)
def list_free_day_priorities(
    teacher_id: int, db: Session = Depends(get_db)
):
    _ensure_teacher(db, teacher_id)
    rows = (db.query(models.TeacherFreeDayPreference)
              .filter(
                  models.TeacherFreeDayPreference.teacher_id == teacher_id)
              .order_by(models.TeacherFreeDayPreference.priority)
              .all())
    return [
        schemas.FreeDayPriorityPref(
            day=int(r.day), priority=int(r.priority))
        for r in rows
    ]


@router.patch(
    "/{teacher_id}/free-day-preferences",
    response_model=list[schemas.FreeDayPriorityPref],
)
def replace_free_day_priorities(
    teacher_id: int,
    payload: schemas.FreeDayPrioritiesIn,
    db: Session = Depends(get_db),
):
    """Replace the teacher's full set of priority preferences.

    Validation:
    - day must be in 1..6 (Lun..Sab)
    - priority must be in 1..3
    - no duplicate days
    - no duplicate priorities
    Empty list clears all preferences.
    """
    _ensure_teacher(db, teacher_id)
    seen_days: set[int] = set()
    seen_pri: set[int] = set()
    cleaned: list[schemas.FreeDayPriorityPref] = []
    for p in payload.preferences:
        d = int(p.day)
        pr = int(p.priority)
        if d < 1 or d > 6:
            raise HTTPException(
                400, f"day must be in 1..6 (got {d})")
        if pr < 1 or pr > 3:
            raise HTTPException(
                400, f"priority must be in 1..3 (got {pr})")
        if d in seen_days:
            raise HTTPException(
                400, f"duplicate day {d}")
        if pr in seen_pri:
            raise HTTPException(
                400, f"duplicate priority {pr}")
        seen_days.add(d)
        seen_pri.add(pr)
        cleaned.append(p)
    db.query(models.TeacherFreeDayPreference).filter(
        models.TeacherFreeDayPreference.teacher_id == teacher_id
    ).delete()
    db.flush()
    for p in cleaned:
        db.add(models.TeacherFreeDayPreference(
            teacher_id=teacher_id,
            day=int(p.day),
            priority=int(p.priority),
        ))
    db.commit()
    return list_free_day_priorities(teacher_id, db)
