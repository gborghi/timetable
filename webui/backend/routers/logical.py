"""Logical disjunctive availability constraints — uniform across
teachers, classes, classrooms.

Endpoints:
  GET    /api/{entity}/{id}/logical-unavailabilities
  POST   /api/{entity}/{id}/logical-unavailabilities
  PUT    /api/{entity}/{id}/logical-unavailabilities/{rule_id}
  DELETE /api/{entity}/{id}/logical-unavailabilities/{rule_id}
  POST   /api/logic/validate                (test-parse helper)

`{entity}` is one of teachers/classes/classrooms; the table holds them
all in one row set discriminated by `entity_type`."""
from __future__ import annotations

import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..db import get_db
from ..utils.logic_parser import LogicError, parse_to_dnf

router = APIRouter(tags=["logical"])

ENTITY_MODEL = {
    "teachers": models.Teacher,
    "classes": models.SchoolClass,
    "classrooms": models.Classroom,
}
ENTITY_TYPE = {
    "teachers": "teacher",
    "classes": "class",
    "classrooms": "classroom",
}


def _check_entity(entity: str, entity_id: int, db: Session):
    Model = ENTITY_MODEL.get(entity)
    if Model is None:
        raise HTTPException(404, f"entita sconosciuta: {entity}")
    obj = db.get(Model, entity_id)
    if obj is None:
        raise HTTPException(404, f"{entity} {entity_id} inesistente")
    return obj


def _row_to_out(row: models.LogicalUnavailability) -> schemas.LogicalUnavOut:
    try:
        clauses = json.loads(row.parsed_dnf_json or "[]")
    except Exception:
        clauses = []
    from ..utils.logic_parser import dnf_to_pretty
    return schemas.LogicalUnavOut(
        id=row.id, entity_type=row.entity_type, entity_id=row.entity_id,
        expression=row.expression, pretty=dnf_to_pretty(clauses),
        clauses=clauses, is_hard=row.is_hard, soft_penalty=row.soft_penalty,
    )


@router.post("/api/logic/validate", response_model=schemas.LogicValidateOut)
def validate(payload: schemas.LogicValidateIn):
    try:
        parsed = parse_to_dnf(payload.expression)
        return schemas.LogicValidateOut(
            ok=True, expression=parsed.expression,
            pretty=parsed.pretty, clauses=parsed.clauses,
        )
    except LogicError as e:
        return schemas.LogicValidateOut(
            ok=False, expression=payload.expression, error=str(e)
        )


def _list_rules(entity: str, entity_id: int, db: Session):
    _check_entity(entity, entity_id, db)
    rows = db.query(models.LogicalUnavailability).filter(
        models.LogicalUnavailability.entity_type == ENTITY_TYPE[entity],
        models.LogicalUnavailability.entity_id == entity_id,
    ).order_by(models.LogicalUnavailability.id).all()
    return [_row_to_out(r) for r in rows]


