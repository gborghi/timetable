"""CRUD for students. A student optionally belongs to a single home class;
membership in StudyGroup is handled via the /api/groups endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models, schemas
from ..db import get_db
from ..utils.list_query import filter_and_sort, QueryError
from ..utils.pagination import paginated_or_list

router = APIRouter(prefix="/api/students", tags=["students"])


def _student_tags(s: models.Student) -> list[str]:
    return sorted({a.tag.name for a in s.tag_assignments if a.tag})


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
        nickname=s.nickname,
        birth_date=s.birth_date, gender=s.gender, email=s.email,
        student_code=s.student_code, class_id=s.class_id, notes=s.notes,
        class_name=cls_name, n_groups=n_groups,
        tags=_student_tags(s),
    )


def _sync_student_tags(s: models.Student, tag_names: list[str],
                       db: Session) -> None:
    """Reconcile s.tag_assignments with the requested tag-name list.
    Unknown names are created on the fly (lower-cased)."""
    desired = {(t or "").strip().lower() for t in (tag_names or [])}
    desired.discard("")
    # Index existing tags by name
    name_to_tag = {
        t.name: t for t in db.query(models.StudentTag).filter(
            models.StudentTag.name.in_(desired)
        ).all()
    } if desired else {}
    # Create missing
    for n in desired - set(name_to_tag.keys()):
        new = models.StudentTag(name=n)
        db.add(new)
        db.flush()
        name_to_tag[n] = new
    # Current assignments by tag name
    current = {a.tag.name: a for a in s.tag_assignments if a.tag}
    # Drop missing
    for name, a in list(current.items()):
        if name not in desired:
            db.delete(a)
    # Add new
    for name in desired - set(current.keys()):
        db.add(models.StudentTagAssignment(
            student_id=s.id, tag_id=name_to_tag[name].id,
        ))


@router.get("")
def list_students(q: str | None = Query(None),
                  sort: str | None = Query(None),
                  class_id: int | None = Query(None),
                  limit: int | None = Query(None, ge=0, le=10000),
                  offset: int | None = Query(None, ge=0),
                  format: str | None = Query(None),
                  db: Session = Depends(get_db)):
    """List students. Pagination opt-in via `?limit=N&offset=M`:
    when either is set, response is `{items, total, limit, offset}`;
    otherwise the bare list is returned (legacy shape).
    """
    qry = db.query(models.Student)
    if class_id is not None:
        qry = qry.filter(models.Student.class_id == class_id)
    rows = qry.order_by(models.Student.last_name,
                        models.Student.first_name).all()
    out = [_to_out(s, db).model_dump() for s in rows]
    try:
        filtered = filter_and_sort(out, "students", q, sort)
    except QueryError as e:
        raise HTTPException(400, f"Errore query: {e}")
    return paginated_or_list(filtered, limit, offset,
                              fmt=format, entity="students")


@router.get("/by-tags")
def students_by_tags(
    any_of: str | None = Query(
        None,
        description="lista tag separati da virgola; "
                    "match: studente con almeno un tag della lista"
    ),
    all_of: str | None = Query(
        None,
        description="lista tag separati da virgola; "
                    "match: studente con TUTTI i tag della lista"
    ),
    db: Session = Depends(get_db),
):
    """Returns students matching a tag filter. Used by the
    'precompile group members' action when creating a new study
    group from a tag (e.g. all students with debito_matematica_4).
    """
    def _split(s: str | None) -> list[str]:
        if not s:
            return []
        return [t.strip().lower() for t in s.split(",") if t.strip()]

    any_set = _split(any_of)
    all_set = _split(all_of)
    rows = db.query(models.Student).all()
    out = []
    for s in rows:
        tags = set(_student_tags(s))
        if any_set and not tags.intersection(any_set):
            continue
        if all_set and not set(all_set).issubset(tags):
            continue
        out.append({
            "id": s.id,
            "last_name": s.last_name,
            "first_name": s.first_name,
            "nickname": s.nickname,
            "class_id": s.class_id,
            "tags": sorted(tags),
        })
    return out


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
    s.nickname = p.nickname
    s.birth_date = p.birth_date
    s.gender = p.gender
    s.email = p.email
    s.student_code = p.student_code
    if s.class_id != p.class_id and s.id is not None:
        # The docente di sostegno is assigned to the pupil, so they
        # move with them. Assignment.class_id is only a cached copy of
        # where the pupil is; the solver re-derives it anyway (see
        # engine_io.support_class_id), but leaving it stale would show
        # the support teacher in the old class all over the UI.
        for a in db.query(models.Assignment).filter(
                models.Assignment.student_id == s.id).all():
            a.class_id = p.class_id
    s.class_id = p.class_id
    s.notes = p.notes
    _sync_student_tags(s, getattr(p, "tags", None) or [], db)


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


# ---------------------------------------------------------------- Tags

tags_router = APIRouter(prefix="/api/student-tags", tags=["students"])


@tags_router.get("", response_model=list[schemas.StudentTagOut])
def list_student_tags(db: Session = Depends(get_db)):
    counts = dict(
        db.query(
            models.StudentTagAssignment.tag_id,
            func.count(models.StudentTagAssignment.id),
        ).group_by(models.StudentTagAssignment.tag_id).all()
    )
    rows = db.query(models.StudentTag).order_by(models.StudentTag.name).all()
    return [
        schemas.StudentTagOut(
            id=t.id, name=t.name, description=t.description,
            n_students=int(counts.get(t.id, 0)),
        )
        for t in rows
    ]


@tags_router.post("", response_model=schemas.StudentTagOut)
def create_student_tag(payload: schemas.StudentTagIn,
                       db: Session = Depends(get_db)):
    name = (payload.name or "").strip().lower()
    if not name:
        raise HTTPException(400, "nome tag vuoto")
    existing = db.query(models.StudentTag).filter(
        models.StudentTag.name == name
    ).first()
    if existing is not None:
        raise HTTPException(409, f"tag '{name}' gia esistente")
    t = models.StudentTag(name=name, description=payload.description)
    db.add(t)
    db.commit()
    db.refresh(t)
    return schemas.StudentTagOut(
        id=t.id, name=t.name, description=t.description, n_students=0,
    )


@tags_router.put("/{tid}", response_model=schemas.StudentTagOut)
def update_student_tag(tid: int, payload: schemas.StudentTagIn,
                       db: Session = Depends(get_db)):
    t = db.get(models.StudentTag, tid)
    if t is None:
        raise HTTPException(404, "tag non trovato")
    new_name = (payload.name or "").strip().lower()
    if not new_name:
        raise HTTPException(400, "nome tag vuoto")
    if new_name != t.name:
        clash = db.query(models.StudentTag).filter(
            models.StudentTag.name == new_name,
            models.StudentTag.id != tid,
        ).first()
        if clash is not None:
            raise HTTPException(409, f"tag '{new_name}' gia esistente")
        t.name = new_name
    t.description = payload.description
    db.commit()
    db.refresh(t)
    n = db.query(models.StudentTagAssignment).filter(
        models.StudentTagAssignment.tag_id == t.id
    ).count()
    return schemas.StudentTagOut(
        id=t.id, name=t.name, description=t.description, n_students=int(n),
    )


@tags_router.delete("/{tid}")
def delete_student_tag(tid: int, db: Session = Depends(get_db)):
    t = db.get(models.StudentTag, tid)
    if t is None:
        raise HTTPException(404, "tag non trovato")
    db.delete(t)  # ON DELETE CASCADE removes assignments
    db.commit()
    return {"ok": True}


