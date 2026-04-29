"""CRUD for subjects (with associated SOFT preferences) and the subject
group weights."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..db import get_db
from ..utils.list_query import filter_and_sort, QueryError

router = APIRouter(prefix="/api/subjects", tags=["subjects"])


def _to_out(s: models.Subject) -> schemas.SubjectOut:
    return schemas.SubjectOut.model_validate(s)


@router.get("")
def list_subjects(q: str | None = Query(None),
                  sort: str | None = Query(None),
                  db: Session = Depends(get_db)):
    rows = db.query(models.Subject).order_by(models.Subject.name).all()
    out = [_to_out(s).model_dump() for s in rows]
    try:
        return filter_and_sort(out, "subjects", q, sort)
    except QueryError as e:
        raise HTTPException(400, f"Errore query: {e}")


@router.post("", response_model=schemas.SubjectOut)
def create_subject(payload: schemas.SubjectIn,
                   db: Session = Depends(get_db)):
    if db.query(models.Subject).filter(
        models.Subject.name == payload.name
    ).first():
        raise HTTPException(400, "subject already exists")
    s = models.Subject(**payload.model_dump())
    db.add(s)
    db.commit()
    db.refresh(s)
    return _to_out(s)


@router.put("/{subject_id}", response_model=schemas.SubjectOut)
def update_subject(subject_id: int, payload: schemas.SubjectIn,
                   db: Session = Depends(get_db)):
    s = db.get(models.Subject, subject_id)
    if s is None:
        raise HTTPException(404, "subject not found")
    for k, v in payload.model_dump().items():
        setattr(s, k, v)
    db.commit()
    db.refresh(s)
    return _to_out(s)


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
