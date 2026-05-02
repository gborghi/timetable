"""CRUD for classrooms (aule)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..db import get_db
from .. import optimization
from ..utils.list_query import filter_and_sort, QueryError
from ..utils.pagination import paginated_or_list

router = APIRouter(prefix="/api/classrooms", tags=["classrooms"])


def _to_out(c: models.Classroom) -> schemas.ClassroomOut:
    tags = sorted({a.tag.name for a in c.tag_assignments if a.tag})
    return schemas.ClassroomOut(
        id=c.id, name=c.name, kind=c.kind,
        capacity=c.capacity,
        multi_class=c.multi_class,
        multi_class_max=c.multi_class_max,
        multi_class_pref=c.multi_class_pref,
        multi_class_pref_weight=c.multi_class_pref_weight,
        notes=c.notes,
        tags=tags,
        subject_prefs=[
            schemas.ClassroomSubjectPrefIn(
                subject=p.subject, weight=p.weight, required=p.required,
                state=(p.state or
                       ("enforced" if p.required else "allowed")),
            )
            for p in c.subject_prefs
        ],
        class_prefs=[
            schemas.ClassroomClassPrefIn(
                class_name=p.class_name, weight=p.weight, is_home=p.is_home
            )
            for p in c.class_prefs
        ],
        unavailability=[
            schemas.UnavailabilitySlot(
                day=u.day, hour=u.hour, state=u.state,
                soft_penalty=u.soft_penalty, reason=u.reason
            )
            for u in c.unavailability
        ],
    )


def _sync_tags(r: models.Classroom, tag_names: list[str], db: Session):
    """Resync the room's tag assignments. Creates Tag rows on the fly
    for unknown names."""
    target = {(t or "").strip().lower() for t in (tag_names or [])
              if t and t.strip()}
    # Delete dropped assignments
    keep_ids: set[int] = set()
    if target:
        for tname in target:
            tag = db.query(models.ClassroomTag).filter(
                models.ClassroomTag.name == tname
            ).first()
            if tag is None:
                tag = models.ClassroomTag(name=tname)
                db.add(tag)
                db.flush()
            keep_ids.add(tag.id)
    db.query(models.ClassroomTagAssignment).filter(
        models.ClassroomTagAssignment.classroom_id == r.id,
        ~models.ClassroomTagAssignment.tag_id.in_(keep_ids or [-1]),
    ).delete(synchronize_session=False)
    # Add missing assignments
    existing = {a.tag_id for a in db.query(
        models.ClassroomTagAssignment
    ).filter(
        models.ClassroomTagAssignment.classroom_id == r.id
    ).all()}
    for tid in keep_ids - existing:
        db.add(models.ClassroomTagAssignment(
            classroom_id=r.id, tag_id=tid,
        ))


@router.get("")
def list_rooms(q: str | None = Query(None),
               sort: str | None = Query(None),
               format: str | None = Query(None),
               limit: int | None = Query(None, ge=0, le=10000),
               offset: int | None = Query(None, ge=0),
               db: Session = Depends(get_db)):
    rows = db.query(models.Classroom).order_by(models.Classroom.name).all()
    out = [_to_out(c).model_dump() for c in rows]
    try:
        filtered = filter_and_sort(out, "classrooms", q, sort)
    except QueryError as e:
        raise HTTPException(400, f"Errore query: {e}")
    return paginated_or_list(filtered, limit, offset,
                              fmt=format, entity="classrooms")


@router.get("/suggested-counts")
def suggested_counts(db: Session = Depends(get_db)):
    """Return the proportional default counts for each lab/palestra/etc.
    given the number of classes currently in the DB. Used by the UI to
    pre-populate the auto-generate form."""
    from .. import mock_classrooms
    n = db.query(models.SchoolClass).count()
    defaults = mock_classrooms.compute_default_counts(n)
    total_extra = sum(defaults.values())
    return {
        "n_classes": n,
        "counts": defaults,
        "total_classrooms_if_applied": n + total_extra,
        "rules": {
            "standard": "1 per classe (home room)",
            "lab_fisica": "~ 1 ogni 10 classi (min 1)",
            "lab_chimica": "~ 1 ogni 10 classi (min 1)",
            "lab_informatica": "~ 1 ogni 8 classi (min 1)",
            "lab_linguistico": "~ 1 ogni 12 classi (min 1)",
            "palestra": "~ 1 ogni 18 classi (min 1)",
            "biblioteca": "1 fissa fino a 60 classi, poi +1 ogni 60",
            "aula_speciale": "~ 1 ogni 20 classi (min 1)",
        },
    }


@router.post("/auto-generate")
def auto_generate(payload: schemas.MockClassroomsIn,
                  db: Session = Depends(get_db)):
    overrides = {
        "lab_chimica": payload.n_lab_chimica,
        "lab_fisica": payload.n_lab_fisica,
        "lab_informatica": payload.n_lab_informatica,
        "lab_linguistico": payload.n_lab_linguistico,
        "palestra": payload.n_palestra,
        "biblioteca": payload.n_biblioteca,
        "aula_speciale": payload.n_aula_speciale,
    }
    summary = optimization.auto_generate_classrooms(overrides)
    return {"ok": True, **summary}


@router.get("/{room_id}", response_model=schemas.ClassroomOut)
def get_room(room_id: int, db: Session = Depends(get_db)):
    r = db.get(models.Classroom, room_id)
    if r is None:
        raise HTTPException(404, "classroom not found")
    return _to_out(r)


def _apply(r: models.Classroom, p: schemas.ClassroomIn, db: Session):
    r.name = p.name
    r.kind = p.kind
    r.capacity = p.capacity
    r.multi_class = p.multi_class
    r.multi_class_max = p.multi_class_max
    r.multi_class_pref = p.multi_class_pref
    r.multi_class_pref_weight = p.multi_class_pref_weight
    r.notes = p.notes
    if r.id is not None:
        db.query(models.ClassroomSubjectPreference).filter(
            models.ClassroomSubjectPreference.classroom_id == r.id
        ).delete()
        db.query(models.ClassroomClassPreference).filter(
            models.ClassroomClassPreference.classroom_id == r.id
        ).delete()
        db.query(models.ClassroomUnavailability).filter(
            models.ClassroomUnavailability.classroom_id == r.id
        ).delete()
        db.flush()
    for sp in p.subject_prefs:
        st = sp.state if sp.state in (
            "allowed", "soft", "preferred", "forbidden", "enforced"
        ) else ("enforced" if sp.required else "allowed")
        db.add(models.ClassroomSubjectPreference(
            classroom_id=r.id, subject=sp.subject,
            state=st,
            weight=sp.weight, required=(st == "enforced" or sp.required),
        ))
    for cp in p.class_prefs:
        db.add(models.ClassroomClassPreference(
            classroom_id=r.id, class_name=cp.class_name,
            weight=cp.weight, is_home=cp.is_home,
        ))
    for u in p.unavailability:
        db.add(models.ClassroomUnavailability(
            classroom_id=r.id, day=int(u.day), hour=int(u.hour),
            state=u.state if u.state in ("hard", "soft", "preferred", "enforced") else "hard",
            soft_penalty=int(u.soft_penalty or 100),
            reason=u.reason,
        ))
    # Sync tags (many-to-many)
    _sync_tags(r, getattr(p, "tags", None) or [], db)


@router.post("", response_model=schemas.ClassroomOut)
def create_room(payload: schemas.ClassroomIn,
                db: Session = Depends(get_db)):
    if db.query(models.Classroom).filter(
        models.Classroom.name == payload.name
    ).first():
        raise HTTPException(400, "classroom already exists")
    r = models.Classroom(name=payload.name)
    db.add(r)
    db.flush()
    _apply(r, payload, db)
    db.commit()
    db.refresh(r)
    return _to_out(r)


@router.put("/{room_id}", response_model=schemas.ClassroomOut)
def update_room(room_id: int, payload: schemas.ClassroomIn,
                db: Session = Depends(get_db)):
    r = db.get(models.Classroom, room_id)
    if r is None:
        raise HTTPException(404, "classroom not found")
    _apply(r, payload, db)
    db.commit()
    db.refresh(r)
    return _to_out(r)


@router.delete("/{room_id}")
def delete_room(room_id: int, db: Session = Depends(get_db)):
    r = db.get(models.Classroom, room_id)
    if r is None:
        raise HTTPException(404, "classroom not found")
    db.delete(r)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------
# Classroom tags (CRUD)
# ---------------------------------------------------------------------

# Mounted on a separate prefix so the URL is friendly. The router
# itself is /api/classrooms; we also expose /api/classroom-tags for
# the tag dictionary, registered in main.py.
tags_router = APIRouter(prefix="/api/classroom-tags",
                         tags=["classrooms"])


@tags_router.get("", response_model=list[schemas.ClassroomTagOut])
def list_tags(db: Session = Depends(get_db)):
    """List every tag with the count of classrooms using it."""
    rows = db.query(models.ClassroomTag).order_by(
        models.ClassroomTag.name
    ).all()
    # Count assignments per tag in one query
    from sqlalchemy import func
    counts = dict(
        db.query(
            models.ClassroomTagAssignment.tag_id,
            func.count(models.ClassroomTagAssignment.id),
        ).group_by(models.ClassroomTagAssignment.tag_id).all()
    )
    return [
        schemas.ClassroomTagOut(
            id=t.id, name=t.name, description=t.description,
            n_classrooms=int(counts.get(t.id, 0)),
        )
        for t in rows
    ]


@tags_router.post("", response_model=schemas.ClassroomTagOut)
def create_tag(payload: schemas.ClassroomTagIn,
               db: Session = Depends(get_db)):
    name = (payload.name or "").strip().lower()
    if not name:
        raise HTTPException(400, "name vuoto")
    if db.query(models.ClassroomTag).filter(
        models.ClassroomTag.name == name
    ).first():
        raise HTTPException(409, f"tag '{name}' esiste gia'")
    t = models.ClassroomTag(name=name, description=payload.description)
    db.add(t)
    db.commit()
    db.refresh(t)
    return schemas.ClassroomTagOut(
        id=t.id, name=t.name, description=t.description, n_classrooms=0,
    )


@tags_router.put("/{tag_id}", response_model=schemas.ClassroomTagOut)
def update_tag(tag_id: int, payload: schemas.ClassroomTagIn,
               db: Session = Depends(get_db)):
    t = db.get(models.ClassroomTag, tag_id)
    if t is None:
        raise HTTPException(404, "tag non trovato")
    new_name = (payload.name or "").strip().lower()
    if not new_name:
        raise HTTPException(400, "name vuoto")
    if new_name != t.name:
        clash = db.query(models.ClassroomTag).filter(
            models.ClassroomTag.name == new_name
        ).first()
        if clash is not None and clash.id != t.id:
            raise HTTPException(409, f"tag '{new_name}' esiste gia'")
    t.name = new_name
    t.description = payload.description
    db.commit()
    db.refresh(t)
    from sqlalchemy import func
    n = int(db.query(func.count(models.ClassroomTagAssignment.id)).filter(
        models.ClassroomTagAssignment.tag_id == t.id
    ).scalar() or 0)
    return schemas.ClassroomTagOut(
        id=t.id, name=t.name, description=t.description, n_classrooms=n,
    )


@tags_router.delete("/{tag_id}")
def delete_tag(tag_id: int, db: Session = Depends(get_db)):
    t = db.get(models.ClassroomTag, tag_id)
    if t is None:
        raise HTTPException(404, "tag non trovato")
    db.delete(t)   # cascade removes assignments
    db.commit()
    return {"ok": True}
