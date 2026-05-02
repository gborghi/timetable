"""Unified constraint creation + feasibility check + batch ops.

Endpoints:
  POST   /api/constraints                  unified creation dispatcher
  POST   /api/constraints/feasibility-check
  POST   /api/constraints/delete-batch     bulk delete by (kind, id) pairs

Per-row deletes go through /api/monitor/constraints/{kind}/{id} (already
exposed in monitor.py).

The creation dispatcher is a single polymorphic endpoint that the
frontend NewConstraintModal calls with a (scope, kind, level,
owner_id[, owner_id_2], ...) payload. Dispatches to:

  (teacher | class | classroom, matrix_slot)  -> *Unavailability
  (teacher | class | classroom, logical)      -> LogicalUnavailability
  (curriculum, logical)                       -> CurriculumLogicalConstraint
  (subject_room, room_pref)                   -> ClassroomSubjectPreference
  (teacher_room, room_pref)                   -> TeacherClassroomPreference
  (class, coteach)                            -> CoTeachingRule

The feasibility-check builds a minimal CP-SAT model + extracts an
unsatisfiable core via SufficientAssumptionsForInfeasibility().
See utils/feasibility.py.
"""
from __future__ import annotations

import json as _json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..db import get_db

router = APIRouter(prefix="/api/constraints", tags=["constraints"])


_DAYS = {1, 2, 3, 4, 5, 6}
_HOURS = {8, 9, 10, 11, 12, 13}


def _normalise_weight(level: str, weight: int | None) -> int:
    """Coerce `weight` to a sane SOFT-penalty value given the level.
    HARD/ENFORCED/ALLOWED ignore weight (we store 0).
    PREFERRED expects negative; SOFT expects positive.
    """
    if level in ("hard", "enforced", "allowed", "forbidden"):
        return 0
    w = int(weight if weight is not None else 100)
    if level == "preferred" and w > 0:
        return -abs(w)
    if level == "soft" and w < 0:
        return abs(w)
    return w


def _slot_label(day: int, hour: int) -> str:
    days = {1: "Lun", 2: "Mar", 3: "Mer", 4: "Gio",
            5: "Ven", 6: "Sab"}
    return f"{days.get(day, '?')}{hour}"


