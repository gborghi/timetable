"""Constraint introspection: find every saved constraint (matrix
unavailability, logical unavailability, room/teacher prefs, coteach,
curriculum logical, GENERAL DSL) that mentions a specific entity --
no matter where it was created.

We don't need a full unified DSL parser for this; we just walk every
constraint source and extract two pieces of information:

  - structured_mentions: entity references resolvable from the
                         row's owner_id / FK columns (always
                         accurate)
  - text_mentions       : entity names that appear inside the
                         expression text (best-effort, regex-based)

Combined into a `mentions` set per constraint. The search endpoint
filters by `(entity_type, entity_id)` -> any constraint whose
mentions contain that pair is returned.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

from sqlalchemy.orm import Session

from .. import models


def _teacher_display(t: models.Teacher) -> str:
    if t.nickname:
        return t.nickname
    if t.last_name and t.first_name:
        return f"{t.last_name} {t.first_name}"
    return t.name


def _build_name_index(db: Session) -> dict[str, list[tuple[str, int, str]]]:
    """Build a `lower(name) -> [(entity_type, id, display_name)]`
    map covering every entity the user can mention in a DSL string."""
    out: dict[str, list[tuple[str, int, str]]] = {}

    def _add(name: str, et: str, eid: int, display: str):
        if not name:
            return
        out.setdefault(name.lower(), []).append((et, eid, display))

    for t in db.query(models.Teacher).all():
        d = _teacher_display(t)
        _add(t.name, "teacher", t.id, d)
        if t.last_name:
            _add(t.last_name, "teacher", t.id, d)
        if t.nickname:
            _add(t.nickname, "teacher", t.id, d)
    for c in db.query(models.SchoolClass).all():
        _add(c.name, "class", c.id, c.name)
        if c.nickname:
            _add(c.nickname, "class", c.id, c.name)
    for r in db.query(models.Classroom).all():
        _add(r.name, "classroom", r.id, r.name)
    for s in db.query(models.Subject).all():
        _add(s.name, "subject", s.id, s.name)
    for cu in db.query(models.Curriculum).all():
        _add(cu.code, "curriculum", cu.id, cu.name or cu.code)
        _add(cu.name, "curriculum", cu.id, cu.name or cu.code)
    for g in db.query(models.StudyGroup).all():
        _add(g.name, "group", g.id, g.name)
    return out


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def _extract_text_mentions(text: str,
                            name_index: dict
                            ) -> set[tuple[str, int]]:
    """Scan free text (an expression) for tokens that match known
    entity names. Returns a set of (entity_type, id) tuples. Best-
    effort: ambiguous tokens (e.g. "1A" if both a class name and a
    subject name) match all candidates."""
    out: set[tuple[str, int]] = set()
    for tok in _TOKEN_RE.findall(text or ""):
        for et, eid, _disp in name_index.get(tok.lower(), []):
            out.add((et, eid))
    return out


def _scope_to_origin(scope: str) -> str:
    return {
        "docente": "teacher", "classe": "class", "aula": "classroom",
        "indirizzo": "curriculum", "materia/aula": "subject_room",
        "docente/aula": "teacher_room",
        "global": "general",
    }.get(scope or "", scope or "")


def _slot_label(d: int, h: int) -> str:
    days = {1: "Lun", 2: "Mar", 3: "Mer", 4: "Gio",
            5: "Ven", 6: "Sab"}
    return f"{days.get(d, '?')}{h}"


def list_all_constraints_with_mentions(db: Session) -> list[dict]:
    """Iterate every constraint source (matrix cells, logical
    unavailabilities, classroom/teacher prefs, coteach, curriculum
    logical, GeneralConstraint) and return a flat list of dicts
    with a `mentions` set populated from owner_id/FK + text
    extraction.
    """
    teachers = {t.id: t for t in db.query(models.Teacher).all()}
    classes = {c.id: c for c in db.query(models.SchoolClass).all()}
    rooms = {r.id: r for r in db.query(models.Classroom).all()}
    curr_by_id = {c.id: c for c in db.query(models.Curriculum).all()}
    name_index = _build_name_index(db)

    out: list[dict] = []

    # Matrix cells: teacher / class / classroom unavailability
    for u in db.query(models.TeacherUnavailability).all():
        t = teachers.get(u.teacher_id)
        if t is None:
            continue
        out.append({
            "kind": "teacher_cell", "id": u.id,
            "scope": "docente",
            "owner_id": t.id,
            "owner_name": _teacher_display(t),
            "level": u.state, "weight": int(u.soft_penalty or 0),
            "detail": _slot_label(u.day, u.hour),
            "expression": "",
            "origin": "teacher",
            "mentions": {("teacher", t.id)},
        })
    for u in db.query(models.ClassUnavailability).all():
        c = classes.get(u.class_id)
        if c is None:
            continue
        out.append({
            "kind": "class_cell", "id": u.id,
            "scope": "classe",
            "owner_id": c.id, "owner_name": c.name,
            "level": u.state, "weight": int(u.soft_penalty or 0),
            "detail": _slot_label(u.day, u.hour),
            "expression": "",
            "origin": "class",
            "mentions": {("class", c.id)},
        })
    for u in db.query(models.ClassroomUnavailability).all():
        r = rooms.get(u.classroom_id)
        if r is None:
            continue
        out.append({
            "kind": "room_cell", "id": u.id,
            "scope": "aula",
            "owner_id": r.id, "owner_name": r.name,
            "level": u.state, "weight": int(u.soft_penalty or 0),
            "detail": _slot_label(u.day, u.hour),
            "expression": "",
            "origin": "classroom",
            "mentions": {("classroom", r.id)},
        })

    # Logical (teacher/class/classroom)
    for r in db.query(models.LogicalUnavailability).all():
        owner_name = ""
        owner_id = r.entity_id
        scope_label = {"teacher": "docente", "class": "classe",
                       "classroom": "aula"}.get(r.entity_type, r.entity_type)
        if r.entity_type == "teacher":
            t = teachers.get(r.entity_id)
            if t: owner_name = _teacher_display(t)
        elif r.entity_type == "class":
            c = classes.get(r.entity_id)
            if c: owner_name = c.name
        elif r.entity_type == "classroom":
            cr = rooms.get(r.entity_id)
            if cr: owner_name = cr.name
        mentions = {(r.entity_type, owner_id)}
        mentions |= _extract_text_mentions(r.expression or "", name_index)
        out.append({
            "kind": f"logical_{r.entity_type}", "id": r.id,
            "scope": scope_label,
            "owner_id": owner_id, "owner_name": owner_name or f"#{owner_id}",
            "level": r.kind or ("hard" if r.is_hard else "soft"),
            "weight": int(r.soft_penalty or 0),
            "detail": (r.label + ": " if r.label else "") + (r.expression or ""),
            "expression": r.expression or "",
            "origin": r.entity_type,
            "mentions": mentions,
        })

    # Curriculum logical
    for r in db.query(models.CurriculumLogicalConstraint).all():
        cu = curr_by_id.get(r.curriculum_id)
        owner_name = (cu.name or cu.code) if cu else f"#{r.curriculum_id}"
        mentions = {("curriculum", r.curriculum_id)}
        mentions |= _extract_text_mentions(r.expression or "", name_index)
        out.append({
            "kind": "logical_curriculum", "id": r.id,
            "scope": "indirizzo",
            "owner_id": r.curriculum_id, "owner_name": owner_name,
            "level": r.kind or ("hard" if r.is_hard else "soft"),
            "weight": int(r.soft_penalty or 0),
            "detail": (r.label + ": " if r.label else "") + (r.expression or ""),
            "expression": r.expression or "",
            "origin": "curriculum",
            "mentions": mentions,
        })

    # Coteach
    for ct in db.query(models.CoTeachingRule).all():
        c = classes.get(ct.class_id)
        if c is None:
            continue
        mentions: set[tuple[str, int]] = {("class", c.id)}
        if ct.subject:
            for et, eid, _ in name_index.get(ct.subject.lower(), []):
                mentions.add((et, eid))
        if ct.teacher_csv:
            for nm in (ct.teacher_csv or "").split(","):
                for et, eid, _ in name_index.get(nm.strip().lower(), []):
                    mentions.add((et, eid))
        out.append({
            "kind": "coteach", "id": ct.id,
            "scope": "classe",
            "owner_id": c.id, "owner_name": c.name,
            "level": "hard" if ct.required else "soft",
            "weight": int(ct.weight or 0),
            "detail": (f"{ct.subject}: {ct.n_teachers} docenti"
                       + (f" ({ct.teacher_csv})" if ct.teacher_csv else "")),
            "expression": "",
            "origin": "class",
            "mentions": mentions,
        })

    # Subject<->Classroom prefs
    for sp in db.query(models.ClassroomSubjectPreference).all():
        if (sp.state or "allowed") == "allowed":
            continue
        room = rooms.get(sp.classroom_id)
        if room is None:
            continue
        mentions: set[tuple[str, int]] = {("classroom", room.id)}
        if sp.subject:
            for et, eid, _ in name_index.get(sp.subject.lower(), []):
                mentions.add((et, eid))
        out.append({
            "kind": "subject_room_pref", "id": sp.id,
            "scope": "materia/aula",
            "owner_id": sp.classroom_id,
            "owner_name": f"{sp.subject} <-> {room.name}",
            "level": sp.state, "weight": int(sp.weight or 0),
            "detail": room.name, "expression": "",
            "origin": "classroom",
            "mentions": mentions,
        })

    # Teacher<->Classroom prefs
    for tp in db.query(models.TeacherClassroomPreference).all():
        if (tp.state or "allowed") == "allowed":
            continue
        t = teachers.get(tp.teacher_id)
        room = rooms.get(tp.classroom_id)
        if t is None or room is None:
            continue
        out.append({
            "kind": "teacher_room_pref", "id": tp.id,
            "scope": "docente/aula",
            "owner_id": tp.teacher_id,
            "owner_name": f"{_teacher_display(t)} <-> {room.name}",
            "level": tp.state, "weight": int(tp.weight or 0),
            "detail": room.name, "expression": "",
            "origin": "teacher",
            "mentions": {("teacher", t.id), ("classroom", room.id)},
        })

    # GeneralConstraint (DSL)
    for gc in db.query(models.GeneralConstraint).all():
        mentions: set[tuple[str, int]] = set()
        if gc.scope and gc.owner_id is not None:
            mentions.add((gc.scope, gc.owner_id))
        mentions |= _extract_text_mentions(gc.expression or "", name_index)
        out.append({
            "kind": "general_dsl", "id": gc.id,
            "scope": gc.scope or "global",
            "owner_id": gc.owner_id,
            "owner_name": (gc.label or "(DSL)"),
            "level": gc.level or "hard",
            "weight": int(gc.weight or 0),
            "detail": gc.expression or "",
            "expression": gc.expression or "",
            "origin": gc.scope or "general",
            "mentions": mentions,
        })

    return out


def search_constraints(db: Session, *,
                        entity_type: str | None = None,
                        entity_id: int | None = None,
                        text: str | None = None,
                        levels: Iterable[str] | None = None,
                        kinds: Iterable[str] | None = None,
                        ) -> list[dict]:
    """Search saved constraints by mention. The result is a list of
    constraint dicts (each with `mentions` SET as a list for
    JSON-friendliness) filtered by:

      - entity_type + entity_id : the constraint must mention that
                                  exact (type, id) pair (anywhere:
                                  owner, FK, or in DSL text)
      - text                    : free-text substring in the
                                  constraint's `detail` /
                                  `expression`
      - levels                  : whitelist of levels
      - kinds                   : whitelist of kind values
    """
    rows = list_all_constraints_with_mentions(db)
    if entity_type and entity_id is not None:
        key = (entity_type, int(entity_id))
        rows = [r for r in rows if key in r["mentions"]]
    if text:
        lc = text.lower()
        rows = [r for r in rows
                if lc in (r.get("detail") or "").lower()
                or lc in (r.get("expression") or "").lower()
                or lc in (r.get("owner_name") or "").lower()]
    if levels:
        lv = set(levels)
        rows = [r for r in rows if r.get("level") in lv]
    if kinds:
        kk = set(kinds)
        rows = [r for r in rows if r.get("kind") in kk]
    out: list[dict] = []
    for r in rows:
        mset = r["mentions"]
        out.append({
            **{k: v for k, v in r.items() if k != "mentions"},
            "mentions": [{"entity_type": et, "entity_id": eid}
                         for (et, eid) in sorted(mset)],
        })
    return out
