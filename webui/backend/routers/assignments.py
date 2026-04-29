"""Read + manual edit of prof->class assignments."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, optimization
from ..db import get_db

router = APIRouter(prefix="/api/assignments", tags=["assignments"])


@router.get("")
def list_assignments(db: Session = Depends(get_db)):
    """Return assignments with denormalized teacher/class names."""
    teachers = {t.id: t for t in db.query(models.Teacher).all()}
    classes = {c.id: c for c in db.query(models.SchoolClass).all()}
    rows = db.query(models.Assignment).all()
    out = []
    for a in rows:
        t = teachers.get(a.teacher_id)
        c = classes.get(a.class_id)
        if t is None or c is None:
            continue
        out.append({
            "id": a.id,
            "teacher_id": a.teacher_id,
            "teacher_name": t.name,
            "class_id": a.class_id,
            "class_name": c.name,
            "subject": a.subject,
            "hours": a.hours,
            "locked": a.locked,
        })
    return out


@router.get("/by-class")
def assignments_grouped_by_class(db: Session = Depends(get_db)):
    """Group: class -> [{subject, teacher, hours, locked}, ...]."""
    teachers = {t.id: t for t in db.query(models.Teacher).all()}
    classes = {c.id: c for c in db.query(models.SchoolClass).all()}
    out: dict[str, list[dict]] = {c.name: [] for c in classes.values()}
    for a in db.query(models.Assignment).all():
        t = teachers.get(a.teacher_id)
        c = classes.get(a.class_id)
        if t is None or c is None:
            continue
        out.setdefault(c.name, []).append({
            "id": a.id,
            "subject": a.subject,
            "teacher": t.name,
            "hours": a.hours,
            "locked": a.locked,
        })
    return out


@router.put("/manual")
def manual_assignment(payload: schemas.ManualAssignmentIn,
                      db: Session = Depends(get_db)):
    ok, reason, new = optimization.manual_assignment(
        db, payload.class_name, payload.subject,
        payload.teacher_name, locked=payload.locked,
    )
    out = {"accepted": ok, "reason": reason}
    if ok and new is not None:
        teacher = db.get(models.Teacher, new.teacher_id)
        sclass = db.get(models.SchoolClass, new.class_id)
        out["new_assignment"] = {
            "id": new.id,
            "teacher_id": new.teacher_id,
            "teacher_name": teacher.name if teacher else "?",
            "class_id": new.class_id,
            "class_name": sclass.name if sclass else "?",
            "subject": new.subject,
            "hours": new.hours,
            "locked": new.locked,
        }
    return out


@router.post("/lock/{assignment_id}")
def lock(assignment_id: int, locked: bool = True,
         db: Session = Depends(get_db)):
    a = db.get(models.Assignment, assignment_id)
    if a is None:
        raise HTTPException(404, "assignment not found")
    a.locked = locked
    db.commit()
    return {"ok": True, "locked": locked}


@router.delete("/{assignment_id}")
def delete_assignment(assignment_id: int, db: Session = Depends(get_db)):
    a = db.get(models.Assignment, assignment_id)
    if a is None:
        raise HTTPException(404, "assignment not found")
    db.delete(a)
    db.commit()
    return {"ok": True}
