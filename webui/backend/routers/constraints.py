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
            # NB: LogicalUnavailability has no `label` column (only the
            # curriculum-scoped variant does); silently drop it here so
            # callers passing a description don't 500.
            row = models.LogicalUnavailability(
                entity_type=entity_type,
                entity_id=int(payload.owner_id),
                expression=payload.expression,
                parsed_dnf_json=_json.dumps(parsed.clauses),
                kind=level, is_hard=is_hard, soft_penalty=weight,
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


# ---------------------------------------------------------------------
# Apply-suggestion / revert / history (FeasibilityPanel actions)
# ---------------------------------------------------------------------


def _logical_owner_label(db: Session, row) -> str:
    """Best-effort human label for a Logical/Curriculum constraint."""
    if isinstance(row, models.CurriculumLogicalConstraint):
        cur = db.query(models.Curriculum).filter_by(
            id=row.curriculum_id).first()
        return f"curriculum {cur.name if cur else row.curriculum_id}"
    # LogicalUnavailability: scope is teacher/class/classroom
    scope = getattr(row, "scope", None)
    oid = getattr(row, "owner_id", None)
    if scope == "teacher":
        t = db.query(models.Teacher).filter_by(id=oid).first()
        if t:
            return (t.nickname
                    or (f"{t.last_name or ''} {t.first_name or ''}".strip())
                    or t.name or f"teacher#{oid}")
    if scope == "class":
        c = db.query(models.SchoolClass).filter_by(id=oid).first()
        if c:
            return c.name or f"class#{oid}"
    if scope == "classroom":
        r = db.query(models.Classroom).filter_by(id=oid).first()
        if r:
            return r.name or f"classroom#{oid}"
    return f"{scope}#{oid}"


def _snapshot_logical_row(row) -> dict:
    """Capture the mutable fields of a logical/curriculum constraint
    so a future 'restore' can put them back."""
    snap = {}
    for f in ("level", "expression", "soft_penalty", "weight",
              "is_hard", "kind", "enabled", "scope", "owner_id"):
        if hasattr(row, f):
            v = getattr(row, f)
            if v is not None:
                snap[f] = v
    return snap


class ApplySuggestionIn(_BM):
    """Body for /api/constraints/apply-suggestion.

    `action` is one of:
      - 'remove'   -> hard delete from DB. Reversible only via the
                       `before_json` snapshot (re-create the row).
      - 'soften'   -> turn HARD/ENFORCED into SOFT with the given
                       `weight` (default 100). Only meaningful for
                       logical constraints.
      - 'disable'  -> set enabled=False (if the row has that field),
                       otherwise lower level to ALLOWED. Reversible
                       by 'enable' / 'restore'.
      - 'edit'     -> apply the new fields from `params` (e.g.
                       expression, level, weight). The caller is
                       responsible for sending a sane payload.

    `targets` is a list of `{kind, id}` pairs. The action is applied
    atomically across all of them; partial failures roll back the
    whole batch.
    """
    action: str
    targets: list[dict]
    params: dict | None = None
    note: str | None = None


def _apply_one(db: Session, target: dict, action: str,
               params: dict | None) -> dict:
    """Apply a single intervention. Returns
    {kind, id, before, after, ok, error}."""
    out = {"kind": target.get("kind"), "id": target.get("id"),
           "before": None, "after": None, "ok": False, "error": None}
    kind = target.get("kind")
    rid = target.get("id")
    Model = _DELETE_MODEL_FOR.get(kind)
    if Model is None:
        out["error"] = f"unknown kind {kind!r}"
        return out
    row = db.query(Model).filter_by(id=rid).first()
    if row is None:
        out["error"] = f"{kind} #{rid} not found"
        return out
    before = _snapshot_logical_row(row)
    out["before"] = before
    out["owner_label"] = _logical_owner_label(db, row)
    if action == "remove":
        db.delete(row)
        out["ok"] = True
        return out
    if action == "soften":
        if not hasattr(row, "level"):
            out["error"] = ("soften: questo tipo di vincolo non ha "
                             "un attributo 'level'")
            return out
        new_weight = int((params or {}).get("weight", 100))
        row.level = "soft"
        if hasattr(row, "soft_penalty"):
            row.soft_penalty = abs(new_weight)
        if hasattr(row, "weight"):
            row.weight = abs(new_weight)
        if hasattr(row, "is_hard"):
            row.is_hard = False
        out["after"] = _snapshot_logical_row(row)
        out["ok"] = True
        return out
    if action == "disable":
        if hasattr(row, "enabled"):
            row.enabled = False
        elif hasattr(row, "level"):
            row.level = "allowed"
        else:
            out["error"] = ("disable: questo tipo di vincolo non ha "
                             "un campo 'enabled' ne' 'level'")
            return out
        out["after"] = _snapshot_logical_row(row)
        out["ok"] = True
        return out
    if action == "enable":
        if hasattr(row, "enabled"):
            row.enabled = True
            out["after"] = _snapshot_logical_row(row)
            out["ok"] = True
            return out
        out["error"] = "enable: il vincolo non ha campo 'enabled'"
        return out
    if action == "edit":
        p = params or {}
        for f in ("level", "expression", "soft_penalty", "weight",
                  "is_hard"):
            if f in p and hasattr(row, f):
                setattr(row, f, p[f])
        out["after"] = _snapshot_logical_row(row)
        out["ok"] = True
        return out
    out["error"] = f"unknown action {action!r}"
    return out


@router.post("/apply-suggestion")
def apply_suggestion(payload: ApplySuggestionIn,
                      db: Session = Depends(get_db)):
    """Apply a suggested action (remove / soften / disable / enable /
    edit) on a list of constraints, atomically.

    Each successful intervention writes a `ConstraintIntervention`
    row capturing before/after JSON, the owner label, the action and
    an optional note. The id of that row is returned in the response,
    so the caller can later /revert/{intervention_id}.
    """
    action = payload.action
    if action not in ("remove", "soften", "disable", "enable", "edit"):
        raise HTTPException(400, f"unknown action {action!r}")

    results = []
    intervention_ids = []
    try:
        for tgt in payload.targets:
            r = _apply_one(db, tgt, action, payload.params)
            if not r["ok"]:
                # roll back the whole batch on first error
                db.rollback()
                raise HTTPException(
                    400,
                    f"intervento fallito su {tgt}: {r['error']}",
                )
            iv = models.ConstraintIntervention(
                action=action,
                target_kind=r["kind"],
                target_id=r["id"],
                target_owner_label=r.get("owner_label"),
                before_json=_json.dumps(r["before"]) if r["before"] else None,
                after_json=_json.dumps(r["after"]) if r.get("after") else None,
                note=payload.note,
            )
            db.add(iv)
            db.flush()    # populate iv.id
            intervention_ids.append(iv.id)
            results.append({**r, "intervention_id": iv.id})
        db.commit()
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"errore interno: {e}")
    return {
        "ok": True,
        "action": action,
        "n_applied": len(results),
        "intervention_ids": intervention_ids,
        "results": results,
    }


