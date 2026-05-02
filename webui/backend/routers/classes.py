"""CRUD for school classes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..db import get_db
from ..utils.list_query import filter_and_sort, QueryError
from ..utils.pagination import paginated_or_list

router = APIRouter(prefix="/api/classes", tags=["classes"])


def _class_unavailability(db, class_id: int) -> list[schemas.UnavailabilitySlot]:
    rows = db.query(models.ClassUnavailability).filter(
        models.ClassUnavailability.class_id == class_id
    ).all()
    return [
        schemas.UnavailabilitySlot(
            day=u.day, hour=u.hour, state=u.state,
            soft_penalty=u.soft_penalty, reason=u.reason
        ) for u in rows
    ]


def _to_out(c: models.SchoolClass, db=None) -> schemas.ClassOut:
    unav = _class_unavailability(db, c.id) if db is not None else []
    # Decode preferred_free_days_json (best-effort).
    import json as _json
    pfd_list: list[schemas.FreeDayPref] = []
    raw = getattr(c, "preferred_free_days_json", None) or ""
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
    return schemas.ClassOut(
        id=c.id,
        name=c.name,
        nickname=c.nickname,
        year=c.year,
        section=c.section,
        curriculum=c.curriculum,
        curriculum_id=c.curriculum_id,
        n_students=c.n_students,
        notes=c.notes,
        hard_entry_at_8=c.hard_entry_at_8,
        hard_exit_after_12=c.hard_exit_after_12,
        hard_no_holes=c.hard_no_holes,
        hard_dual_math=c.hard_dual_math,
        hard_dual_italian=c.hard_dual_italian,
        hard_motorie_pairs=c.hard_motorie_pairs,
        hard_max_6_per_day=c.hard_max_6_per_day,
        soft_minimize_sixth_weight=c.soft_minimize_sixth_weight,
        preferred_free_days=pfd_list,
        required_free_days_count=int(
            getattr(c, "required_free_days_count", 0) or 0
        ),
        max_hours_per_day=int(
            getattr(c, "max_hours_per_day", 5) or 5
        ),
        subjects=[
            schemas.ClassSubjectIn(subject=s.subject,
                                   hours_per_week=s.hours_per_week)
            for s in c.subjects
        ],
        unavailability=unav,
    )


@router.get("")
def list_classes(q: str | None = Query(None),
                 sort: str | None = Query(None),
                 format: str | None = Query(None),
                 db: Session = Depends(get_db)):
    rows = db.query(models.SchoolClass).order_by(
        models.SchoolClass.name
    ).all()
    out = [_to_out(c, db).model_dump() for c in rows]
    try:
        filtered = filter_and_sort(out, "classes", q, sort)
    except QueryError as e:
        raise HTTPException(400, f"Errore query: {e}")
    return paginated_or_list(filtered, None, None,
                              fmt=format, entity="classes")


@router.get("/{class_id}", response_model=schemas.ClassOut)
def get_class(class_id: int, db: Session = Depends(get_db)):
    c = db.get(models.SchoolClass, class_id)
    if c is None:
        raise HTTPException(404, "class not found")
    return _to_out(c, db)


def _apply(c: models.SchoolClass, p: schemas.ClassIn, db: Session) -> None:
    c.name = p.name
    c.nickname = p.nickname
    c.year = p.year
    c.section = p.section
    c.curriculum = p.curriculum
    if p.curriculum_id is not None:
        cur = db.get(models.Curriculum, p.curriculum_id)
        if cur is None:
            raise HTTPException(400, f"curriculum_id {p.curriculum_id} inesistente")
        c.curriculum_id = p.curriculum_id
        if not c.curriculum:
            c.curriculum = cur.code
    else:
        c.curriculum_id = None
    c.n_students = p.n_students
    c.notes = p.notes
    c.hard_entry_at_8 = p.hard_entry_at_8
    c.hard_exit_after_12 = p.hard_exit_after_12
    c.hard_no_holes = p.hard_no_holes
    c.hard_dual_math = p.hard_dual_math
    c.hard_dual_italian = p.hard_dual_italian
    c.hard_motorie_pairs = p.hard_motorie_pairs
    c.hard_max_6_per_day = p.hard_max_6_per_day
    c.soft_minimize_sixth_weight = p.soft_minimize_sixth_weight
    # Free-day fields
    import json as _json
    pfd: list[dict] = []
    seen_days: set[int] = set()
    for it in (getattr(p, "preferred_free_days", None) or [])[:3]:
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
    c.preferred_free_days_json = _json.dumps(pfd) if pfd else None
    rc = int(getattr(p, "required_free_days_count", 0) or 0)
    c.required_free_days_count = max(0, min(6, rc))
    mh = int(getattr(p, "max_hours_per_day", 5) or 5)
    c.max_hours_per_day = max(1, min(7, mh))
    if c.id is not None:
        db.query(models.ClassSubject).filter(
            models.ClassSubject.class_id == c.id
        ).delete()
        db.query(models.ClassUnavailability).filter(
            models.ClassUnavailability.class_id == c.id
        ).delete()
        db.flush()
    for s in p.subjects:
        db.add(models.ClassSubject(
            class_id=c.id, subject=s.subject,
            hours_per_week=int(s.hours_per_week),
        ))
    for u in p.unavailability:
        db.add(models.ClassUnavailability(
            class_id=c.id, day=int(u.day), hour=int(u.hour),
            state=u.state if u.state in ("hard", "soft", "preferred", "enforced") else "hard",
            soft_penalty=int(u.soft_penalty or 100),
            reason=u.reason,
        ))


@router.post("", response_model=schemas.ClassOut)
def create_class(payload: schemas.ClassIn, db: Session = Depends(get_db)):
    if db.query(models.SchoolClass).filter(
        models.SchoolClass.name == payload.name
    ).first():
        raise HTTPException(400, "class with this name already exists")
    c = models.SchoolClass(name=payload.name)
    db.add(c)
    db.flush()
    _apply(c, payload, db)
    db.commit()
    db.refresh(c)
    return _to_out(c, db)


@router.put("/{class_id}", response_model=schemas.ClassOut)
def update_class(class_id: int, payload: schemas.ClassIn,
                 db: Session = Depends(get_db)):
    c = db.get(models.SchoolClass, class_id)
    if c is None:
        raise HTTPException(404, "class not found")
    _apply(c, payload, db)
    db.commit()
    db.refresh(c)
    return _to_out(c, db)


@router.delete("/{class_id}")
def delete_class(class_id: int, db: Session = Depends(get_db)):
    c = db.get(models.SchoolClass, class_id)
    if c is None:
        raise HTTPException(404, "class not found")
    db.delete(c)
    db.commit()
    return {"ok": True}
