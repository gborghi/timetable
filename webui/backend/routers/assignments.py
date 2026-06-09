"""Read + manual edit of prof->class assignments."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models, schemas, optimization
from ..db import get_db

router = APIRouter(prefix="/api/assignments", tags=["assignments"])


class _AssignmentRestoreItem(BaseModel):
    """One assignment snapshot to recreate (the shape list_assignments
    returns, ids dropped). Used by bulk/restore to power the UNDO of a
    bulk delete."""
    teacher_id: int
    class_id: int | None = None
    group_id: int | None = None
    subject: str
    hours: int = 0
    locked: bool = False
    coteach_group_id: int | None = None
    is_support: bool = False
    is_potenziamento: bool = False
    parallel_group_id: int | None = None


class _BulkRestoreIn(BaseModel):
    items: list[_AssignmentRestoreItem]


def _assignment_dict(a, t, c, g=None):
    """Shared serialization. `c` may be None for is_potenziamento or
    group-targeted rows. `g` is the StudyGroup for group-targeted rows."""
    return {
        "id": a.id,
        "teacher_id": a.teacher_id,
        "teacher_name": t.name,
        "class_id": a.class_id,
        "class_name": c.name if c else None,
        "group_id": a.group_id,
        "group_name": g.name if g else None,
        "subject": a.subject,
        "hours": a.hours,
        "locked": a.locked,
        # Task C1 flags:
        "coteach_group_id": a.coteach_group_id,
        "is_support": bool(a.is_support),
        "is_potenziamento": bool(a.is_potenziamento),
    }


@router.get("")
def list_assignments(db: Session = Depends(get_db)):
    """Return assignments with denormalized teacher/class/group names.
    Includes C1 flags: coteach_group_id, is_support,
    is_potenziamento, plus C3 group_id/group_name. Potenziamento rows
    have class_id=None; group-targeted rows have class_id=None and
    group_id=<id>."""
    teachers = {t.id: t for t in db.query(models.Teacher).all()}
    classes = {c.id: c for c in db.query(models.SchoolClass).all()}
    groups = {g.id: g for g in db.query(models.StudyGroup).all()}
    rows = db.query(models.Assignment).all()
    out = []
    for a in rows:
        t = teachers.get(a.teacher_id)
        if t is None:
            continue
        c = classes.get(a.class_id) if a.class_id is not None else None
        g = groups.get(a.group_id) if a.group_id is not None else None
        # Skip orphan rows (no class AND no group AND not potenziamento).
        if c is None and g is None and not a.is_potenziamento:
            continue
        out.append(_assignment_dict(a, t, c, g))
    return out


@router.get("/by-class")
def assignments_grouped_by_class(db: Session = Depends(get_db)):
    """Group: class -> [{subject, teacher, hours, locked, ...}, ...].
    Potenziamento rows are returned under the synthetic key
    '__potenziamento__'. Group-targeted (Task C3) rows are returned
    under '__group_<group_name>__' keys so the UI can show them in
    dedicated sections."""
    teachers = {t.id: t for t in db.query(models.Teacher).all()}
    classes = {c.id: c for c in db.query(models.SchoolClass).all()}
    groups = {g.id: g for g in db.query(models.StudyGroup).all()}
    out: dict[str, list[dict]] = {c.name: [] for c in classes.values()}
    out["__potenziamento__"] = []
    for a in db.query(models.Assignment).all():
        t = teachers.get(a.teacher_id)
        if t is None:
            continue
        c = classes.get(a.class_id) if a.class_id is not None else None
        g = groups.get(a.group_id) if a.group_id is not None else None
        if g is not None:
            key = f"__group_{g.name}__"
            out.setdefault(key, []).append({
                "id": a.id,
                "subject": a.subject,
                "teacher": t.name,
                "hours": a.hours,
                "locked": a.locked,
                "group_id": g.id,
                "group_name": g.name,
                "coteach_group_id": a.coteach_group_id,
                "is_support": bool(a.is_support),
            })
            continue
        if a.is_potenziamento or c is None:
            out["__potenziamento__"].append({
                "id": a.id,
                "subject": a.subject,
                "teacher": t.name,
                "hours": a.hours,
                "locked": a.locked,
                "is_potenziamento": True,
            })
            continue
        out.setdefault(c.name, []).append({
            "id": a.id,
            "subject": a.subject,
            "teacher": t.name,
            "hours": a.hours,
            "locked": a.locked,
            "coteach_group_id": a.coteach_group_id,
            "is_support": bool(a.is_support),
            "is_potenziamento": False,
        })
    return out


@router.put("/manual")
def manual_assignment(payload: schemas.ManualAssignmentIn,
                      db: Session = Depends(get_db)):
    ok, reason, new = optimization.manual_assignment(
        db, payload.class_name, payload.subject,
        payload.teacher_name, locked=payload.locked,
        target_kind=payload.target_kind,
        group_name=payload.group_name,
        hours=payload.hours,
    )
    out = {"accepted": ok, "reason": reason}
    if ok and new is not None:
        teacher = db.get(models.Teacher, new.teacher_id)
        sclass = (db.get(models.SchoolClass, new.class_id)
                  if new.class_id is not None else None)
        sgroup = (db.get(models.StudyGroup, new.group_id)
                  if new.group_id is not None else None)
        out["new_assignment"] = {
            "id": new.id,
            "teacher_id": new.teacher_id,
            "teacher_name": teacher.name if teacher else "?",
            "class_id": new.class_id,
            "class_name": sclass.name if sclass else None,
            "group_id": new.group_id,
            "group_name": sgroup.name if sgroup else None,
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


# ---------- Bulk operations ----------
#
# These endpoints accept a list of assignment ids and apply a single
# action across all of them in one DB transaction. Per-row failures
# are collected in `errors` so the UI can show a partial-success
# toast without rolling back the rows that did succeed.


@router.post("/bulk/delete", response_model=schemas.BulkAssignmentResultOut)
def bulk_delete_assignments(payload: schemas.BulkAssignmentIdsIn,
                            db: Session = Depends(get_db)):
    """Delete every Assignment whose id appears in `payload.ids`.
    Unknown ids are skipped (counted in n_skipped)."""
    n_applied = 0
    n_skipped = 0
    errors: list[str] = []
    for aid in payload.ids:
        a = db.get(models.Assignment, aid)
        if a is None:
            n_skipped += 1
            errors.append(f"id={aid}: cattedra inesistente")
            continue
        db.delete(a)
        n_applied += 1
    db.commit()
    return {
        "ok": n_applied > 0 or not payload.ids,
        "n_applied": n_applied,
        "n_skipped": n_skipped,
        "errors": errors,
    }


@router.post("/bulk/restore", response_model=schemas.BulkAssignmentResultOut)
def bulk_restore_assignments(payload: _BulkRestoreIn,
                             db: Session = Depends(get_db)):
    """Recreate assignments from snapshots (UNDO of a bulk delete). New
    rows get fresh ids; a snapshot whose teacher no longer exists is
    skipped. XOR(class_id, group_id) is the caller's responsibility (the
    snapshots come straight from list_assignments)."""
    n_applied = 0
    n_skipped = 0
    errors: list[str] = []
    for it in payload.items:
        if db.get(models.Teacher, it.teacher_id) is None:
            n_skipped += 1
            errors.append(f"teacher_id={it.teacher_id}: docente inesistente")
            continue
        db.add(models.Assignment(
            teacher_id=it.teacher_id, class_id=it.class_id,
            group_id=it.group_id, subject=it.subject, hours=it.hours,
            locked=it.locked, coteach_group_id=it.coteach_group_id,
            is_support=it.is_support, is_potenziamento=it.is_potenziamento,
            parallel_group_id=it.parallel_group_id))
        n_applied += 1
    db.commit()
    return {
        "ok": n_applied > 0 or not payload.items,
        "n_applied": n_applied,
        "n_skipped": n_skipped,
        "errors": errors,
    }


@router.post("/bulk/lock", response_model=schemas.BulkAssignmentResultOut)
def bulk_lock_assignments(payload: schemas.BulkAssignmentLockIn,
                          db: Session = Depends(get_db)):
    """Set `locked=payload.locked` on every Assignment in
    `payload.ids`. Useful to pin or unpin a batch of cattedre at
    once before launching Phase A so the solver respects the
    user's choices."""
    n_applied = 0
    n_skipped = 0
    errors: list[str] = []
    for aid in payload.ids:
        a = db.get(models.Assignment, aid)
        if a is None:
            n_skipped += 1
            errors.append(f"id={aid}: cattedra inesistente")
            continue
        a.locked = bool(payload.locked)
        n_applied += 1
    db.commit()
    return {
        "ok": True,
        "n_applied": n_applied,
        "n_skipped": n_skipped,
        "errors": errors,
    }


