"""CRUD for plessi (school sites) + commuting rules + entity
policies.

Routes:
  - /api/plessi                     -- CRUD on Plesso rows
  - /api/plessi/commuting-rules     -- CRUD on PlessoCommutingRule
  - /api/plessi/entity-policies     -- CRUD on PlessoEntityPolicy
  - /api/plessi/validate            -- run pre-flight validation
                                        (returns the list of
                                        violations without raising)

Route order matters: the static sub-paths (/commuting-rules,
/entity-policies, /validate) MUST be declared before the
dynamic /{pid} routes, otherwise FastAPI tries to parse the
literal sub-path as a Plesso integer id and returns 422.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..db import get_db
from .. import optimization

router = APIRouter(prefix="/api/plessi", tags=["plessi"])


# =========================================================
# Static sub-routes (declared BEFORE /{pid} dynamic routes)
# =========================================================


# ---------- Commuting rules CRUD ----------


@router.get(
    "/commuting-rules",
    response_model=list[schemas.PlessoCommutingRuleOut])
def list_commuting_rules(
    entity_kind: str | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(models.PlessoCommutingRule)
    if entity_kind:
        q = q.filter(
            models.PlessoCommutingRule.entity_kind == entity_kind)
    rows = q.order_by(
        models.PlessoCommutingRule.from_plesso_id,
        models.PlessoCommutingRule.to_plesso_id,
        models.PlessoCommutingRule.entity_kind,
    ).all()
    return [schemas.PlessoCommutingRuleOut.model_validate(r)
            for r in rows]


@router.post(
    "/commuting-rules",
    response_model=schemas.PlessoCommutingRuleOut)
def create_commuting_rule(
    payload: schemas.PlessoCommutingRuleIn,
    db: Session = Depends(get_db),
):
    r = models.PlessoCommutingRule(**payload.model_dump())
    db.add(r)
    try:
        db.commit()
        db.refresh(r)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        raise HTTPException(
            400, f"Commuting rule non creata: {e}") from e
    return schemas.PlessoCommutingRuleOut.model_validate(r)


@router.put(
    "/commuting-rules/{rid}",
    response_model=schemas.PlessoCommutingRuleOut)
def update_commuting_rule(
    rid: int,
    payload: schemas.PlessoCommutingRuleIn,
    db: Session = Depends(get_db),
):
    r = db.query(models.PlessoCommutingRule).filter(
        models.PlessoCommutingRule.id == rid).one_or_none()
    if r is None:
        raise HTTPException(404, f"Commuting rule #{rid} non trovata")
    for k, v in payload.model_dump().items():
        setattr(r, k, v)
    db.commit()
    db.refresh(r)
    return schemas.PlessoCommutingRuleOut.model_validate(r)


@router.delete("/commuting-rules/{rid}", status_code=204)
def delete_commuting_rule(rid: int, db: Session = Depends(get_db)):
    r = db.query(models.PlessoCommutingRule).filter(
        models.PlessoCommutingRule.id == rid).one_or_none()
    if r is None:
        raise HTTPException(404, f"Commuting rule #{rid} non trovata")
    db.delete(r)
    db.commit()


# ---------- Entity policies CRUD ----------


@router.get(
    "/entity-policies",
    response_model=list[schemas.PlessoEntityPolicyOut])
def list_entity_policies(
    entity_kind: str | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(models.PlessoEntityPolicy)
    if entity_kind:
        q = q.filter(
            models.PlessoEntityPolicy.entity_kind == entity_kind)
    rows = q.order_by(
        models.PlessoEntityPolicy.entity_kind,
        models.PlessoEntityPolicy.entity_id.is_(None).desc(),
        models.PlessoEntityPolicy.entity_id,
    ).all()
    return [schemas.PlessoEntityPolicyOut.model_validate(r)
            for r in rows]


@router.post(
    "/entity-policies",
    response_model=schemas.PlessoEntityPolicyOut)
def create_entity_policy(
    payload: schemas.PlessoEntityPolicyIn,
    db: Session = Depends(get_db),
):
    pol = models.PlessoEntityPolicy(**payload.model_dump())
    db.add(pol)
    try:
        db.commit()
        db.refresh(pol)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        raise HTTPException(
            400, f"Entity policy non creata: {e}") from e
    return schemas.PlessoEntityPolicyOut.model_validate(pol)


@router.put(
    "/entity-policies/{pid}",
    response_model=schemas.PlessoEntityPolicyOut)
def update_entity_policy(
    pid: int,
    payload: schemas.PlessoEntityPolicyIn,
    db: Session = Depends(get_db),
):
    pol = db.query(models.PlessoEntityPolicy).filter(
        models.PlessoEntityPolicy.id == pid).one_or_none()
    if pol is None:
        raise HTTPException(404, f"Entity policy #{pid} non trovata")
    for k, v in payload.model_dump().items():
        setattr(pol, k, v)
    db.commit()
    db.refresh(pol)
    return schemas.PlessoEntityPolicyOut.model_validate(pol)


@router.delete("/entity-policies/{pid}", status_code=204)
def delete_entity_policy(pid: int, db: Session = Depends(get_db)):
    pol = db.query(models.PlessoEntityPolicy).filter(
        models.PlessoEntityPolicy.id == pid).one_or_none()
    if pol is None:
        raise HTTPException(404, f"Entity policy #{pid} non trovata")
    db.delete(pol)
    db.commit()


# ---------- Validation ----------


@router.get("/validate")
def validate_plessi(db: Session = Depends(get_db)):
    """Run the same pre-flight validation invoked by every solver
    run, but return the list of violations as JSON instead of
    raising. Useful for the UI to show a live "config OK" badge.
    """
    violations = optimization.validate_plessi_rules(db)
    return {
        "ok": len(violations) == 0,
        "violations": violations,
    }


# =========================================================
# Plesso CRUD (the dynamic /{pid} routes go LAST)
# =========================================================


@router.get("", response_model=list[schemas.PlessoOut])
def list_plessi(db: Session = Depends(get_db)):
    return [
        schemas.PlessoOut.model_validate(p)
        for p in db.query(models.Plesso).order_by(
            models.Plesso.name).all()
    ]


@router.post("", response_model=schemas.PlessoOut)
def create_plesso(
    payload: schemas.PlessoIn,
    db: Session = Depends(get_db),
):
    p = models.Plesso(
        name=payload.name,
        code=payload.code,
        address=payload.address,
        notes=payload.notes,
    )
    db.add(p)
    try:
        db.commit()
        db.refresh(p)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        raise HTTPException(
            400, f"Plesso non creato: {e}") from e
    return schemas.PlessoOut.model_validate(p)


@router.get("/{pid}", response_model=schemas.PlessoOut)
def get_plesso(pid: int, db: Session = Depends(get_db)):
    p = db.query(models.Plesso).filter(
        models.Plesso.id == pid).one_or_none()
    if p is None:
        raise HTTPException(404, f"Plesso #{pid} non trovato")
    return schemas.PlessoOut.model_validate(p)


@router.put("/{pid}", response_model=schemas.PlessoOut)
def update_plesso(
    pid: int,
    payload: schemas.PlessoIn,
    db: Session = Depends(get_db),
):
    p = db.query(models.Plesso).filter(
        models.Plesso.id == pid).one_or_none()
    if p is None:
        raise HTTPException(404, f"Plesso #{pid} non trovato")
    p.name = payload.name
    p.code = payload.code
    p.address = payload.address
    p.notes = payload.notes
    db.commit()
    db.refresh(p)
    return schemas.PlessoOut.model_validate(p)


@router.delete("/{pid}", status_code=204)
def delete_plesso(pid: int, db: Session = Depends(get_db)):
    p = db.query(models.Plesso).filter(
        models.Plesso.id == pid).one_or_none()
    if p is None:
        raise HTTPException(404, f"Plesso #{pid} non trovato")
    db.delete(p)
    db.commit()
