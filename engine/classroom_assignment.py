r"""Assegnazione delle aule alle lezioni gia\` schedulate -- modulo nuovo.

NON modifica nessuno dei moduli esistenti in `engine/`. E\` pensato
per essere chiamato dal backend webui (`webui/backend/optimization.py`)
con dati gia\` reificati in dict Python.

INPUT
=====
    lessons: list di dict
        {
          'teacher': str,           # docente principale
          'co_teachers': list[str], # eventuali compresenze
          'class':   str,           # nome classe
          'subject': str,
          'day':     int (1..6),
          'hour':    int (8..13),
        }
    classrooms: list di dict
        {
          'name':           str,
          'kind':           str,    # standard / lab_* / palestra / ...
          'capacity':       int,
          'multi_class':    bool,
          'multi_class_max':int,    # HARD: max classi simultanee
          'unavailability': set[(day, hour)],
          'subject_required': set[str],   # HARD subject restrictions
          'subject_pref_weight': dict[subject -> float],
          'class_pref_weight':   dict[class_name -> float],
          'is_home_for':    set[class_name],   # SOFT: home room
        }
    soft_weights: dict, opzionale
        {
          'home_bonus':     float,  # premia home-room match (default 20)
          'lab_match':      float,  # premia lab match (default 10)
          'concurrency':    float,  # penalty per ogni "extra" classe
                                    # rispetto al multi_class_pref
        }

OUTPUT
======
    Un dict {(class, subject, day, hour) -> classroom_name} con la
    nuova assegnazione, oppure None se infeasible.

NOTE
====
- Trattiamo ogni gruppo di compresenze come UN'unica lezione: la chiave
  e\` (class, subject, day, hour). Il modulo non separa le lezioni per
  docente perche\` la stanza e\` condivisa.
- Lab-required: se l'aula ha `subject_required` non vuoto, accetta solo
  lezioni con subject in quell'insieme. Le altre lezioni NON possono
  essere assegnate a quell'aula.
- Multi-class: se due lezioni vogliono la stessa palestra nello stesso
  slot, sono ammesse purche\` <= multi_class_max. Penalita\` SOFT se
  > multi_class_pref (es. preferiamo 1 classe in palestra anche se 2
  starebbero per HARD).

USO programmatico:

    from classroom_assignment import solve_classroom_assignment
    out, status = solve_classroom_assignment(
        lessons, classrooms, time_limit_s=30, workers=4
    )
"""
from __future__ import annotations

import time
from collections import defaultdict
from typing import Any

from ortools.sat.python import cp_model


def _normalize_classroom(cl: dict) -> dict:
    out = dict(cl)
    out.setdefault("kind", "standard")
    out.setdefault("capacity", 30)
    out.setdefault("multi_class", False)
    out.setdefault("multi_class_max", 1 if not out.get("multi_class") else 2)
    out.setdefault("multi_class_pref", 1)
    out.setdefault("multi_class_pref_weight", 10.0)
    out.setdefault("unavailability", set())
    out.setdefault("subject_required", set())
    out.setdefault("subject_pref_weight", {})
    out.setdefault("class_pref_weight", {})
    out.setdefault("is_home_for", set())
    return out


def _can_host(room: dict, lesson: dict) -> bool:
    """HARD eligibility: subject compatibility + room not unavailable on
    that slot."""
    subj = lesson["subject"]
    day = lesson["day"]
    hour = lesson["hour"]
    if (day, hour) in room["unavailability"]:
        return False
    # Lab-required rooms only accept their subjects
    if room["subject_required"] and subj not in room["subject_required"]:
        return False
    return True


