"""CRUD for saved views (named filter+sort combinations attached to
an entity list). Used by the dropdown above the SortableQueryableList."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..db import get_db

router = APIRouter(prefix="/api/saved-views", tags=["saved-views"])


_ALLOWED_ENTITIES = {
    "teachers", "classes", "classrooms", "subjects", "students",
    "groups", "curricula", "constraints", "monitor",
}


def _to_out(v: models.SavedView) -> schemas.SavedViewOut:
    levels = []
    if v.sort_levels_json:
        try:
            arr = json.loads(v.sort_levels_json)
            if isinstance(arr, list):
                for it in arr:
                    if isinstance(it, dict) and "column" in it:
                        levels.append(schemas.SortLevel(
                            column=str(it.get("column") or ""),
                            direction=str(it.get("direction") or "asc"),
                        ))
        except Exception:
            pass
    return schemas.SavedViewOut(
        id=v.id, entity=v.entity, name=v.name,
        dsl_query=v.dsl_query, sort_levels=levels,
        description=v.description,
    )


@router.get("", response_model=list[schemas.SavedViewOut])
def list_views(
    entity: str | None = Query(
        None,
        description="filter to a specific entity",
    ),
    db: Session = Depends(get_db),
):
    qry = db.query(models.SavedView).order_by(
        models.SavedView.entity, models.SavedView.name,
    )
    if entity:
        qry = qry.filter(models.SavedView.entity == entity.lower())
    return [_to_out(v) for v in qry.all()]


@router.post("", response_model=schemas.SavedViewOut)
def create_view(payload: schemas.SavedViewIn,
                db: Session = Depends(get_db)):
    entity = (payload.entity or "").strip().lower()
    name = (payload.name or "").strip()
    if entity not in _ALLOWED_ENTITIES:
        raise HTTPException(
            400, f"entita' non riconosciuta: '{entity}'. "
                 f"Valide: {sorted(_ALLOWED_ENTITIES)}"
        )
    if not name:
        raise HTTPException(400, "nome vista vuoto")
    clash = db.query(models.SavedView).filter(
        models.SavedView.entity == entity,
        models.SavedView.name == name,
    ).first()
    if clash is not None:
        raise HTTPException(
            409, f"esiste gia' una vista '{name}' per {entity}"
        )
    levels_json = json.dumps([
        {"column": l.column, "direction": l.direction}
        for l in payload.sort_levels
    ])
    v = models.SavedView(
        entity=entity, name=name,
        dsl_query=payload.dsl_query or None,
        sort_levels_json=levels_json,
        description=payload.description,
    )
    db.add(v)
    db.commit()
    db.refresh(v)
    return _to_out(v)


@router.put("/{vid}", response_model=schemas.SavedViewOut)
def update_view(vid: int, payload: schemas.SavedViewIn,
                db: Session = Depends(get_db)):
    v = db.get(models.SavedView, vid)
    if v is None:
        raise HTTPException(404, "vista non trovata")
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(400, "nome vista vuoto")
    if name != v.name:
        clash = db.query(models.SavedView).filter(
            models.SavedView.entity == v.entity,
            models.SavedView.name == name,
            models.SavedView.id != vid,
        ).first()
        if clash is not None:
            raise HTTPException(409, f"nome '{name}' gia' usato")
        v.name = name
    v.dsl_query = payload.dsl_query or None
    v.description = payload.description
    v.sort_levels_json = json.dumps([
        {"column": l.column, "direction": l.direction}
        for l in payload.sort_levels
    ])
    db.commit()
    db.refresh(v)
    return _to_out(v)


@router.delete("/{vid}")
def delete_view(vid: int, db: Session = Depends(get_db)):
    v = db.get(models.SavedView, vid)
    if v is None:
        raise HTTPException(404, "vista non trovata")
    db.delete(v)
    db.commit()
    return {"ok": True}