class RevertIn(_BM):
    """Revert one or more interventions by their intervention_id."""
    intervention_ids: list[int]


@router.post("/revert")
def revert_interventions(payload: RevertIn,
                          db: Session = Depends(get_db)):
    """Revert previously-applied interventions in reverse order. For
    'remove' actions the row is re-created from `before_json` (with
    a NEW id, since the old one is gone); the new id is reported. For
    'soften' / 'disable' / 'edit' the original field values are
    restored. Each revert writes its own ConstraintIntervention with
    action='restore' and links back via `reverted_by_id`.
    """
    iv_rows = (db.query(models.ConstraintIntervention)
                 .filter(
                     models.ConstraintIntervention.id.in_(
                         payload.intervention_ids))
                 .order_by(models.ConstraintIntervention.id.desc())
                 .all())
    found_ids = {iv.id for iv in iv_rows}
    missing = [i for i in payload.intervention_ids if i not in found_ids]
    if missing:
        raise HTTPException(404,
                             f"interventi non trovati: {missing}")
    out_results = []
    try:
        for iv in iv_rows:
            if iv.reverted:
                out_results.append({
                    "intervention_id": iv.id, "ok": False,
                    "error": "gia' revertito"})
                continue
            try:
                before = _json.loads(iv.before_json or "{}")
            except Exception:
                before = {}
            Model = _DELETE_MODEL_FOR.get(iv.target_kind)
            if Model is None:
                out_results.append({
                    "intervention_id": iv.id, "ok": False,
                    "error": f"unknown kind {iv.target_kind}"})
                continue
            if iv.action == "remove":
                # Re-create the row from before_json. New id.
                new_row = Model(**{k: v for k, v in before.items()
                                    if hasattr(Model, k)})
                db.add(new_row)
                db.flush()
                new_id = new_row.id
                out_results.append({
                    "intervention_id": iv.id, "ok": True,
                    "restored_kind": iv.target_kind,
                    "restored_id": new_id,
                    "note": "row re-created with new id"})
            else:
                row = db.query(Model).filter_by(
                    id=iv.target_id).first()
                if row is None:
                    out_results.append({
                        "intervention_id": iv.id, "ok": False,
                        "error": (f"{iv.target_kind} "
                                   f"#{iv.target_id} non esiste piu'"
                                   " (puoi ricrearlo via remove revert)")})
                    continue
                for f, v in before.items():
                    if hasattr(row, f):
                        setattr(row, f, v)
                out_results.append({
                    "intervention_id": iv.id, "ok": True,
                    "restored_kind": iv.target_kind,
                    "restored_id": iv.target_id})
            iv.reverted = True
            restore_iv = models.ConstraintIntervention(
                action="restore",
                target_kind=iv.target_kind,
                target_id=iv.target_id,
                target_owner_label=iv.target_owner_label,
                before_json=iv.after_json,
                after_json=iv.before_json,
                note=f"revert of intervention #{iv.id}",
            )
            db.add(restore_iv)
            db.flush()
            iv.reverted_by_id = restore_iv.id
        db.commit()
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"errore interno: {e}")
    return {"ok": True, "n_reverted": len(out_results),
            "results": out_results}


