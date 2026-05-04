"""Read + manual edit of prof->class assignments."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, optimization
from ..db import get_db

router = APIRouter(prefix="/api/assignments", tags=["assignments"])


def _assignment_dict(a, t, c):
    """Shared serialization. `c` may be None for is_potenziamento rows."""
    return {
        "id": a.id,
        "teacher_id": a.teacher_id,
        "teacher_name": t.name,
        "class_id": a.class_id,
        "class_name": c.name if c else None,
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
    """Return assignments with denormalized teacher/class names.
    Includes Task C1 flags: coteach_group_id, is_support,
    is_potenziamento. Potenziamento rows have class_id=None and
    class_name=None."""
    teachers = {t.id: t for t in db.query(models.Teacher).all()}
    classes = {c.id: c for c in db.query(models.SchoolClass).all()}
    rows = db.query(models.Assignment).all()
    out = []
    for a in rows:
        t = teachers.get(a.teacher_id)
        if t is None:
            continue
        c = classes.get(a.class_id) if a.class_id is not None else None
        # Skip rows with missing class UNLESS this is potenziamento
        # (where class_id is intentionally NULL).
        if c is None and not a.is_potenziamento:
            continue
        out.append(_assignment_dict(a, t, c))
    return out


@router.get("/by-class")
def assignments_grouped_by_class(db: Session = Depends(get_db)):
    """Group: class -> [{subject, teacher, hours, locked, ...}, ...].
    Potenziamento rows are returned under the synthetic key
    '__potenziamento__' so the UI can show them in a dedicated
    section."""
    teachers = {t.id: t for t in db.query(models.Teacher).all()}
    classes = {c.id: c for c in db.query(models.SchoolClass).all()}
    out: dict[str, list[dict]] = {c.name: [] for c in classes.values()}
    out["__potenziamento__"] = []
    for a in db.query(models.Assignment).all():
        t = teachers.get(a.teacher_id)
        if t is None:
            continue
        c = classes.get(a.class_id) if a.class_id is not None else None
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