def solve_classroom_assignment(
    lessons: list[dict],
    classrooms: list[dict],
    *,
    soft_weights: dict[str, float] | None = None,
    time_limit_s: float = 30.0,
    workers: int = 4,
    log: bool = False,
    locked_classrooms: list[tuple] | None = None,
    plessi_data=None,
) -> tuple[dict | None, str]:
    """Returns (mapping, status_name). mapping is None if infeasible.

    `locked_classrooms` (optional): list of tuples
    (class_name, subject, day, hour, classroom_name) that MUST be
    assigned. Each such lesson_key gets `model.Add(x[(key, room)] == 1)`
    for the named room. If the named room is not eligible for that
    lesson (kind / availability) the solver returns INFEASIBLE with
    a `LOCKED_INELIGIBLE:...` status.
    """
    if not lessons:
        return {}, "OPTIMAL"
    if not classrooms:
        return None, "NO_CLASSROOMS"

    soft = dict(soft_weights or {})
    soft.setdefault("home_bonus", 20.0)
    soft.setdefault("subject_pref_bonus", 10.0)
    soft.setdefault("class_pref_bonus", 10.0)
    soft.setdefault("multi_class_overflow", 30.0)

    rooms = [_normalize_classroom(r) for r in classrooms]
    room_by_name = {r["name"]: r for r in rooms}

    # Build the locked-room map keyed by lesson_key.
    locks_by_lesson: dict[tuple, str] = {}
    for entry in (locked_classrooms or []):
        if len(entry) != 5:
            continue
        cl_l, s_l, d_l, h_l, room_name = entry
        if not room_name:
            continue
        locks_by_lesson[(cl_l, s_l, int(d_l), int(h_l))] = room_name

    # Group lessons by (class, subject, day, hour) — multiple co-teachers
    # share one lesson and one room.
    lesson_keys: list[tuple[str, str, int, int]] = []
    seen = set()
    for L in lessons:
        key = (L["class"], L["subject"], int(L["day"]), int(L["hour"]))
        if key in seen:
            continue
        seen.add(key)
        lesson_keys.append(key)

    # Sanity: each lesson_key must have at least one eligible room.
    eligible: dict[tuple, list[str]] = {}
    for L in lessons:
        key = (L["class"], L["subject"], int(L["day"]), int(L["hour"]))
        if key in eligible:
            continue
        elig = [r["name"] for r in rooms
                if _can_host(r, L)]
        eligible[key] = elig

    no_room_keys = [k for k, v in eligible.items() if not v]
    if no_room_keys:
        # Return early with diagnostic
        return None, f"NO_ELIGIBLE:{no_room_keys[:5]}"

    # Validate locks against eligibility.
    bad_locks = [
        (k, room) for k, room in locks_by_lesson.items()
        if k not in eligible or room not in eligible.get(k, [])
    ]
    if bad_locks:
        return None, f"LOCKED_INELIGIBLE:{bad_locks[:5]}"

    model = cp_model.CpModel()
    # x[lesson_key, room_name] = 1 if that lesson is assigned to that room
    x: dict[tuple, Any] = {}
    for key in lesson_keys:
        for rname in eligible[key]:
            x[(key, rname)] = model.NewBoolVar(f"x_{rname}_{key}")
        # exactly-1 room per lesson
        model.Add(sum(x[(key, rn)] for rn in eligible[key]) == 1)

    # Slot capacity: per (room, day, hour), the number of distinct
    # CLASSES assigned must be <= multi_class_max. Different classes count
    # separately even if subject differs; same class same slot is just one
    # lesson_key.
    by_slot: dict[tuple[str, int, int], list[tuple]] = defaultdict(list)
    for key in lesson_keys:
        cl, subj, d, h = key
        for rn in eligible[key]:
            by_slot[(rn, d, h)].append(key)
    overflow_terms: list[Any] = []
    for (rn, d, h), keys in by_slot.items():
        room = room_by_name[rn]
        max_c = room["multi_class_max"] if room["multi_class"] else 1
        # collect x vars for these lesson_keys -> sum is the number of
        # distinct classes in (room, d, h)
        if not keys:
            continue
        terms = [x[(k, rn)] for k in keys]
        model.Add(sum(terms) <= max_c)
        # SOFT overflow vs preferred concurrency
        pref = max(1, int(room["multi_class_pref"]))
        if pref < max_c:
            ov = model.NewIntVar(0, max_c - pref, f"ov_{rn}_{d}_{h}")
            model.Add(ov >= sum(terms) - pref)
            overflow_terms.append(
                int(soft["multi_class_overflow"] *
                    room["multi_class_pref_weight"]) * ov
            )

    # Native locks: force x[(key, room)] == 1 for every locked
    # (lesson_key, room_name). The eligibility validation above
    # has already ensured the room is in `eligible[key]`.
    for key, room_name in locks_by_lesson.items():
        var = x.get((key, room_name))
        if var is None:
            # Defensive: should be caught by bad_locks above.
            continue
        model.Add(var == 1)

    # Plessi constraints (commuting rules + entity policies for
    # teachers). Builds teacher_for_lesson on the fly so the helper
    # can group decisions by (teacher, day, hour).
    n_pl_commute = 0
    n_pl_policy = 0
    if plessi_data is not None and getattr(
            plessi_data, "classroom_to_plesso", None):
        teacher_for_lesson: dict[tuple, list[str]] = {}
        for L in lessons:
            key = (L["class"], L["subject"],
                   int(L["day"]), int(L["hour"]))
            t_list = teacher_for_lesson.setdefault(key, [])
            if L.get("teacher"):
                t_list.append(L["teacher"])
            for ct in L.get("co_teachers") or []:
                if ct and ct not in t_list:
                    t_list.append(ct)
        days_set = sorted({k[2] for k in lesson_keys})
        hours_set = sorted({k[3] for k in lesson_keys})
        try:
            from plessi_constraints import (  # type: ignore
                add_plesso_commuting_constraints_classroom_assignment,
                add_plesso_entity_policy_constraints_classroom_assignment,
                add_plesso_commuting_constraints_class_kind,
                add_plesso_entity_policy_constraints_class_kind,
            )
        except ImportError:
            from engine.plessi_constraints import (  # type: ignore
                add_plesso_commuting_constraints_classroom_assignment,
                add_plesso_entity_policy_constraints_classroom_assignment,
                add_plesso_commuting_constraints_class_kind,
                add_plesso_entity_policy_constraints_class_kind,
            )
        n_pl_commute = (
            add_plesso_commuting_constraints_classroom_assignment(
                model, x, eligible, plessi_data,
                teacher_for_lesson=teacher_for_lesson,
                days=days_set, hours=hours_set,
            )
            + add_plesso_commuting_constraints_class_kind(
                model, x, eligible, plessi_data,
                days=days_set, hours=hours_set,
            )
        )
        n_pl_policy = (
            add_plesso_entity_policy_constraints_classroom_assignment(
                model, x, eligible, plessi_data,
                teacher_for_lesson=teacher_for_lesson,
                days=days_set,
            )
            + add_plesso_entity_policy_constraints_class_kind(
                model, x, eligible, plessi_data,
                days=days_set,
            )
        )

    # Bonus terms (negative because we minimize -bonus)
    bonus_terms: list[Any] = []
    for key in lesson_keys:
        cl, subj, d, h = key
        for rn in eligible[key]:
            room = room_by_name[rn]
            b = 0.0
            if cl in room["is_home_for"]:
                b += soft["home_bonus"]
            if subj in room["subject_pref_weight"]:
                b += float(room["subject_pref_weight"][subj]) * \
                     soft["subject_pref_bonus"] / 10.0
            if cl in room["class_pref_weight"]:
                b += float(room["class_pref_weight"][cl]) * \
                     soft["class_pref_bonus"] / 10.0
            if b > 0:
                bonus_terms.append(int(-b) * x[(key, rn)])

    # Objective: minimize overflow penalty - bonuses
    objective_terms = list(overflow_terms) + list(bonus_terms)
    if objective_terms:
        model.Minimize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_search_workers = workers
    solver.parameters.log_search_progress = log
    t0 = time.time()
    status = solver.Solve(model)
    elapsed = time.time() - t0
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, solver.StatusName(status)
    out = {}
    for key in lesson_keys:
        for rn in eligible[key]:
            if solver.Value(x[(key, rn)]) == 1:
                out[key] = rn
                break
    print(
        f"[classroom] status={solver.StatusName(status)} "
        f"elapsed={elapsed:.1f}s lessons={len(lesson_keys)} "
        f"rooms={len(rooms)}"
        + (f" plessi(commute={n_pl_commute}, policy={n_pl_policy})"
           if (n_pl_commute or n_pl_policy) else "")
    )
    return out, solver.StatusName(status)


