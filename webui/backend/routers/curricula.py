"""CRUD for curricula (indirizzi di studio).

Each curriculum carries:
  * a code (machine name, unique) and a display name
  * monte ore per (year, subject) — the canonical weekly grid for that
    indirizzo
  * curriculum-level logical constraints, optionally restricted to a
    specific year

Endpoints:
  GET    /api/curricula
  GET    /api/curricula/{id}
  POST   /api/curricula
  PUT    /api/curricula/{id}
  DELETE /api/curricula/{id}
  GET    /api/curricula/{id}/logical-constraints
  POST   /api/curricula/{id}/logical-constraints
  PUT    /api/curricula/{id}/logical-constraints/{rule_id}
  DELETE /api/curricula/{id}/logical-constraints/{rule_id}
"""
from __future__ import annotations

import json
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..db import get_db
from ..utils.list_query import filter_and_sort, QueryError
from ..utils.logic_parser import LogicError, parse_to_dnf, dnf_to_pretty
from ..utils.pagination import paginated_or_list

router = APIRouter(prefix="/api/curricula", tags=["curricula"])


def _hours_for(c: models.Curriculum) -> list[schemas.CurriculumSubjectHoursIn]:
    return [
        schemas.CurriculumSubjectHoursIn(
            year=h.year, subject=h.subject,
            hours_per_week=h.hours_per_week,
        )
        for h in sorted(c.hours, key=lambda x: (x.year, x.subject))
    ]


def _to_out(c: models.Curriculum, db: Session) -> schemas.CurriculumOut:
    n_classes = db.query(models.SchoolClass).filter(
        models.SchoolClass.curriculum_id == c.id
    ).count()
    return schemas.CurriculumOut(
        id=c.id, code=c.code, name=c.name,
        description=c.description, notes=c.notes, score=c.score,
        hours=_hours_for(c),
        n_classes=n_classes,
    )


@router.get("")
def list_curricula(q: str | None = Query(None),
                   sort: str | None = Query(None),
                   format: str | None = Query(None),
                   db: Session = Depends(get_db)):
    rows = db.query(models.Curriculum).order_by(models.Curriculum.code).all()
    out = [_to_out(c, db).model_dump() for c in rows]
    try:
        filtered = filter_and_sort(out, "curricula", q, sort)
    except QueryError as e:
        raise HTTPException(400, f"Errore query: {e}")
    return paginated_or_list(filtered, None, None,
                              fmt=format, entity="curricula")


@router.get("/{cid}", response_model=schemas.CurriculumOut)
def get_curriculum(cid: int, db: Session = Depends(get_db)):
    c = db.get(models.Curriculum, cid)
    if c is None:
        raise HTTPException(404, "curriculum non trovato")
    return _to_out(c, db)


def _apply(c: models.Curriculum, p: schemas.CurriculumIn, db: Session) -> None:
    c.code = p.code
    c.name = p.name
    c.description = p.description
    c.notes = p.notes
    c.score = int(p.score)
    if c.id is not None:
        db.query(models.CurriculumSubjectHours).filter(
            models.CurriculumSubjectHours.curriculum_id == c.id
        ).delete()
        db.flush()
    for h in p.hours:
        db.add(models.CurriculumSubjectHours(
            curriculum_id=c.id, year=int(h.year),
            subject=h.subject, hours_per_week=int(h.hours_per_week),
        ))


@router.post("", response_model=schemas.CurriculumOut)
def create_curriculum(payload: schemas.CurriculumIn,
                      db: Session = Depends(get_db)):
    if db.query(models.Curriculum).filter(
        models.Curriculum.code == payload.code
    ).first():
        raise HTTPException(400, "esiste gia un indirizzo con questo code")
    c = models.Curriculum(code=payload.code, name=payload.name)
    db.add(c)
    db.flush()
    _apply(c, payload, db)
    db.commit()
    db.refresh(c)
    return _to_out(c, db)


@router.put("/{cid}", response_model=schemas.CurriculumOut)
def update_curriculum(cid: int, payload: schemas.CurriculumIn,
                      db: Session = Depends(get_db)):
    c = db.get(models.Curriculum, cid)
    if c is None:
        raise HTTPException(404, "curriculum non trovato")
    # Reject duplicate code only if changing it onto another row
    other = db.query(models.Curriculum).filter(
        models.Curriculum.code == payload.code,
        models.Curriculum.id != cid
    ).first()
    if other:
        raise HTTPException(400, "code gia in uso da un altro indirizzo")
    _apply(c, payload, db)
    db.commit()
    db.refresh(c)
    return _to_out(c, db)


@router.delete("/{cid}")
def delete_curriculum(cid: int, db: Session = Depends(get_db)):
    c = db.get(models.Curriculum, cid)
    if c is None:
        raise HTTPException(404, "curriculum non trovato")
    # SchoolClass.curriculum_id is set NULL by FK ondelete; the legacy
    # string column is left untouched.
    db.delete(c)
    db.commit()
    return {"ok": True}


