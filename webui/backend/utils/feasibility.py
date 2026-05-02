"""Feasibility check for the HARD/ENFORCED constraint set.

Builds a minimal CP-SAT model that captures matrix HARD/ENFORCED
cells, Assignment.hours requirements, and per-(teacher, slot) /
per-(class, slot) atMostOne. Wraps every removable constraint in
an assumption literal so that, when UNSAT, CP-SAT's
`SufficientAssumptionsForInfeasibility()` returns a minimal core
of constraints whose removal would make the model SAT.

The model is intentionally LIGHT: it does NOT model rooms or the
Phase B SOFT objective. It checks "is it possible at all to fit the
required hours into the available slots given the HARD/ENFORCED
constraints?". For richer checks (logical-DNF, room availability,
SOFT preferences) the existing `monitor._detect_conflicts` runs
alongside and contributes its hits as additional cores.

Returns:
    {
        "feasible": bool | None,        # None if solver timed out
        "n_constraints": int,           # constraints encoded in CP-SAT
        "n_assignments": int,
        "time_s": float,
        "cores": [
            {
                "id": int,
                "kind": "matrix_hard" | "matrix_enforced" |
                        "logical_unsat" | "hours_overflow"
                        | ...,
                "reason": str,
                "members": [
                    { "db_kind": str, "db_id": int,
                      "level": str, "scope": str,
                      "owner_name": str, "detail": str },
                    ...
                ],
            },
            ...
        ],
        "suggested_removal": [
            { "db_kind": str, "db_id": int,
              "owner_name": str, "detail": str, "reason": str },
            ...
        ],
    }
"""
from __future__ import annotations

import json
import time
from collections import defaultdict
from typing import Any

from sqlalchemy.orm import Session

from .. import models


_DAYS = list(range(1, 7))
_HOURS = list(range(8, 14))
_DAY_CODE = {1: "Lun", 2: "Mar", 3: "Mer", 4: "Gio",
             5: "Ven", 6: "Sab"}


def _slot_label(d: int, h: int) -> str:
    return f"{_DAY_CODE.get(d, '?')}{h}"


def _teacher_display(t: models.Teacher) -> str:
    if t.nickname:
        return t.nickname
    if t.last_name and t.first_name:
        return f"{t.last_name} {t.first_name}"
    return t.name


_DAY_TO_INT = {
    "Monday": 1, "Tuesday": 2, "Wednesday": 3,
    "Thursday": 4, "Friday": 5, "Saturday": 6,
    "Lunedi": 1, "Martedi": 2, "Mercoledi": 3,
    "Giovedi": 4, "Venerdi": 5, "Sabato": 6,
}


