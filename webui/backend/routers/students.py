"""CRUD for students. A student optionally belongs to a single home class;
membership in StudyGroup is handled via the /api/groups endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..db import get_db
from ..utils.list_query import filter_and_sort, QueryError

router = APIRouter(prefix="/api/students", tags=["students"])


def _to_out(s: models.Student, db: Session) -> schemas.StudentOut:
    cls_name = None
    if s.class_id is not None:
        cls = db.get(models.SchoolClass, s.class_id)
        if cls is not None:
            cls_name = cls.name
    n_groups = db.query(models.GroupMembership).filter(
        models.GroupMembership.student_id == s.id
    ).count()
    return schemas.StudentOut(
        id=s.id, last_name=s.last_name, first_name=s.first_name,
        birth_date=s.birth_date, gender=s.gender, email=s.email,
        student_code=s.student_code, class_id=s.class_id, notes=s.notes,
        class_name=cls_name, n_groups=n_groups,
    )


@router.get("")
def list_students(q: str | None = Query(None),
                  sort: str | None = Query(None),
                  class_id: int | None = Query(None),
                  db: Session = Depends(get_db)):
    qry = db.query(models.Student)
    if class_id is not None:
        qry = qry.filter(models.Student.class_id == class_id)
    rows = qry.order_by(models.Student.last_name,
                        models.Student.first_name).all()
    out = [_to_out(s, db).model_dump() for s in rows]
    try:
        return filter_and_sort(out, "students", q, sort)
    except QueryError as e:
        raise HTTPException(400, f"Errore query: {e}")


@router.get("/{sid}", response_model=schemas.StudentOut)
def get_student(sid: int, db: Session = Depends(get_db)):
    s = db.get(models.Student, sid)
    if s is None:
        raise HTTPException(404, "studente non trovato")
    return _to_out(s, db)


def _validate_class(db: Session, class_id: int | None) -> None:
    if class_id is None:
        return
    if db.get(models.SchoolClass, class_id) is None:
        raise HTTPException(400, f"class_id {class_id} inesistente")


def _apply(s: models.Student, p: schemas.StudentIn, db: Session) -> None:
    _validate_class(db, p.class_id)
    s.last_name = p.last_name
    s.first_name = p.first_name
    s.birth_date = p.birth_date
    s.gender = p.gender
    s.email = p.email
    s.student_code = p.student_code
    s.class_id = p.class_id
    s.notes = p.notes


@router.post("", response_model=schemas.StudentOut)
def create_student(payload: schemas.StudentIn,
                   db: Session = Depends(get_db)):
    s = models.Student(last_name=payload.last_name,
                       first_name=payload.first_name)
    db.add(s)
    db.flush()
    _apply(s, payload, db)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(400, f"errore creazione studente: {e}")
    db.refresh(s)
    return _to_out(s, db)


@router.put("/{sid}", response_model=schemas.StudentOut)
def update_student(sid: int, payload: schemas.StudentIn,
                   db: Session = Depends(get_db)):
    s = db.get(models.Student, sid)
    if s is None:
        raise HTTPException(404, "studente non trovato")
    _apply(s, payload, db)
    db.commit()
    db.refresh(s)
    return _to_out(s, db)


@router.delete("/{sid}")
def delete_student(sid: int, db: Session = Depends(get_db)):
    s = db.get(models.Student, sid)
    if s is None:
        raise HTTPException(404, "studente non trovato")
    db.delete(s)
    db.commit()
    return {"ok": True}
