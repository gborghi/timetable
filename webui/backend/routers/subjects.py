"""CRUD for subjects (with associated SOFT preferences) and the subject
group weights."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..db import get_db
from ..utils.list_query import filter_and_sort, QueryError
from ..utils.pagination import paginated_or_list

router = APIRouter(prefix="/api/subjects", tags=["subjects"])


def _classroom_prefs_for_subject(db, name: str
                                 ) -> list[schemas.SubjectClassroomPrefIn]:
    rooms = {r.id: r for r in db.query(models.Classroom).all()}
    rows = db.query(models.ClassroomSubjectPreference).filter(
        models.ClassroomSubjectPreference.subject == name
    ).all()
    out = []
    for r in rows:
        room = rooms.get(r.classroom_id)
        if room is None:
            continue
        out.append(schemas.SubjectClassroomPrefIn(
            classroom_name=room.name,
            state=r.state or "allowed",
            weight=float(r.weight or 0.0),
        ))
    return out


def _to_out(s: models.Subject, db=None) -> schemas.SubjectOut:
    base = schemas.SubjectOut.model_validate(s)
    if db is not None:
        base = base.model_copy(update={
            "classroom_prefs": _classroom_prefs_for_subject(db, s.name),
        })
    return base


@router.get("")
def list_subjects(q: str | None = Query(None),
                  sort: str | None = Query(None),
                  format: str | None = Query(None),
                  db: Session = Depends(get_db)):
    rows = db.query(models.Subject).order_by(models.Subject.name).all()
    out = [_to_out(s, db).model_dump() for s in rows]
    try:
        filtered = filter_and_sort(out, "subjects", q, sort)
    except QueryError as e:
        raise HTTPException(400, f"Errore query: {e}")
    return paginated_or_list(filtered, None, None,
                              fmt=format, entity="subjects")


def _apply_classroom_prefs(db, subject_name: str,
                           prefs: list[schemas.SubjectClassroomPrefIn]) -> None:
    db.query(models.ClassroomSubjectPreference).filter(
        models.ClassroomSubjectPreference.subject == subject_name
    ).delete()
    rooms_by_name = {r.name: r for r in db.query(models.Classroom).all()}
    seen = set()
    for p in prefs:
        if p.classroom_name in seen:
            continue
        seen.add(p.classroom_name)
        room = rooms_by_name.get(p.classroom_name)
        if room is None:
            continue
        st = p.state if p.state in (
            "allowed", "soft", "preferred", "forbidden", "enforced"
        ) else "allowed"
        db.add(models.ClassroomSubjectPreference(
            classroom_id=room.id,
            subject=subject_name,
            state=st,
            weight=float(p.weight or 0.0),
            required=(st == "enforced"),
        ))


@router.post("", response_model=schemas.SubjectOut)
def create_subject(payload: schemas.SubjectIn,
                   db: Session = Depends(get_db)):
    if db.query(models.Subject).filter(
        models.Subject.name == payload.name
    ).first():
        raise HTTPException(400, "subject already exists")
    data = payload.model_dump()
    classroom_prefs = data.pop("classroom_prefs", []) or []
    s = models.Subject(**data)
    db.add(s)
    db.flush()
    _apply_classroom_prefs(db, s.name, payload.classroom_prefs or [])
    db.commit()
    db.refresh(s)
    return _to_out(s, db)


@router.put("/{subject_id}", response_model=schemas.SubjectOut)
def update_subject(subject_id: int, payload: schemas.SubjectIn,
                   db: Session = Depends(get_db)):
    s = db.get(models.Subject, subject_id)
    if s is None:
        raise HTTPException(404, "subject not found")
    data = payload.model_dump()
    classroom_prefs = data.pop("classroom_prefs", []) or []
    for k, v in data.items():
        setattr(s, k, v)
    _apply_classroom_prefs(db, s.name, payload.classroom_prefs or [])
    db.commit()
    db.refresh(s)
    return _to_out(s, db)


@router.delete("/{subject_id}")
def delete_subject(subject_id: int, db: Session = Depends(get_db)):
    s = db.get(models.Subject, subject_id)
    if s is None:
        raise HTTPException(404, "subject not found")
    db.delete(s)
    db.commit()
    return {"ok": True}


@router.get("/group-weights", response_model=list[schemas.SubjectGroupWeightOut])
def list_group_weights(db: Session = Depends(get_db)):
    rows = db.query(models.SubjectGroupWeight).order_by(
        models.SubjectGroupWeight.subject,
        models.SubjectGroupWeight.group_name,
    ).all()
    return [
        schemas.SubjectGroupWeightOut.model_validate(r) for r in rows
    ]


@router.put("/group-weights", response_model=list[schemas.SubjectGroupWeightOut])
def replace_group_weights(payload: list[schemas.SubjectGroupWeightIn],
                           db: Session = Depends(get_db)):
    db.query(models.SubjectGroupWeight).delete()
    db.commit()
    for p in payload:
        db.add(models.SubjectGroupWeight(**p.model_dump()))
    db.commit()
    rows = db.query(models.SubjectGroupWeight).all()
    return [
        schemas.SubjectGroupWeightOut.model_validate(r) for r in rows
    ]