# ---------- Logical constraints (curriculum-level) ----------


def _kind_from_legacy(is_hard: bool, soft_penalty: int) -> str:
    if is_hard:
        return "hard"
    if (soft_penalty or 0) < 0:
        return "preferred"
    return "soft"


def _normalise_kind(payload: schemas.CurriculumLogicalConstraintIn
                    ) -> tuple[str, bool, int]:
    raw = (payload.kind or "").strip().lower()
    if raw not in ("hard", "soft", "preferred", "enforced"):
        raw = _kind_from_legacy(payload.is_hard, payload.soft_penalty)
    pen = int(payload.soft_penalty)
    if raw == "hard":
        return "hard", True, max(0, pen) or 100
    if raw == "enforced":
        return "enforced", True, max(0, pen) or 100
    if raw == "preferred":
        return "preferred", False, -abs(pen if pen else 100)
    return "soft", False, abs(pen if pen else 100)


def _row_to_out(row: models.CurriculumLogicalConstraint
                ) -> schemas.CurriculumLogicalConstraintOut:
    try:
        clauses = json.loads(row.parsed_dnf_json or "[]")
    except Exception:
        clauses = []
    kind = row.kind or _kind_from_legacy(row.is_hard, row.soft_penalty)
    return schemas.CurriculumLogicalConstraintOut(
        id=row.id, curriculum_id=row.curriculum_id,
        year_filter=row.year_filter, label=row.label,
        expression=row.expression,
        pretty=dnf_to_pretty(clauses),
        clauses=clauses,
        is_hard=row.is_hard, soft_penalty=row.soft_penalty,
        kind=kind,
    )


@router.get("/{cid}/logical-constraints",
            response_model=list[schemas.CurriculumLogicalConstraintOut])
def list_curriculum_rules(cid: int, db: Session = Depends(get_db)):
    if db.get(models.Curriculum, cid) is None:
        raise HTTPException(404, "curriculum non trovato")
    rows = db.query(models.CurriculumLogicalConstraint).filter(
        models.CurriculumLogicalConstraint.curriculum_id == cid
    ).order_by(
        models.CurriculumLogicalConstraint.year_filter.is_(None).desc(),
        models.CurriculumLogicalConstraint.year_filter,
        models.CurriculumLogicalConstraint.id,
    ).all()
    return [_row_to_out(r) for r in rows]


@router.post("/{cid}/logical-constraints",
             response_model=schemas.CurriculumLogicalConstraintOut)
def add_curriculum_rule(cid: int,
                        payload: schemas.CurriculumLogicalConstraintIn,
                        db: Session = Depends(get_db)):
    if db.get(models.Curriculum, cid) is None:
        raise HTTPException(404, "curriculum non trovato")
    try:
        parsed = parse_to_dnf(payload.expression)
    except LogicError as e:
        raise HTTPException(400, f"sintassi non valida: {e}")
    if not parsed.clauses:
        raise HTTPException(400, "espressione vuota")
    kind, is_hard, pen = _normalise_kind(payload)
    row = models.CurriculumLogicalConstraint(
        curriculum_id=cid,
        year_filter=payload.year_filter,
        label=payload.label,
        expression=payload.expression,
        parsed_dnf_json=json.dumps(parsed.clauses),
        is_hard=is_hard,
        soft_penalty=pen,
        kind=kind,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _row_to_out(row)


@router.put("/{cid}/logical-constraints/{rid}",
            response_model=schemas.CurriculumLogicalConstraintOut)
def update_curriculum_rule(cid: int, rid: int,
                           payload: schemas.CurriculumLogicalConstraintIn,
                           db: Session = Depends(get_db)):
    row = db.get(models.CurriculumLogicalConstraint, rid)
    if row is None or row.curriculum_id != cid:
        raise HTTPException(404, "regola inesistente per questo indirizzo")
    try:
        parsed = parse_to_dnf(payload.expression)
    except LogicError as e:
        raise HTTPException(400, f"sintassi non valida: {e}")
    kind, is_hard, pen = _normalise_kind(payload)
    row.year_filter = payload.year_filter
    row.label = payload.label
    row.expression = payload.expression
    row.parsed_dnf_json = json.dumps(parsed.clauses)
    row.is_hard = is_hard
    row.soft_penalty = pen
    row.kind = kind
    db.commit()
    db.refresh(row)
    return _row_to_out(row)


@router.delete("/{cid}/logical-constraints/{rid}")
def delete_curriculum_rule(cid: int, rid: int,
                           db: Session = Depends(get_db)):
    row = db.get(models.CurriculumLogicalConstraint, rid)
    if row is None or row.curriculum_id != cid:
        raise HTTPException(404, "regola inesistente per questo indirizzo")
    db.delete(row)
    db.commit()
    return {"ok": True}