@router.post("/bulk/change-teacher",
             response_model=schemas.BulkAssignmentResultOut)
def bulk_change_teacher(payload: schemas.BulkAssignmentChangeTeacherIn,
                         db: Session = Depends(get_db)):
    """Reassign every selected cattedra to `payload.teacher_name`.
    The new teacher must be qualified for the row's subject (i.e.
    have a TeacherSubject row); rows where this fails are reported
    in `errors` and skipped, leaving the existing teacher in place."""
    new_t = db.query(models.Teacher).filter(
        models.Teacher.name == payload.teacher_name
    ).first()
    if new_t is None:
        raise HTTPException(404, f"docente '{payload.teacher_name}' "
                                  "non trovato")
    qualified_subjects = {
        ts.subject for ts in db.query(models.TeacherSubject)
        .filter(models.TeacherSubject.teacher_id == new_t.id).all()
    }
    n_applied = 0
    n_skipped = 0
    errors: list[str] = []
    for aid in payload.ids:
        a = db.get(models.Assignment, aid)
        if a is None:
            n_skipped += 1
            errors.append(f"id={aid}: cattedra inesistente")
            continue
        if a.subject not in qualified_subjects:
            n_skipped += 1
            errors.append(f"id={aid}: '{payload.teacher_name}' non e' "
                          f"qualificato per {a.subject}")
            continue
        a.teacher_id = new_t.id
        n_applied += 1
    db.commit()
    return {
        "ok": True,
        "n_applied": n_applied,
        "n_skipped": n_skipped,
        "errors": errors,
    }