def greedy_classroom_assignment(
    lessons: list[dict],
    classrooms: list[dict],
    *,
    prefer_home: bool = True,
    locked_classrooms: list[tuple] | None = None,
) -> dict:
    """Fallback greedy: per slot, prefer the lesson's home room if free.
    Used when CP-SAT is unnecessary or as a warm start.

    `locked_classrooms` (optional): list of
    (class, subject, day, hour, classroom_name) tuples. The greedy
    pre-assigns those slots first so any subsequent placement
    treats the locked room as occupied (counted in `busy`). Locks
    pointing at an ineligible room are still emitted so the upstream
    _apply_locked_classrooms step has the right answer; the
    capacity bookkeeping for that slot is bumped regardless.
    """
    rooms = [_normalize_classroom(r) for r in classrooms]
    out: dict = {}
    busy: dict[tuple[str, int, int], int] = defaultdict(int)
    by_key: dict[tuple, dict] = {}
    for L in lessons:
        key = (L["class"], L["subject"], int(L["day"]), int(L["hour"]))
        by_key.setdefault(key, L)

    # Pre-place locks. Mark them as done in `out` and reserve the
    # busy slot so the rest of the greedy doesn't double-book.
    locked_keys: set[tuple] = set()
    for entry in (locked_classrooms or []):
        if len(entry) != 5:
            continue
        cl_l, s_l, d_l, h_l, room_name = entry
        if not room_name:
            continue
        key = (cl_l, s_l, int(d_l), int(h_l))
        out[key] = room_name
        busy[(room_name, int(d_l), int(h_l))] += 1
        locked_keys.add(key)

    for key in sorted(by_key):
        if key in locked_keys:
            continue
        L = by_key[key]
        cl, subj, d, h = key
        candidates = [r for r in rooms if _can_host(r, L)]
        if not candidates:
            continue
        if prefer_home:
            home = [r for r in candidates if cl in r["is_home_for"]]
            if home and busy[(home[0]["name"], d, h)] < (
                home[0]["multi_class_max"] if home[0]["multi_class"] else 1
            ):
                room = home[0]
                out[key] = room["name"]
                busy[(room["name"], d, h)] += 1
                continue
        # subject preferences first, then any
        candidates.sort(key=lambda r: (
            -float(r["subject_pref_weight"].get(subj, 0)),
            r["multi_class"],  # avoid multi-class rooms first
        ))
        for room in candidates:
            cap = room["multi_class_max"] if room["multi_class"] else 1
            if busy[(room["name"], d, h)] < cap:
                out[key] = room["name"]
                busy[(room["name"], d, h)] += 1
                break
    return out