@router.get("/interventions")
def list_interventions(limit: int = 100,
                        db: Session = Depends(get_db)):
    """Audit history of constraint interventions. Most recent first."""
    rows = (db.query(models.ConstraintIntervention)
              .order_by(models.ConstraintIntervention.id.desc())
              .limit(limit).all())
    out = []
    for r in rows:
        try:
            before = _json.loads(r.before_json) if r.before_json else None
        except Exception:
            before = None
        try:
            after = _json.loads(r.after_json) if r.after_json else None
        except Exception:
            after = None
        out.append({
            "id": r.id,
            "timestamp": (r.timestamp.isoformat() + "Z"
                          if r.timestamp else None),
            "action": r.action,
            "target_kind": r.target_kind,
            "target_id": r.target_id,
            "target_owner_label": r.target_owner_label,
            "before": before,
            "after": after,
            "reverted": bool(r.reverted),
            "reverted_by_id": r.reverted_by_id,
            "note": r.note,
        })
    return out


# ---------------------------------------------------------------------
# General-purpose DSL constraints
# ---------------------------------------------------------------------


@router.post("/general/validate",
             response_model=schemas.GeneralConstraintValidateOut)
def validate_general(payload: schemas.GeneralConstraintIn):
    """Parse + statically validate the DSL expression. Used by the
    frontend editor (debounced) to surface errors as the user types."""
    from ..utils.general_dsl import parse, validate, DSLError
    try:
        tree = parse(payload.expression)
    except DSLError as e:
        return {"ok": False, "errors": [str(e)], "warnings": [], "n_atoms": 0}
    res = validate(tree)
    return {"ok": res.ok, "errors": res.errors,
            "warnings": res.warnings, "n_atoms": res.n_atoms}


@router.get("/general", response_model=list[schemas.GeneralConstraintOut])
def list_general(scope: str | None = None,
                  owner_id: int | None = None,
                  db: Session = Depends(get_db)):
    q = db.query(models.GeneralConstraint)
    if scope:
        q = q.filter(models.GeneralConstraint.scope == scope)
    if owner_id is not None:
        q = q.filter(models.GeneralConstraint.owner_id == owner_id)
    return q.order_by(models.GeneralConstraint.id.desc()).all()