def _add_rule(entity: str, entity_id: int,
              payload: schemas.LogicalUnavIn, db: Session):
    _check_entity(entity, entity_id, db)
    try:
        parsed = parse_to_dnf(payload.expression)
    except LogicError as e:
        raise HTTPException(400, f"sintassi non valida: {e}")
    if not parsed.clauses:
        raise HTTPException(400, "espressione vuota")
    row = models.LogicalUnavailability(
        entity_type=ENTITY_TYPE[entity], entity_id=entity_id,
        expression=payload.expression,
        parsed_dnf_json=json.dumps(parsed.clauses),
        is_hard=payload.is_hard,
        soft_penalty=int(payload.soft_penalty),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _row_to_out(row)


def _update_rule(entity: str, entity_id: int, rule_id: int,
                 payload: schemas.LogicalUnavIn, db: Session):
    _check_entity(entity, entity_id, db)
    row = db.get(models.LogicalUnavailability, rule_id)
    if row is None or row.entity_type != ENTITY_TYPE[entity] \
            or row.entity_id != entity_id:
        raise HTTPException(404, "regola inesistente per quell'entita")
    try:
        parsed = parse_to_dnf(payload.expression)
    except LogicError as e:
        raise HTTPException(400, f"sintassi non valida: {e}")
    row.expression = payload.expression
    row.parsed_dnf_json = json.dumps(parsed.clauses)
    row.is_hard = payload.is_hard
    row.soft_penalty = int(payload.soft_penalty)
    db.commit()
    db.refresh(row)
    return _row_to_out(row)


def _delete_rule(entity: str, entity_id: int, rule_id: int, db: Session):
    _check_entity(entity, entity_id, db)
    row = db.get(models.LogicalUnavailability, rule_id)
    if row is None or row.entity_type != ENTITY_TYPE[entity] \
            or row.entity_id != entity_id:
        raise HTTPException(404, "regola inesistente per quell'entita")
    db.delete(row)
    db.commit()
    return {"ok": True}


# Teachers ---------------------------------------------------------------

@router.get("/api/teachers/{teacher_id}/logical-unavailabilities",
            response_model=list[schemas.LogicalUnavOut])
def list_teacher_rules(teacher_id: int, db: Session = Depends(get_db)):
    return _list_rules("teachers", teacher_id, db)


@router.post("/api/teachers/{teacher_id}/logical-unavailabilities",
             response_model=schemas.LogicalUnavOut)
def add_teacher_rule(teacher_id: int, payload: schemas.LogicalUnavIn,
                     db: Session = Depends(get_db)):
    return _add_rule("teachers", teacher_id, payload, db)


@router.put("/api/teachers/{teacher_id}/logical-unavailabilities/{rule_id}",
            response_model=schemas.LogicalUnavOut)
def update_teacher_rule(teacher_id: int, rule_id: int,
                        payload: schemas.LogicalUnavIn,
                        db: Session = Depends(get_db)):
    return _update_rule("teachers", teacher_id, rule_id, payload, db)


@router.delete("/api/teachers/{teacher_id}/logical-unavailabilities/{rule_id}")
def del_teacher_rule(teacher_id: int, rule_id: int,
                     db: Session = Depends(get_db)):
    return _delete_rule("teachers", teacher_id, rule_id, db)


# Classes ---------------------------------------------------------------

@router.get("/api/classes/{class_id}/logical-unavailabilities",
            response_model=list[schemas.LogicalUnavOut])
def list_class_rules(class_id: int, db: Session = Depends(get_db)):
    return _list_rules("classes", class_id, db)


@router.post("/api/classes/{class_id}/logical-unavailabilities",
             response_model=schemas.LogicalUnavOut)
def add_class_rule(class_id: int, payload: schemas.LogicalUnavIn,
                   db: Session = Depends(get_db)):
    return _add_rule("classes", class_id, payload, db)


@router.put("/api/classes/{class_id}/logical-unavailabilities/{rule_id}",
            response_model=schemas.LogicalUnavOut)
def update_class_rule(class_id: int, rule_id: int,
                      payload: schemas.LogicalUnavIn,
                      db: Session = Depends(get_db)):
    return _update_rule("classes", class_id, rule_id, payload, db)


@router.delete("/api/classes/{class_id}/logical-unavailabilities/{rule_id}")
def del_class_rule(class_id: int, rule_id: int,
                   db: Session = Depends(get_db)):
    return _delete_rule("classes", class_id, rule_id, db)


# Classrooms ------------------------------------------------------------

@router.get("/api/classrooms/{room_id}/logical-unavailabilities",
            response_model=list[schemas.LogicalUnavOut])
def list_room_rules(room_id: int, db: Session = Depends(get_db)):
    return _list_rules("classrooms", room_id, db)


@router.post("/api/classrooms/{room_id}/logical-unavailabilities",
             response_model=schemas.LogicalUnavOut)
def add_room_rule(room_id: int, payload: schemas.LogicalUnavIn,
                  db: Session = Depends(get_db)):
    return _add_rule("classrooms", room_id, payload, db)


@router.put("/api/classrooms/{room_id}/logical-unavailabilities/{rule_id}",
            response_model=schemas.LogicalUnavOut)
def update_room_rule(room_id: int, rule_id: int,
                     payload: schemas.LogicalUnavIn,
                     db: Session = Depends(get_db)):
    return _update_rule("classrooms", room_id, rule_id, payload, db)


@router.delete("/api/classrooms/{room_id}/logical-unavailabilities/{rule_id}")
def del_room_rule(room_id: int, rule_id: int,
                  db: Session = Depends(get_db)):
    return _delete_rule("classrooms", room_id, rule_id, db)