@router.post("", response_model=schemas.ConstraintCreateOut)
def create_constraint(payload: schemas.ConstraintCreateIn,
                       db: Session = Depends(get_db)):
    """Dispatch creation based on (scope, kind). Returns
    {ok, kind, id, scope, detail}."""
    scope = (payload.scope or "").lower()
    kind = (payload.kind or "").lower()
    level = (payload.level or "hard").lower()
    weight = _normalise_weight(level, payload.weight)

    # ----- matrix_slot ---------------------------------------------------
    if kind == "matrix_slot":
        if payload.day is None or payload.hour is None:
            raise HTTPException(400,
                "matrix_slot richiede day + hour")
        if int(payload.day) not in _DAYS or int(payload.hour) not in _HOURS:
            raise HTTPException(400, "day/hour fuori range")
        if level not in ("hard", "soft", "preferred", "enforced"):
            raise HTTPException(400,
                f"matrix_slot non supporta level={level!r}")
        if scope == "teacher":
            if payload.owner_id is None:
                raise HTTPException(400,
                    "matrix_slot scope=teacher richiede owner_id")
            t = db.get(models.Teacher, int(payload.owner_id))
            if t is None:
                raise HTTPException(404, "docente non trovato")
            existing = db.query(models.TeacherUnavailability).filter(
                models.TeacherUnavailability.teacher_id == t.id,
                models.TeacherUnavailability.day == int(payload.day),
                models.TeacherUnavailability.hour == int(payload.hour),
            ).first()
            if existing is not None:
                existing.state = level
                existing.soft_penalty = weight
                if payload.reason:
                    existing.reason = payload.reason
                row = existing
            else:
                row = models.TeacherUnavailability(
                    teacher_id=t.id,
                    day=int(payload.day), hour=int(payload.hour),
                    state=level, soft_penalty=weight,
                    reason=payload.reason,
                )
                db.add(row)
            db.commit()
            db.refresh(row)
            return {"ok": True, "kind": "teacher_cell", "id": row.id,
                    "scope": "docente",
                    "detail": _slot_label(row.day, row.hour)}
        if scope == "class":
            if payload.owner_id is None:
                raise HTTPException(400,
                    "matrix_slot scope=class richiede owner_id")
            c = db.get(models.SchoolClass, int(payload.owner_id))
            if c is None:
                raise HTTPException(404, "classe non trovata")
            existing = db.query(models.ClassUnavailability).filter(
                models.ClassUnavailability.class_id == c.id,
                models.ClassUnavailability.day == int(payload.day),
                models.ClassUnavailability.hour == int(payload.hour),
            ).first()
            if existing is not None:
                existing.state = level
                existing.soft_penalty = weight
                if payload.reason:
                    existing.reason = payload.reason
                row = existing
            else:
                row = models.ClassUnavailability(
                    class_id=c.id,
                    day=int(payload.day), hour=int(payload.hour),
                    state=level, soft_penalty=weight,
                    reason=payload.reason,
                )
                db.add(row)
            db.commit()
            db.refresh(row)
            return {"ok": True, "kind": "class_cell", "id": row.id,
                    "scope": "classe",
                    "detail": _slot_label(row.day, row.hour)}
        if scope == "classroom":
            if payload.owner_id is None:
                raise HTTPException(400,
                    "matrix_slot scope=classroom richiede owner_id")
            r = db.get(models.Classroom, int(payload.owner_id))
            if r is None:
                raise HTTPException(404, "aula non trovata")
            existing = db.query(models.ClassroomUnavailability).filter(
                models.ClassroomUnavailability.classroom_id == r.id,
                models.ClassroomUnavailability.day == int(payload.day),
                models.ClassroomUnavailability.hour == int(payload.hour),
            ).first()
            if existing is not None:
                existing.state = level
                existing.soft_penalty = weight
                if payload.reason:
                    existing.reason = payload.reason
                row = existing
            else:
                row = models.ClassroomUnavailability(
                    classroom_id=r.id,
                    day=int(payload.day), hour=int(payload.hour),
                    state=level, soft_penalty=weight,
                    reason=payload.reason,
                )
                db.add(row)
            db.commit()
            db.refresh(row)
            return {"ok": True, "kind": "room_cell", "id": row.id,
                    "scope": "aula",
                    "detail": _slot_label(row.day, row.hour)}
        raise HTTPException(400, f"matrix_slot scope={scope!r} non supportato")

    # ----- logical -------------------------------------------------------
    if kind == "logical":
        if not payload.expression or not payload.expression.strip():
            raise HTTPException(400, "logical richiede `expression`")
        from ..utils.logic_parser import parse_to_dnf, LogicError
        try:
            parsed = parse_to_dnf(payload.expression)
        except LogicError as e:
            raise HTTPException(400, f"sintassi non valida: {e}")
        is_hard = level in ("hard", "enforced")
        if scope in ("teacher", "class", "classroom"):
            entity_type = scope
            owner_model = {
                "teacher": models.Teacher,
                "class": models.SchoolClass,
                "classroom": models.Classroom,
            }[scope]
            if payload.owner_id is None:
                raise HTTPException(400,
                    f"logical scope={scope!r} richiede owner_id")
            o = db.get(owner_model, int(payload.owner_id))
            if o is None:
                raise HTTPException(404, "owner non trovato")
            row = models.LogicalUnavailability(
                entity_type=entity_type,
                entity_id=int(payload.owner_id),
                expression=payload.expression,
                parsed_dnf_json=_json.dumps(parsed.clauses),
                kind=level, is_hard=is_hard, soft_penalty=weight,
                label=payload.label or None,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            scope_label = {"teacher": "docente", "class": "classe",
                           "classroom": "aula"}[scope]
            return {"ok": True, "kind": f"logical_{scope}",
                    "id": row.id, "scope": scope_label,
                    "detail": payload.expression[:60]}
        if scope == "curriculum":
            if payload.owner_id is None:
                raise HTTPException(400,
                    "logical scope=curriculum richiede owner_id")
            cu = db.get(models.Curriculum, int(payload.owner_id))
            if cu is None:
                raise HTTPException(404, "curriculum non trovato")
            row = models.CurriculumLogicalConstraint(
                curriculum_id=cu.id,
                expression=payload.expression,
                parsed_dnf_json=_json.dumps(parsed.clauses),
                kind=level, is_hard=is_hard,
                soft_penalty=weight,
                label=payload.label or None,
                year_filter=int(payload.year_filter)
                            if payload.year_filter is not None else None,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return {"ok": True, "kind": "logical_curriculum",
                    "id": row.id, "scope": "indirizzo",
                    "detail": payload.expression[:60]}
        raise HTTPException(400, f"logical scope={scope!r} non supportato")

    # ----- room_pref -----------------------------------------------------
    if kind == "room_pref":
        if level not in ("allowed", "soft", "preferred", "forbidden",
                          "enforced"):
            raise HTTPException(400,
                f"room_pref level={level!r} non valido (usa allowed/soft/preferred/forbidden/enforced)")
        if scope == "subject_room":
            if (payload.owner_id is None) or not payload.subject:
                raise HTTPException(400,
                    "subject_room richiede owner_id (classroom_id) "
                    "+ subject")
            r = db.get(models.Classroom, int(payload.owner_id))
            if r is None:
                raise HTTPException(404, "aula non trovata")
            existing = db.query(models.ClassroomSubjectPreference).filter(
                models.ClassroomSubjectPreference.classroom_id == r.id,
                models.ClassroomSubjectPreference.subject == payload.subject,
            ).first()
            if existing is not None:
                existing.state = level
                existing.required = (level == "enforced")
                existing.weight = float(weight)
                row = existing
            else:
                row = models.ClassroomSubjectPreference(
                    classroom_id=r.id,
                    subject=payload.subject,
                    state=level,
                    required=(level == "enforced"),
                    weight=float(weight),
                )
                db.add(row)
            db.commit()
            db.refresh(row)
            return {"ok": True, "kind": "subject_room_pref",
                    "id": row.id, "scope": "materia/aula",
                    "detail": f"{payload.subject} <-> {r.name}"}
        if scope == "teacher_room":
            if payload.owner_id is None or payload.owner_id_2 is None:
                raise HTTPException(400,
                    "teacher_room richiede owner_id (teacher_id) "
                    "+ owner_id_2 (classroom_id)")
            t = db.get(models.Teacher, int(payload.owner_id))
            r = db.get(models.Classroom, int(payload.owner_id_2))
            if t is None or r is None:
                raise HTTPException(404, "docente o aula non trovati")
            existing = db.query(models.TeacherClassroomPreference).filter(
                models.TeacherClassroomPreference.teacher_id == t.id,
                models.TeacherClassroomPreference.classroom_id == r.id,
            ).first()
            if existing is not None:
                existing.state = level
                existing.weight = float(weight)
                row = existing
            else:
                row = models.TeacherClassroomPreference(
                    teacher_id=t.id, classroom_id=r.id,
                    state=level, weight=float(weight),
                )
                db.add(row)
            db.commit()
            db.refresh(row)
            return {"ok": True, "kind": "teacher_room_pref",
                    "id": row.id, "scope": "docente/aula",
                    "detail": f"{t.name} <-> {r.name}"}
        raise HTTPException(400, f"room_pref scope={scope!r} non supportato")

    # ----- coteach -------------------------------------------------------
    if kind == "coteach":
        if scope != "class":
            raise HTTPException(400,
                "coteach richiede scope=class")
        if payload.owner_id is None or not payload.subject:
            raise HTTPException(400,
                "coteach richiede owner_id (class_id) + subject")
        c = db.get(models.SchoolClass, int(payload.owner_id))
        if c is None:
            raise HTTPException(404, "classe non trovata")
        n = int(payload.n_teachers or 2)
        if n < 2:
            raise HTTPException(400, "coteach n_teachers >= 2")
        # Update existing or insert
        existing = db.query(models.CoTeachingRule).filter(
            models.CoTeachingRule.class_id == c.id,
            models.CoTeachingRule.subject == payload.subject,
        ).first()
        if existing is not None:
            existing.n_teachers = n
            existing.required = (level == "hard")
            existing.weight = float(weight) if weight is not None else 0.0
            existing.teacher_csv = payload.teacher_csv or None
            row = existing
        else:
            row = models.CoTeachingRule(
                class_id=c.id, subject=payload.subject,
                n_teachers=n,
                required=(level == "hard"),
                weight=float(weight) if weight is not None else 0.0,
                teacher_csv=payload.teacher_csv or None,
            )
            db.add(row)
        db.commit()
        db.refresh(row)
        return {"ok": True, "kind": "coteach", "id": row.id,
                "scope": "classe",
                "detail": f"{payload.subject}: {n} docenti"}

    raise HTTPException(400, f"kind sconosciuto: {kind!r}")


# ---------------------------------------------------------------------
# Feasibility check (MUS extraction)
# ---------------------------------------------------------------------


from pydantic import BaseModel as _BM


class FeasibilityCheckIn(_BM):
    time_limit_s: float = 30.0


@router.post("/feasibility-check")
def run_feasibility_check(payload: FeasibilityCheckIn | None = None,
                           db: Session = Depends(get_db)):
    """Run the HARD/ENFORCED-only feasibility analyzer + MUS extractor.
    Returns {feasible, cores, suggested_removal, ...} per
    utils/feasibility.feasibility_check."""
    from ..utils.feasibility import feasibility_check
    tlim = float(payload.time_limit_s) if payload else 30.0
    return feasibility_check(db, time_limit_s=tlim)


# ---------------------------------------------------------------------
# Batch delete
# ---------------------------------------------------------------------


class ConstraintDeleteBatchIn(_BM):
    """List of (kind, id) pairs to delete in one shot. Used by
    "Applica suggerimento" in the FeasibilityPanel."""
    items: list[dict]   # [{kind: str, id: int}, ...]


_DELETE_MODEL_FOR = {
    "teacher_cell": models.TeacherUnavailability,
    "class_cell": models.ClassUnavailability,
    "room_cell": models.ClassroomUnavailability,
    "logical_teacher": models.LogicalUnavailability,
    "logical_class": models.LogicalUnavailability,
    "logical_classroom": models.LogicalUnavailability,
    "logical_curriculum": models.CurriculumLogicalConstraint,
    "coteach": models.CoTeachingRule,
    "subject_room_pref": models.ClassroomSubjectPreference,
    "teacher_room_pref": models.TeacherClassroomPreference,
}


@router.post("/delete-batch")
def delete_constraints_batch(payload: ConstraintDeleteBatchIn,
                              db: Session = Depends(get_db)):
    """Bulk delete by (kind, id) pairs. Skips unknown kinds + missing
    ids; returns counts + skipped list."""
    n_ok = 0
    skipped: list[dict] = []
    for it in payload.items or []:
        kind = (it.get("kind") or "").lower()
        rid = int(it.get("id") or 0)
        Model = _DELETE_MODEL_FOR.get(kind)
        if Model is None or rid == 0:
            skipped.append({**it, "reason": "kind sconosciuto"})
            continue
        row = db.get(Model, rid)
        if row is None:
            skipped.append({**it, "reason": "non trovato"})
            continue
        db.delete(row)
        n_ok += 1
    db.commit()
    return {"ok": True, "deleted": n_ok, "skipped": skipped}