def feasibility_check(db: Session, *, time_limit_s: float = 30.0
                      ) -> dict[str, Any]:
    try:
        from ortools.sat.python import cp_model
    except ImportError:
        return {
            "feasible": None,
            "error": "ortools non installato",
            "cores": [],
            "suggested_removal": [],
            "n_constraints": 0,
            "n_assignments": 0,
            "time_s": 0.0,
        }

    t_start = time.time()
    teachers = {t.id: t for t in db.query(models.Teacher).all()}
    classes = {c.id: c for c in db.query(models.SchoolClass).all()}
    rooms = {r.id: r for r in db.query(models.Classroom).all()}
    assignments = db.query(models.Assignment).all()

    cores: list[dict] = []
    next_core_id = 1

    # ----- Quick local pre-check: matrix HARD + ENFORCED on same cell -----
    # CP-SAT would catch these too, but pre-detecting them gives nicer
    # error messages and cheaper output if there are obvious clashes.
    cell_state: dict[tuple[str, int, int, int], list[dict]] = {}
    for u in db.query(models.TeacherUnavailability).all():
        if u.state in ("hard", "enforced"):
            t = teachers.get(u.teacher_id)
            cell_state.setdefault(
                ("teacher", u.teacher_id, u.day, u.hour), []
            ).append({
                "db_kind": "teacher_cell", "db_id": u.id,
                "level": u.state, "scope": "docente",
                "owner_name": _teacher_display(t) if t else f"#{u.teacher_id}",
                "detail": _slot_label(u.day, u.hour),
            })
    for u in db.query(models.ClassUnavailability).all():
        if u.state in ("hard", "enforced"):
            c = classes.get(u.class_id)
            cell_state.setdefault(
                ("class", u.class_id, u.day, u.hour), []
            ).append({
                "db_kind": "class_cell", "db_id": u.id,
                "level": u.state, "scope": "classe",
                "owner_name": c.name if c else f"#{u.class_id}",
                "detail": _slot_label(u.day, u.hour),
            })
    for u in db.query(models.ClassroomUnavailability).all():
        if u.state in ("hard", "enforced"):
            r = rooms.get(u.classroom_id)
            cell_state.setdefault(
                ("classroom", u.classroom_id, u.day, u.hour), []
            ).append({
                "db_kind": "room_cell", "db_id": u.id,
                "level": u.state, "scope": "aula",
                "owner_name": r.name if r else f"#{u.classroom_id}",
                "detail": _slot_label(u.day, u.hour),
            })
    for key, members in cell_state.items():
        levels = {m["level"] for m in members}
        if "hard" in levels and "enforced" in levels:
            cores.append({
                "id": next_core_id,
                "kind": "matrix_hard_enforced",
                "reason": (f"{key[0]} #{key[1]}: stessa cella marcata "
                           f"sia HARD sia ENFORCED."),
                "members": members,
            })
            next_core_id += 1

    # ----- CP-SAT model: per-Assignment hours feasibility ---------------
    # We don't model classrooms in this MVP (the user runs the dedicated
    # classroom assignment step separately). We do model:
    #   - one boolean var per (assignment, day, hour)
    #   - sum == hours per assignment
    #   - <= 1 per (teacher, slot) across that teacher's assignments
    #   - <= 1 per (class, slot) across that class's assignments
    #   - matrix HARD (T/C cells) -> assumption: sum at that slot for
    #                                that owner == 0
    #   - matrix ENFORCED -> assumption: sum at that slot >= 1
    #   - teacher.free_day -> hardcoded as if HARD on every slot of the
    #                         day; we do NOT make this an assumption
    #                         because it's a teacher field, not a row.
    model = cp_model.CpModel()

    by_class = defaultdict(list)
    by_teacher = defaultdict(list)
    for a in assignments:
        by_class[a.class_id].append(a)
        by_teacher[a.teacher_id].append(a)

    lesson_var: dict[tuple[int, int, int], Any] = {}
    for a in assignments:
        for d in _DAYS:
            for h in _HOURS:
                lesson_var[(a.id, d, h)] = model.NewBoolVar(
                    f"lesson_{a.id}_{d}_{h}"
                )
        model.Add(
            sum(lesson_var[(a.id, d, h)] for d in _DAYS for h in _HOURS)
            == int(a.hours)
        )

    for cid, alist in by_class.items():
        for d in _DAYS:
            for h in _HOURS:
                model.Add(
                    sum(lesson_var[(a.id, d, h)] for a in alist) <= 1
                )
    for tid, alist in by_teacher.items():
        for d in _DAYS:
            for h in _HOURS:
                model.Add(
                    sum(lesson_var[(a.id, d, h)] for a in alist) <= 1
                )

    # Free-day teacher: treat as background HARD (not under assumption).
    for tid, t in teachers.items():
        d = _DAY_TO_INT.get(t.free_day or "")
        if d is None:
            continue
        for a in by_teacher.get(tid, []):
            for h in _HOURS:
                model.Add(lesson_var[(a.id, d, h)] == 0)

    # Assumption literal -> {db_kind, db_id, level, scope, owner_name, detail}
    assumptions: dict[Any, dict] = {}

    def _add_hard_cell_teacher(u):
        alist = by_teacher.get(u.teacher_id, [])
        if not alist:
            return
        lit = model.NewBoolVar(f"a_thard_{u.id}")
        for a in alist:
            model.Add(
                lesson_var[(a.id, u.day, u.hour)] == 0
            ).OnlyEnforceIf(lit)
        assumptions[lit] = {
            "db_kind": "teacher_cell", "db_id": u.id,
            "level": "hard", "scope": "docente",
            "owner_name": _teacher_display(teachers.get(u.teacher_id))
                          if teachers.get(u.teacher_id)
                          else f"#{u.teacher_id}",
            "detail": _slot_label(u.day, u.hour),
        }
        model.AddAssumption(lit)

    def _add_enforced_cell_teacher(u):
        alist = by_teacher.get(u.teacher_id, [])
        if not alist:
            return
        lit = model.NewBoolVar(f"a_tenf_{u.id}")
        model.Add(
            sum(lesson_var[(a.id, u.day, u.hour)] for a in alist) >= 1
        ).OnlyEnforceIf(lit)
        assumptions[lit] = {
            "db_kind": "teacher_cell", "db_id": u.id,
            "level": "enforced", "scope": "docente",
            "owner_name": _teacher_display(teachers.get(u.teacher_id))
                          if teachers.get(u.teacher_id)
                          else f"#{u.teacher_id}",
            "detail": _slot_label(u.day, u.hour),
        }
        model.AddAssumption(lit)

    def _add_hard_cell_class(u):
        alist = by_class.get(u.class_id, [])
        if not alist:
            return
        lit = model.NewBoolVar(f"a_chard_{u.id}")
        for a in alist:
            model.Add(
                lesson_var[(a.id, u.day, u.hour)] == 0
            ).OnlyEnforceIf(lit)
        assumptions[lit] = {
            "db_kind": "class_cell", "db_id": u.id,
            "level": "hard", "scope": "classe",
            "owner_name": classes.get(u.class_id).name
                          if classes.get(u.class_id)
                          else f"#{u.class_id}",
            "detail": _slot_label(u.day, u.hour),
        }
        model.AddAssumption(lit)

    def _add_enforced_cell_class(u):
        alist = by_class.get(u.class_id, [])
        if not alist:
            return
        lit = model.NewBoolVar(f"a_cenf_{u.id}")
        model.Add(
            sum(lesson_var[(a.id, u.day, u.hour)] for a in alist) >= 1
        ).OnlyEnforceIf(lit)
        assumptions[lit] = {
            "db_kind": "class_cell", "db_id": u.id,
            "level": "enforced", "scope": "classe",
            "owner_name": classes.get(u.class_id).name
                          if classes.get(u.class_id)
                          else f"#{u.class_id}",
            "detail": _slot_label(u.day, u.hour),
        }
        model.AddAssumption(lit)

    for u in db.query(models.TeacherUnavailability).all():
        if u.state == "hard":
            _add_hard_cell_teacher(u)
        elif u.state == "enforced":
            _add_enforced_cell_teacher(u)
    for u in db.query(models.ClassUnavailability).all():
        if u.state == "hard":
            _add_hard_cell_class(u)
        elif u.state == "enforced":
            _add_enforced_cell_class(u)

    n_assumptions = len(assumptions)

    # ----- Solve -------------------------------------------------------
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit_s)
    status = solver.Solve(model)

    if status == cp_model.INFEASIBLE:
        # Extract MUS via SufficientAssumptionsForInfeasibility.
        # Returns the indices of the assumption proto list that suffice
        # for infeasibility -- a minimal-ish core.
        try:
            core_indices = solver.SufficientAssumptionsForInfeasibility()
        except Exception:
            core_indices = []
        # Build name->info lookup keyed by Var index.
        core_members: list[dict] = []
        for lit, info in assumptions.items():
            if lit.Index() in core_indices:
                core_members.append(info)
        if core_members:
            cores.append({
                "id": next_core_id,
                "kind": "cpsat_unsat_core",
                "reason": ("Sotto-insieme minimale di vincoli HARD/ENFORCED "
                           "che insieme rendono il modello UNSAT."),
                "members": core_members,
            })
            next_core_id += 1
    elif status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # No CP-SAT-level core. The pre-check cores (if any) still
        # represent infeasibilities we caught locally.
        pass
    else:
        # UNKNOWN / MODEL_INVALID -- treat as inconclusive.
        return {
            "feasible": None,
            "error": f"solver status={status} (timeout o errore)",
            "cores": cores,
            "suggested_removal": [],
            "n_constraints": n_assumptions,
            "n_assignments": len(assignments),
            "time_s": round(time.time() - t_start, 3),
        }

    # ----- Suggested removal --------------------------------------------
    # Heuristic: union of all core members minus one per core. Picking
    # the "most local" cell per core (smaller scope first) maximises
    # the chance that removing those leaves the rest of the model
    # untouched. For now we just propose: for each core remove all
    # its members EXCEPT the first one (which is the most-restrictive
    # ENFORCED if any, otherwise the first HARD).
    suggested: list[dict] = []
    seen: set[tuple[str, int]] = set()
    for c in cores:
        members = c["members"]
        if not members:
            continue
        # Keep one (prefer ENFORCED), remove the rest.
        keep_idx = 0
        for i, m in enumerate(members):
            if m["level"] == "enforced":
                keep_idx = i; break
        for i, m in enumerate(members):
            if i == keep_idx:
                continue
            key = (m["db_kind"], m["db_id"])
            if key in seen:
                continue
            seen.add(key)
            suggested.append({
                **m,
                "reason": (f"In conflitto con {len(members) - 1} altri "
                           f"vincoli del core #{c['id']}"),
            })

    feasible = (status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
                and len(cores) == 0)
    return {
        "feasible": feasible,
        "cores": cores,
        "suggested_removal": suggested,
        "n_constraints": n_assumptions,
        "n_assignments": len(assignments),
        "time_s": round(time.time() - t_start, 3),
    }