@router.post("/bulk/set-flag",
             response_model=schemas.BulkAssignmentResultOut)
def bulk_set_flag(payload: schemas.BulkAssignmentSetFlagIn,
                  db: Session = Depends(get_db)):
    """Toggle `is_potenziamento` or `is_support` on every selected
    row. Other flag names are rejected with a 400 to prevent
    arbitrary attribute writes."""
    if payload.flag not in ("is_potenziamento", "is_support"):
        raise HTTPException(
            400, f"flag '{payload.flag}' non supportato; "
                 "solo is_potenziamento, is_support")
    n_applied = 0
    n_skipped = 0
    errors: list[str] = []
    for aid in payload.ids:
        a = db.get(models.Assignment, aid)
        if a is None:
            n_skipped += 1
            errors.append(f"id={aid}: cattedra inesistente")
            continue
        setattr(a, payload.flag, bool(payload.value))
        n_applied += 1
    db.commit()
    return {
        "ok": True,
        "n_applied": n_applied,
        "n_skipped": n_skipped,
        "errors": errors,
    }


def _teacher_display(t: models.Teacher) -> str:
    if t.nickname:
        return t.nickname
    if t.last_name and t.first_name:
        return f"{t.last_name} {t.first_name}"
    return t.name


@router.get("/teachers-for-subject")
def teachers_for_subject(subject: str,
                         exclude_teacher: str | None = None,
                         db: Session = Depends(get_db)):
    """Returns the list of teachers qualified to teach `subject` with
    their current cattedra load. The frontend uses this to populate the
    'cambia' dropdown and show a per-teacher load badge.

    Each row has: id, name, display, group (classe di concorso),
    max_hours, assigned_hours (sum of hours over their assignments
    excluding this exact (class, subject) slot if exclude_teacher is set
    to that very teacher), available_hours, would_exceed (predicted true
    if this teacher accepts the assignment delta).
    """
    teacher_ids_for_subj: set[int] = set()
    for ts in db.query(models.TeacherSubject).filter(
        models.TeacherSubject.subject == subject
    ).all():
        teacher_ids_for_subj.add(ts.teacher_id)
    teachers = db.query(models.Teacher).filter(
        models.Teacher.id.in_(teacher_ids_for_subj)
    ).order_by(models.Teacher.name).all()
    # current load per teacher
    load: dict[int, int] = {}
    for a in db.query(models.Assignment).all():
        load[a.teacher_id] = load.get(a.teacher_id, 0) + int(a.hours)
    out: list[dict] = []
    for t in teachers:
        used = load.get(t.id, 0)
        out.append({
            "id": t.id,
            "name": t.name,
            "display": _teacher_display(t),
            "group": t.group,
            "max_hours": int(t.max_hours or 0),
            "assigned_hours": used,
            "available_hours": int(t.max_hours or 0) - used,
            "is_over": used > int(t.max_hours or 0),
        })
    return out


@router.get("/loads")
def teacher_loads(db: Session = Depends(get_db)):
    """Summary of every teacher's cattedra load. Used by the
    /assignments page warning panel to flag over-allocation
    (assigned > max) and under-allocation (assigned < max).

    Returns the list (sorted by display name) of:
      {id, name, display, group, max_hours, assigned_hours,
       delta = assigned - max, status = ok | over | under }
    plus aggregate counts.
    """
    teachers = db.query(models.Teacher).order_by(models.Teacher.name).all()
    load: dict[int, int] = {}
    for a in db.query(models.Assignment).all():
        load[a.teacher_id] = load.get(a.teacher_id, 0) + int(a.hours)
    rows = []
    n_over = n_under = 0
    for t in teachers:
        used = load.get(t.id, 0)
        mx = int(t.max_hours or 0)
        delta = used - mx
        if delta > 0:
            status = "over"
            n_over += 1
        elif delta < 0 and used > 0:
            status = "under"
            n_under += 1
        elif used == 0 and mx > 0:
            status = "empty"
            n_under += 1
        else:
            status = "ok"
        rows.append({
            "id": t.id,
            "name": t.name,
            "display": _teacher_display(t),
            "group": t.group,
            "max_hours": mx,
            "assigned_hours": used,
            "delta": delta,
            "status": status,
        })
    return {
        "teachers": rows,
        "n_over": n_over,
        "n_under": n_under,
        "n_total": len(rows),
    }
