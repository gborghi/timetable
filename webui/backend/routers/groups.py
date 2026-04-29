"""CRUD for study groups (gruppi articolati / classi frazionate, type C
semantics: members can come from any combination of classes).

A group has:
  * members: a list of Student rows (cross-class membership allowed)
  * subject_hours: weekly hours the group meets per subject

The solver treats a group as a virtual class scheduled in parallel with
home classes; constraints across overlapping memberships are enforced
during the scheduling phase (TODO: solver-side wiring; the data model is
already in place)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..db import get_db
from ..utils.list_query import filter_and_sort, QueryError

router = APIRouter(prefix="/api/groups", tags=["groups"])


def _to_out(g: models.StudyGroup, db: Session) -> schemas.StudyGroupOut:
    student_ids = [m.student_id for m in g.members]
    classes = set()
    if student_ids:
        rows = db.query(models.Student.class_id).filter(
            models.Student.id.in_(student_ids)
        ).all()
        for (cid,) in rows:
            if cid is not None:
                classes.add(cid)
    return schemas.StudyGroupOut(
        id=g.id, name=g.name, kind=g.kind,
        description=g.description, notes=g.notes,
        student_ids=student_ids,
        subject_hours=[
            schemas.GroupSubjectHoursIn(
                subject=h.subject, hours_per_week=h.hours_per_week
            ) for h in sorted(g.subject_hours, key=lambda x: x.subject)
        ],
        n_students=len(student_ids),
        n_classes_touched=len(classes),
    )


@router.get("")
def list_groups(q: str | None = Query(None),
                sort: str | None = Query(None),
                db: Session = Depends(get_db)):
    rows = db.query(models.StudyGroup).order_by(models.StudyGroup.name).all()
    out = [_to_out(g, db).model_dump() for g in rows]
    try:
        return filter_and_sort(out, "groups", q, sort)
    except QueryError as e:
        raise HTTPException(400, f"Errore query: {e}")


@router.get("/{gid}", response_model=schemas.StudyGroupOut)
def get_group(gid: int, db: Session = Depends(get_db)):
    g = db.get(models.StudyGroup, gid)
    if g is None:
        raise HTTPException(404, "gruppo non trovato")
    return _to_out(g, db)


def _apply(g: models.StudyGroup, p: schemas.StudyGroupIn,
           db: Session) -> None:
    g.name = p.name
    g.kind = p.kind
    g.description = p.description
    g.notes = p.notes
    if g.id is not None:
        db.query(models.GroupMembership).filter(
            models.GroupMembership.group_id == g.id
        ).delete()
        db.query(models.GroupSubjectHours).filter(
            models.GroupSubjectHours.group_id == g.id
        ).delete()
        db.flush()
    seen_students: set[int] = set()
    for sid in p.student_ids:
        if sid in seen_students:
            continue
        seen_students.add(sid)
        if db.get(models.Student, sid) is None:
            raise HTTPException(400, f"student_id {sid} inesistente")
        db.add(models.GroupMembership(group_id=g.id, student_id=int(sid)))
    seen_subj: set[str] = set()
    for sh in p.subject_hours:
        if sh.subject in seen_subj:
            continue
        seen_subj.add(sh.subject)
        db.add(models.GroupSubjectHours(
            group_id=g.id, subject=sh.subject,
            hours_per_week=int(sh.hours_per_week)
        ))


@router.post("", response_model=schemas.StudyGroupOut)
def create_group(payload: schemas.StudyGroupIn,
                 db: Session = Depends(get_db)):
    if db.query(models.StudyGroup).filter(
        models.StudyGroup.name == payload.name
    ).first():
        raise HTTPException(400, "gruppo con questo nome gia esistente")
    g = models.StudyGroup(name=payload.name, kind=payload.kind)
    db.add(g)
    db.flush()
    _apply(g, payload, db)
    db.commit()
    db.refresh(g)
    return _to_out(g, db)


@router.put("/{gid}", response_model=schemas.StudyGroupOut)
def update_group(gid: int, payload: schemas.StudyGroupIn,
                 db: Session = Depends(get_db)):
    g = db.get(models.StudyGroup, gid)
    if g is None:
        raise HTTPException(404, "gruppo non trovato")
    other = db.query(models.StudyGroup).filter(
        models.StudyGroup.name == payload.name,
        models.StudyGroup.id != gid
    ).first()
    if other:
        raise HTTPException(400, "nome gia in uso da un altro gruppo")
    _apply(g, payload, db)
    db.commit()
    db.refresh(g)
    return _to_out(g, db)


@router.delete("/{gid}")
def delete_group(gid: int, db: Session = Depends(get_db)):
    g = db.get(models.StudyGroup, gid)
    if g is None:
        raise HTTPException(404, "gruppo non trovato")
    db.delete(g)
    db.commit()
    return {"ok": True}
