"""CRUD for co-teaching rules."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..db import get_db

router = APIRouter(prefix="/api/coteaching", tags=["coteaching"])


def _to_out(r: models.CoTeachingRule, class_name: str) -> schemas.CoTeachingOut:
    teachers = [t.strip() for t in (r.teacher_csv or "").split(",")
                if t.strip()]
    return schemas.CoTeachingOut(
        id=r.id, class_name=class_name, subject=r.subject,
        required=r.required, weight=r.weight,
        n_teachers=r.n_teachers, teachers=teachers,
    )


@router.get("", response_model=list[schemas.CoTeachingOut])
def list_rules(db: Session = Depends(get_db)):
    classes = {c.id: c.name for c in db.query(models.SchoolClass).all()}
    rows = db.query(models.CoTeachingRule).all()
    return [_to_out(r, classes.get(r.class_id, "?")) for r in rows]


@router.post("", response_model=schemas.CoTeachingOut)
def create_rule(payload: schemas.CoTeachingIn,
                db: Session = Depends(get_db)):
    cl = db.query(models.SchoolClass).filter(
        models.SchoolClass.name == payload.class_name
    ).first()
    if cl is None:
        raise HTTPException(404, "class not found")
    existing = db.query(models.CoTeachingRule).filter(
        models.CoTeachingRule.class_id == cl.id,
        models.CoTeachingRule.subject == payload.subject,
    ).first()
    if existing is not None:
        raise HTTPException(400, "rule already exists for (class, subject)")
    rule = models.CoTeachingRule(
        class_id=cl.id, subject=payload.subject,
        required=payload.required, weight=payload.weight,
        n_teachers=max(1, int(payload.n_teachers)),
        teacher_csv=",".join(payload.teachers) or None,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _to_out(rule, payload.class_name)


@router.put("/{rule_id}", response_model=schemas.CoTeachingOut)
def update_rule(rule_id: int, payload: schemas.CoTeachingIn,
                db: Session = Depends(get_db)):
    r = db.get(models.CoTeachingRule, rule_id)
    if r is None:
        raise HTTPException(404, "rule not found")
    cl = db.query(models.SchoolClass).filter(
        models.SchoolClass.name == payload.class_name
    ).first()
    if cl is None:
        raise HTTPException(404, "class not found")
    r.class_id = cl.id
    r.subject = payload.subject
    r.required = payload.required
    r.weight = payload.weight
    r.n_teachers = max(1, int(payload.n_teachers))
    r.teacher_csv = ",".join(payload.teachers) or None
    db.commit()
    db.refresh(r)
    return _to_out(r, payload.class_name)


@router.delete("/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    r = db.get(models.CoTeachingRule, rule_id)
    if r is None:
        raise HTTPException(404, "rule not found")
    db.delete(r)
    db.commit()
    return {"ok": True}