@router.post("/general", response_model=schemas.GeneralConstraintOut)
def create_general(payload: schemas.GeneralConstraintIn,
                    db: Session = Depends(get_db)):
    from ..utils.general_dsl import parse, validate, DSLError
    import json as _json
    try:
        tree = parse(payload.expression)
    except DSLError as e:
        raise HTTPException(400, f"sintassi non valida: {e}")
    res = validate(tree)
    if not res.ok:
        raise HTTPException(400, "validazione: " + "; ".join(res.errors))
    # Normalise weight per level (same convention as elsewhere).
    weight = int(payload.weight or 100)
    if payload.level == "preferred" and weight > 0:
        weight = -weight
    if payload.level == "soft" and weight < 0:
        weight = -weight
    if payload.level in ("hard", "enforced"):
        weight = 0
    row = models.GeneralConstraint(
        expression=payload.expression,
        label=payload.label,
        level=payload.level,
        weight=weight,
        scope=payload.scope,
        owner_id=payload.owner_id,
        # We don't actually serialise the AST to JSON (it's recursive
        # with dataclasses); we re-parse on evaluation. Faster and
        # avoids a JSON round-trip headache.
        parsed_ast_json=None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.put("/general/{cid}", response_model=schemas.GeneralConstraintOut)
def update_general(cid: int, payload: schemas.GeneralConstraintIn,
                    db: Session = Depends(get_db)):
    from ..utils.general_dsl import parse, validate, DSLError
    row = db.get(models.GeneralConstraint, cid)
    if row is None:
        raise HTTPException(404, "constraint non trovato")
    try:
        parse(payload.expression)
    except DSLError as e:
        raise HTTPException(400, f"sintassi non valida: {e}")
    weight = int(payload.weight or 100)
    if payload.level == "preferred" and weight > 0:
        weight = -weight
    if payload.level == "soft" and weight < 0:
        weight = -weight
    if payload.level in ("hard", "enforced"):
        weight = 0
    row.expression = payload.expression
    row.label = payload.label
    row.level = payload.level
    row.weight = weight
    row.scope = payload.scope
    row.owner_id = payload.owner_id
    db.commit()
    db.refresh(row)
    return row


@router.delete("/general/{cid}")
def delete_general(cid: int, db: Session = Depends(get_db)):
    row = db.get(models.GeneralConstraint, cid)
    if row is None:
        raise HTTPException(404, "constraint non trovato")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("/search")
def search_constraints_endpoint(
    entity_type: str | None = None,
    entity_id: int | None = None,
    text: str | None = None,
    levels: str | None = None,   # CSV: hard,soft,...
    kinds: str | None = None,    # CSV: teacher_cell,logical_teacher,general_dsl,...
    db: Session = Depends(get_db),
):
    """Cross-source constraint search. Finds every saved constraint
    that *mentions* the given entity, regardless of where it was
    created. Used by the "Ricerca avanzata" panel in /constraints.

    Filters (all optional, ANDed):
      - entity_type / entity_id : exact (type, id) mention check
      - text                    : free-text substring (detail /
                                  expression / owner_name)
      - levels                  : CSV of levels to keep
      - kinds                   : CSV of kinds to keep

    `entity_type` valid values:
      teacher | class | classroom | subject | curriculum | group
    """
    from ..utils.constraint_search import search_constraints
    lvs = [s.strip() for s in (levels or "").split(",") if s.strip()]
    ks = [s.strip() for s in (kinds or "").split(",") if s.strip()]
    return search_constraints(
        db,
        entity_type=entity_type,
        entity_id=int(entity_id) if entity_id is not None else None,
        text=text,
        levels=lvs or None,
        kinds=ks or None,
    )


@router.post("/general/check-all")
def check_all_general(db: Session = Depends(get_db)):
    """Evaluate every General DSL constraint against the current
    active solution snapshot. Returns a list of HARD violations and
    the cumulative SOFT penalty contribution."""
    from ..utils.general_dsl import (
        parse, evaluate_safe, build_world, DSLError,
    )
    world = build_world(db)
    rows = db.query(models.GeneralConstraint).all()
    hard_violations: list[dict] = []
    soft_penalty = 0
    soft_violations: list[dict] = []
    for row in rows:
        try:
            tree = parse(row.expression)
        except DSLError as e:
            hard_violations.append({
                "id": row.id,
                "label": row.label,
                "expression": row.expression,
                "level": row.level,
                "scope": row.scope,
                "owner_id": row.owner_id,
                "error": f"parse error: {e}",
            })
            continue
        ok, err = evaluate_safe(tree, world)
        if err:
            hard_violations.append({
                "id": row.id, "label": row.label,
                "expression": row.expression,
                "level": row.level, "scope": row.scope,
                "owner_id": row.owner_id,
                "error": f"eval error: {err}",
            })
            continue
        if not ok:
            entry = {
                "id": row.id, "label": row.label,
                "expression": row.expression,
                "level": row.level, "scope": row.scope,
                "owner_id": row.owner_id,
            }
            if row.level in ("hard", "enforced"):
                hard_violations.append(entry)
            elif row.level == "soft":
                soft_penalty += int(row.weight)
                soft_violations.append(entry)
            elif row.level == "preferred":
                # PREFERRED violated -> no penalty (just no bonus)
                pass
        else:
            if row.level == "preferred" and row.weight < 0:
                soft_penalty += int(row.weight)   # bonus
    return {
        "n_constraints": len(rows),
        "hard_violations": hard_violations,
        "soft_violations": soft_violations,
        "soft_penalty": soft_penalty,
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
