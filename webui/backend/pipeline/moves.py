"""Drag-drop preview, HARD placement gate, and solution health.

The single definition of "is this edit legal" used by /schedule,
/lessons, and the calendar.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from .. import engine_io, models
from .grid import DAY_TO_INT, DAYS, HOURS
from .hard_check import _class_busy_key_fn, _hard_check_ctx


def _logical_constraints(db: Session) -> dict[str, list[dict]]:
    """Materialize logical disjunctive rules grouped by entity_type+name.
    Returns a dict like:
      {
        'teacher_rules': {teacher_name: [ {clauses, is_hard, soft_penalty}, ...]},
        'class_rules':   {class_name:   [...]},
        'room_rules':    {room_name:    [...]},
      }
    """
    import json as _json
    teachers = {t.id: t.name for t in db.query(models.Teacher).all()}
    classes = {c.id: c.name for c in db.query(models.SchoolClass).all()}
    rooms = {r.id: r.name for r in db.query(models.Classroom).all()}
    out = {"teacher_rules": {}, "class_rules": {}, "room_rules": {}}
    for r in db.query(models.LogicalUnavailability).all():
        try:
            clauses = _json.loads(r.parsed_dnf_json or "[]")
        except Exception:
            clauses = []
        rec = {"clauses": clauses, "is_hard": r.is_hard,
               "soft_penalty": r.soft_penalty}
        if r.entity_type == "teacher":
            n = teachers.get(r.entity_id)
            if n: out["teacher_rules"].setdefault(n, []).append(rec)
        elif r.entity_type == "class":
            n = classes.get(r.entity_id)
            if n: out["class_rules"].setdefault(n, []).append(rec)
        elif r.entity_type == "classroom":
            n = rooms.get(r.entity_id)
            if n: out["room_rules"].setdefault(n, []).append(rec)
    return out


def _logical_violation_summary(rules: dict, name: str,
                               unavail_set: set[tuple[int, int]]
                               ) -> tuple[bool, int]:
    """For the rules attached to `name`, returns (any_hard_violated,
    total_soft_penalty).

    Penalty semantics by rule kind:
      * HARD            (is_hard=True)      : violated -> hard flag
      * SOFT            (is_hard=False, p>=0): violated -> +p
      * PREFERRED       (is_hard=False, p<0) : satisfied -> +p (= bonus)

    Both SOFT and PREFERRED contributions are summed in `soft_pen` so the
    same objective accumulator handles both.
    """
    from ..utils.logic_parser import evaluate_against_unavailable
    hard_violated = False
    soft_pen = 0
    for rule in rules.get(name, []):
        ok = evaluate_against_unavailable(rule["clauses"], unavail_set)
        pen = int(rule["soft_penalty"])
        if not ok:
            if rule["is_hard"]:
                hard_violated = True
            elif pen >= 0:
                # SOFT constraint, pay penalty
                soft_pen += pen
            # PREFERRED + violated -> no contribution
        else:
            # satisfied
            if not rule["is_hard"] and pen < 0:
                # PREFERRED + satisfied -> apply bonus (negative)
                soft_pen += pen
    return hard_violated, soft_pen


def _logical_check_for_solution(db: Session, sol: dict
                                ) -> tuple[bool, int, str | None]:
    """Run all logical rules over the given solution. Returns
    (all_hard_satisfied, total_soft_penalty, first_violation_msg_or_None).
    """
    rules = _logical_constraints(db)
    # Build unavailable sets per entity from the solution and the 3-state matrix
    av = _availability_constraints(db)
    teacher_unavail: dict[str, set] = {}
    class_unavail: dict[str, set] = {}
    room_unavail: dict[str, set] = {}
    # 3-state hard cells already block the slot
    for t, d, h in av["teacher_hard"]:
        teacher_unavail.setdefault(t, set()).add((d, h))
    for c, d, h in av["class_hard"]:
        class_unavail.setdefault(c, set()).add((d, h))
    for r, d, h in av["room_hard"]:
        room_unavail.setdefault(r, set()).add((d, h))
    # Slots actually busy in the solution count as unavailable for the
    # entity (occupied by a lesson)
    active = engine_io.get_active_solution(db)
    rooms_by_lesson = {}
    if active is not None:
        for l in db.query(models.Lesson).filter(
            models.Lesson.solution_id == active.id
        ).all():
            rooms_by_lesson[(l.teacher_name, l.class_name, l.subject,
                             l.day, l.hour)] = l.classroom_name
    for k, v in sol.items():
        if v != 1:
            continue
        p, cl, _subj, d, h = k
        teacher_unavail.setdefault(p, set()).add((d, h))
        class_unavail.setdefault(cl, set()).add((d, h))
        room = rooms_by_lesson.get(k)
        if room:
            room_unavail.setdefault(room, set()).add((d, h))

    total_soft = 0
    first_violation = None

    def visit(group_name, name_to_set, rule_group):
        nonlocal total_soft, first_violation
        for name, rule_list in rule_group.items():
            unav = name_to_set.get(name, set())
            for rule in rule_list:
                from ..utils.logic_parser import evaluate_against_unavailable
                ok = evaluate_against_unavailable(rule["clauses"], unav)
                pen = int(rule["soft_penalty"])
                if not ok:
                    if rule["is_hard"]:
                        if first_violation is None:
                            first_violation = (
                                f"vincolo logico HARD violato su {group_name} "
                                f"{name}"
                            )
                        return  # stop on first hard violation
                    if pen >= 0:
                        # SOFT, pay penalty when violated
                        total_soft += pen
                    # PREFERRED violated -> no contribution
                else:
                    if not rule["is_hard"] and pen < 0:
                        # PREFERRED satisfied -> bonus (negative addend)
                        total_soft += pen

    visit("docente", teacher_unavail, rules["teacher_rules"])
    if first_violation is None:
        visit("classe", class_unavail, rules["class_rules"])
    if first_violation is None:
        visit("aula", room_unavail, rules["room_rules"])
    return (first_violation is None, total_soft, first_violation)


def _availability_constraints(db: Session) -> dict[str, Any]:
    """Materialize the HARD/SOFT availability per (teacher, class,
    classroom). Used by drag-drop validation and soft scoring.

    Returns:
      teacher_hard:    set[(name, day, hour)]
      teacher_soft:    dict[(name, day, hour) -> penalty]
      class_hard:      set[(name, day, hour)]
      class_soft:      dict[...]
      room_hard:       set[(name, day, hour)]
      room_soft:       dict[...]
    """
    teacher_hard: set = set()
    teacher_soft: dict = {}
    teacher_enforced: set = set()
    teachers = {t.id: t for t in db.query(models.Teacher).all()}
    for u in db.query(models.TeacherUnavailability).all():
        t = teachers.get(u.teacher_id)
        if t is None:
            continue
        if u.state == "hard":
            teacher_hard.add((t.name, u.day, u.hour))
        elif u.state in ("soft", "preferred"):
            # 'soft'      -> positive penalty (penalised when used)
            # 'preferred' -> negative penalty (rewarded when used)
            teacher_soft[(t.name, u.day, u.hour)] = u.soft_penalty
        elif u.state == "enforced":
            # The teacher MUST have a lesson at this slot. The hard
            # constraint is enforced at solver time; here we just collect.
            teacher_enforced.add((t.name, u.day, u.hour))
    # Auto-promote free_day -> 6 hard cells
    for t in teachers.values():
        d = DAY_TO_INT.get(t.free_day or "")
        if d is None:
            continue
        for h in HOURS:
            teacher_hard.add((t.name, d, h))

    class_hard: set = set()
    class_soft: dict = {}
    class_enforced: set = set()
    classes = {c.id: c for c in db.query(models.SchoolClass).all()}
    for u in db.query(models.ClassUnavailability).all():
        c = classes.get(u.class_id)
        if c is None:
            continue
        if u.state == "hard":
            class_hard.add((c.name, u.day, u.hour))
        elif u.state in ("soft", "preferred"):
            class_soft[(c.name, u.day, u.hour)] = u.soft_penalty
        elif u.state == "enforced":
            class_enforced.add((c.name, u.day, u.hour))

    room_hard: set = set()
    room_soft: dict = {}
    room_enforced: set = set()
    rooms = {r.id: r for r in db.query(models.Classroom).all()}
    for u in db.query(models.ClassroomUnavailability).all():
        r = rooms.get(u.classroom_id)
        if r is None:
            continue
        if u.state == "hard":
            room_hard.add((r.name, u.day, u.hour))
        elif u.state in ("soft", "preferred"):
            room_soft[(r.name, u.day, u.hour)] = u.soft_penalty
        elif u.state == "enforced":
            room_enforced.add((r.name, u.day, u.hour))

    return {
        "teacher_hard": teacher_hard,
        "teacher_soft": teacher_soft,
        "teacher_enforced": teacher_enforced,
        "class_hard": class_hard,
        "class_soft": class_soft,
        "class_enforced": class_enforced,
        "room_hard": room_hard,
        "room_soft": room_soft,
        "room_enforced": room_enforced,
    }


def availability_soft_penalty(sol: dict, db: Session) -> int:
    """Sum of soft penalties induced by SOFT-yellow availability cells
    overlapping with active lessons in `sol`."""
    av = _availability_constraints(db)
    total = 0
    # Need lesson rows for classroom info
    rooms_by_lesson = {}
    active = engine_io.get_active_solution(db)
    if active is not None:
        for l in db.query(models.Lesson).filter(
            models.Lesson.solution_id == active.id
        ).all():
            rooms_by_lesson[(l.teacher_name, l.class_name, l.subject,
                             l.day, l.hour)] = l.classroom_name
    for k, v in sol.items():
        if v != 1:
            continue
        p, cl, _subj, d, h = k
        total += av["teacher_soft"].get((p, d, h), 0)
        total += av["class_soft"].get((cl, d, h), 0)
        room = rooms_by_lesson.get(k)
        if room:
            total += av["room_soft"].get((room, d, h), 0)
    return total


def preview_moves_for_lesson(db: Session, src: tuple,
                              candidates: list[tuple[int, int]] | None = None
                              ) -> list[dict[str, Any]]:
    """For each (day, hour) candidate, simulate moving the lesson at src
    there and report:
      - status: 'ok' / 'hard_violation' / 'soft_worse' / 'noop'
      - reason: explanation when violating HARD
      - delta_soft: int delta (negative = improvement)
    The simulation does NOT persist anything."""
    import metaheuristics as meta  # type: ignore

    active = engine_io.get_active_solution(db)
    if active is None:
        return []
    sol = engine_io.lessons_to_solution_dict(db, active.id)
    profs = engine_io.profs_dict_from_db(db)
    if src not in sol:
        return []
    if candidates is None:
        candidates = [(d, h) for d in DAYS for h in HOURS]
    av = _availability_constraints(db)
    hard_ctx = _hard_check_ctx(db)
    busy_key = _class_busy_key_fn(hard_ctx)
    src_busy = busy_key(*src[:3])
    # Se l'orario di partenza viola gia\` un HARD globale, il gate
    # marcherebbe OGNI destinazione come 'hard_violation' e l'anteprima
    # diventerebbe tutta rossa senza informazione. Vedi la stessa
    # logica in `validate_and_apply_move`.
    base_hard_ok = meta.is_hard_feasible(sol, profs, verbose=False,
                                         **hard_ctx)
    p, cl, subj, _, _ = src
    src_lesson = db.query(models.Lesson).filter(
        models.Lesson.solution_id == active.id,
        models.Lesson.teacher_name == p,
        models.Lesson.class_name == cl,
        models.Lesson.subject == subj,
        models.Lesson.day == src[3],
        models.Lesson.hour == src[4],
    ).first()
    src_room = src_lesson.classroom_name if src_lesson else None
    v0, _ = meta.compute_soft(sol, profs)

    results: list[dict[str, Any]] = []
    for d, h in candidates:
        if d == src[3] and h == src[4]:
            results.append({"day": d, "hour": h, "status": "noop",
                            "reason": "slot di origine",
                            "delta_soft": 0})
            continue
        dst = (p, cl, subj, d, h)
        # quick HARD checks: 3-state availability for teacher/class/room
        if (p, d, h) in av["teacher_hard"]:
            results.append({"day": d, "hour": h,
                            "status": "hard_violation",
                            "reason": f"docente {p} HARD non disp.",
                            "delta_soft": None})
            continue
        if (cl, d, h) in av["class_hard"]:
            results.append({"day": d, "hour": h,
                            "status": "hard_violation",
                            "reason": f"classe {cl} HARD non disp.",
                            "delta_soft": None})
            continue
        # Note: room availability is INTENTIONALLY not checked here. The
        # preview shows the slot as free if teacher/class allow the move;
        # if the lesson's old room is occupied (or HARD-unavailable) at
        # the destination, validate_and_apply_move clears the room and
        # asks the user to pick a new one (room_cleared=True flag).
        # destination already occupied by SAME (same triple) -> noop
        if sol.get(dst, 0) == 1:
            results.append({"day": d, "hour": h, "status": "noop",
                            "reason": "stessa lezione presente",
                            "delta_soft": 0})
            continue
        # destination occupied by DIFFERENT triple -> overlap explanation
        # detect class or teacher already busy at (d, h)
        teacher_busy = any(
            v == 1 and k[0] == p and k[3] == d and k[4] == h
            for k, v in sol.items() if k != src
        )
        # Il sostegno non occupa la classe, e compresenza / parallel
        # intra condividono la stessa cella per costruzione: solo una
        # busy_key DIVERSA e\` un conflitto reale. Vedi
        # `_class_busy_key_fn`.
        class_busy = src_busy is not None and any(
            v == 1 and k[1] == cl and k[3] == d and k[4] == h
            and busy_key(k[0], k[1], k[2]) not in (None, src_busy)
            for k, v in sol.items() if k != src
        )
        if teacher_busy:
            results.append({"day": d, "hour": h,
                            "status": "hard_violation",
                            "reason": f"docente {p} occupato in altro slot",
                            "delta_soft": None})
            continue
        if class_busy:
            results.append({"day": d, "hour": h,
                            "status": "hard_violation",
                            "reason": f"classe {cl} ha gia\\` lezione in {d}/{h}",
                            "delta_soft": None})
            continue
        # full HARD check (covers no-holes / dual-mat / motorie / 5-consec)
        new_sol = dict(sol)
        new_sol[src] = 0
        new_sol[dst] = 1
        if base_hard_ok and not meta.is_hard_feasible(
                new_sol, profs, verbose=False, **hard_ctx):
            results.append({"day": d, "hour": h,
                            "status": "hard_violation",
                            "reason": "viola un vincolo HARD globale "
                                      "(buchi/uscita/dual mat/motorie)",
                            "delta_soft": None})
            continue
        ok_hard, _soft_logical_new, msg = _logical_check_for_solution(db, new_sol)
        if not ok_hard:
            results.append({"day": d, "hour": h,
                            "status": "hard_violation",
                            "reason": msg or "vincolo logico HARD violato",
                            "delta_soft": None})
            continue
        v1, _ = meta.compute_soft(new_sol, profs)
        # 3-state + logical SOFT contributions
        _ok0, soft_logical_old, _ = _logical_check_for_solution(db, sol)
        v0_full = v0 + availability_soft_penalty(sol, db) + soft_logical_old
        v1_full = v1 + availability_soft_penalty(new_sol, db) + _soft_logical_new
        delta = int(v1_full - v0_full)
        if delta > 0:
            status = "soft_worse"
        elif delta < 0:
            status = "ok"
        else:
            status = "ok"
        results.append({"day": d, "hour": h, "status": status,
                        "reason": None, "delta_soft": delta})
    return results


def assess_solution_health(db: Session, sol_id: int) -> dict[str, Any]:
    r"""Is solution ``sol_id`` fit to be the school's live timetable?

    Runs the three checks a solve has to pass before it is allowed to
    become active -- full coverage, global HARD feasibility, logical
    HARD constraints -- against the solution as it is stored *now*.

    It re-checks rather than trusting `Solution.metrics`, because a
    solution can be saved feasible and then rot: the school edits the
    week, a teacher's unavailability changes, hours move by hand. The
    metrics describe the moment the solver finished; activation is
    about the moment the school starts running on it.

    Returns ``{"ok", "problems", "coverage", "required_hours",
    "missing_hours", "worst", "hard_ok", "logical_ok"}``. ``problems``
    is a list of ready-to-show Italian sentences; ``ok`` is simply
    ``not problems``.
    """
    import metaheuristics as meta  # type: ignore

    problems: list[str] = []

    # --- Coverage. Same (teacher, class, subject) accounting /monitor
    # uses for its per-cattedra "ore mancanti", so the two agree.
    placed: dict[tuple, int] = {}
    for l in db.query(models.Lesson).filter(
            models.Lesson.solution_id == sol_id).all():
        key = (l.teacher_name, l.class_name, l.subject)
        placed[key] = placed.get(key, 0) + 1
    teachers = {t.id: t.name for t in db.query(models.Teacher).all()}
    classes = {c.id: c.name for c in db.query(models.SchoolClass).all()}
    required = 0
    missing = 0
    worst: list[dict] = []
    for a in db.query(models.Assignment).all():
        tn = teachers.get(a.teacher_id)
        cn = classes.get(a.class_id)
        if tn is None or cn is None:
            continue
        need = int(a.hours or 0)
        required += need
        gap = need - placed.get((tn, cn, a.subject), 0)
        if gap > 0:
            missing += gap
            worst.append({"teacher": tn, "class": cn,
                          "subject": a.subject, "missing": gap})
    coverage = None if required <= 0 else (required - missing) / required
    worst.sort(key=lambda r: -r["missing"])
    if missing > 0:
        problems.append(
            f"{missing} ore su {required} non sono collocate "
            f"(copertura {(coverage or 0) * 100:.1f}%).")

    # --- Global HARD + logical, on the stored solution.
    sol = engine_io.lessons_to_solution_dict(db, sol_id)
    profs = engine_io.profs_dict_from_db(db)
    hard_ok = True
    try:
        hard_ok = bool(meta.is_hard_feasible(
            sol, profs, verbose=False, **_hard_check_ctx(db)))
    except Exception as exc:  # noqa: BLE001
        # A checker that cannot run is not a pass, but it is also not
        # evidence of a broken timetable -- say which it is.
        hard_ok = True
        problems.append(f"Controllo HARD non eseguibile: {exc}")
    if not hard_ok:
        problems.append(
            "Viola almeno un vincolo HARD globale "
            "(buchi/uscite anticipate/materie doppie/motorie).")
    logical_ok, _soft, msg = _logical_check_for_solution(db, sol)
    if not logical_ok:
        problems.append("Vincolo logico HARD violato: "
                        + (msg or "espressione non soddisfatta."))

    return {
        "ok": not problems,
        "problems": problems,
        "coverage": None if coverage is None else round(coverage, 4),
        "required_hours": required,
        "missing_hours": missing,
        "worst": worst[:10],
        "hard_ok": hard_ok,
        "logical_ok": logical_ok,
    }


def validate_hard_placement(db: Session, *, add: tuple,
                            remove: tuple | None = None,
                            sol: dict | None = None,
                            profs: dict | None = None) -> dict[str, Any]:
    r"""The HARD gate for a single edit of the active solution, shared by
    every hand-editing path.

    ``add`` / ``remove`` are ``(teacher, class, subject, day, hour)``
    keys; pass both for a move, ``add`` alone for an insertion (a pool
    entry being rescheduled, a lesson added by hand). Returns
    ``{"ok", "reason", "baseline_infeasible", "new_sol"}``.

    This exists because it was previously inlined in
    ``validate_and_apply_move`` and therefore reachable only by moves.
    The endpoints that *create* a lesson checked nothing but
    double-booking, so a lesson could be dropped onto an hour where the
    teacher is HARD-unavailable, or one that opens a hole / breaks a
    logical constraint -- the exact guarantees the solver is asked to
    respect, bypassed by a click. Keep this the single definition; a
    fourth copy is how they diverge again.

    NB it is deliberately silent about `Lesson.locked`: a pin belongs to
    an existing row, so only the movers can spend one, and they ask
    first.
    """
    import metaheuristics as meta  # type: ignore
    active = engine_io.get_active_solution(db)
    if active is None:
        return {"ok": False, "reason": "Nessuna soluzione attiva",
                "baseline_infeasible": False, "new_sol": None}
    if sol is None:
        sol = engine_io.lessons_to_solution_dict(db, active.id)
    if profs is None:
        profs = engine_io.profs_dict_from_db(db)

    p, cl, _subj, d, h = add
    av = _availability_constraints(db)
    if (p, d, h) in av["teacher_hard"]:
        return {"ok": False, "baseline_infeasible": False, "new_sol": None,
                "reason": (f"Il docente {p} ha indisponibilita HARD "
                           f"in giorno {d} ora {h}.")}
    if (cl, d, h) in av["class_hard"]:
        return {"ok": False, "baseline_infeasible": False, "new_sol": None,
                "reason": (f"La classe {cl} ha indisponibilita HARD "
                           f"in giorno {d} ora {h}.")}

    new_sol = dict(sol)
    if remove is not None:
        new_sol[remove] = 0
    new_sol[add] = 1

    # Il gate globale ha senso solo se il PUNTO DI PARTENZA e\` pulito.
    # `is_hard_feasible` e\` un bool sull'intera scuola: se l'orario
    # attivo viola gia\` un HARD (tipico dopo un import, o quando Phase B
    # non modella una regola come H_A), pretendere feasibility assoluta
    # rifiuta OGNI modifica, comprese quelle che servono proprio a
    # sanare la violazione. Quando la base e\` gia\` infattibile lo
    # segnaliamo al chiamante e lasciamo passare: i controlli puntuali
    # qui sopra (docente/classe, vincoli logici) restano.
    hard_ctx = _hard_check_ctx(db)
    baseline_infeasible = False
    if not meta.is_hard_feasible(new_sol, profs, verbose=False, **hard_ctx):
        if meta.is_hard_feasible(sol, profs, verbose=False, **hard_ctx):
            return {"ok": False, "baseline_infeasible": False,
                    "new_sol": None,
                    "reason": "Mossa rifiutata: viola almeno un vincolo HARD."}
        baseline_infeasible = True

    ok_hard, _soft_pen, msg = _logical_check_for_solution(db, new_sol)
    if not ok_hard:
        return {"ok": False, "baseline_infeasible": baseline_infeasible,
                "new_sol": None,
                "reason": ("Mossa rifiutata: "
                           + (msg or "vincolo logico HARD violato."))}
    return {"ok": True, "reason": None, "new_sol": new_sol,
            "baseline_infeasible": baseline_infeasible}


def validate_and_apply_move(db: Session, src: tuple, dst: tuple,
                            *, unlock: bool = False) -> dict[str, Any]:
    """src/dst are (teacher_name, class_name, subject, day, hour). The lesson
    at src moves to dst. Returns a dict with accepted/reason and optional
    obj before/after.

    A PINNED lesson (`Lesson.locked`, finding 26) is refused unless the
    caller passes ``unlock=True``, and the refusal carries
    ``needs_unlock=True`` so the UI can ask "sbloccare e spostare?" instead
    of showing a dead end. This is deliberately distinct from a HARD
    rejection, which no flag may override: a pin is the school's own
    earlier choice and only the school can revoke it. Moving with
    ``unlock=True`` leaves the lesson UNPINNED at the destination (the pin
    said "this hour", and the hour is what changed)."""
    import metaheuristics as meta  # type: ignore
    active = engine_io.get_active_solution(db)
    if active is None:
        return {"accepted": False, "reason": "Nessuna soluzione attiva"}
    sol = engine_io.lessons_to_solution_dict(db, active.id)
    profs = engine_io.profs_dict_from_db(db)
    if src not in sol:
        return {"accepted": False, "reason": "Lezione di origine non trovata"}
    if sol.get(dst, 0) == 1:
        return {"accepted": False,
                "reason": "Slot di destinazione gia` occupato dalla "
                          "stessa lezione (no-op)"}
    av = _availability_constraints(db)
    # if the lesson has a classroom, also check room HARD
    src_lesson = db.query(models.Lesson).filter(
        models.Lesson.solution_id == active.id,
        models.Lesson.teacher_name == src[0],
        models.Lesson.class_name == src[1],
        models.Lesson.subject == src[2],
        models.Lesson.day == src[3],
        models.Lesson.hour == src[4],
    ).first()
    # A pin is refusable-but-overridable: ask, don't silently unpin.
    # Checked here, before the expensive _hard_check_ctx/is_hard_feasible
    # pass below, so the round-trip that only wants a confirmation is cheap.
    if src_lesson is not None and src_lesson.locked and not unlock:
        return {"accepted": False, "needs_unlock": True,
                "reason": ("La lezione e` bloccata in questo slot. "
                           "Spostarla la sblocchera`.")}
    # Room HARD-unavailability is NOT a reason to reject the move: the
    # post-apply pass below will simply clear the classroom and tell the
    # caller via room_cleared=True so the UI can prompt for a new pick.

    gate = validate_hard_placement(db, add=dst, remove=src,
                                   sol=sol, profs=profs)
    if not gate["ok"]:
        return {"accepted": False, "reason": gate["reason"]}
    new_sol = gate["new_sol"]
    baseline_infeasible = gate["baseline_infeasible"]
    v0, m0 = meta.compute_soft(sol, profs)
    v1, m1 = meta.compute_soft(new_sol, profs)
    # 3-state SOFT contribution (added on top of meta SOFT score)
    v0 += availability_soft_penalty(sol, db)
    v1 += availability_soft_penalty(new_sol, db)
    # Logical SOFT contribution
    _ok0, soft0, _ = _logical_check_for_solution(db, sol)
    _ok1, soft1, _ = _logical_check_for_solution(db, new_sol)
    v0 += soft0
    v1 += soft1
    # Apply: replace the solution dict, then carry the classroom across
    # the move (replace_solution_lessons keys on (p,cl,subj,day,hour),
    # so the moved lesson would otherwise lose its classroom).
    engine_io.replace_solution_lessons(db, active.id, new_sol)
    src_room = src_lesson.classroom_name if src_lesson else None
    room_cleared = False
    cleared_room = None
    if src_room:
        # Look up the moved lesson row by its new key
        new_row = db.query(models.Lesson).filter(
            models.Lesson.solution_id == active.id,
            models.Lesson.teacher_name == dst[0],
            models.Lesson.class_name == dst[1],
            models.Lesson.subject == dst[2],
            models.Lesson.day == dst[3],
            models.Lesson.hour == dst[4],
        ).first()
        # Conflict 1: the room is occupied by another lesson at dst
        conflict_lesson = db.query(models.Lesson).filter(
            models.Lesson.solution_id == active.id,
            models.Lesson.day == dst[3],
            models.Lesson.hour == dst[4],
            models.Lesson.classroom_name == src_room,
            models.Lesson.id != (new_row.id if new_row else -1),
        ).first()
        # Conflict 2: the room is HARD-unavailable in admin matrix at dst
        conflict_admin = (src_room, dst[3], dst[4]) in av["room_hard"]
        if new_row is not None:
            if conflict_lesson is None and not conflict_admin:
                # Free: carry the room across the move
                new_row.classroom_name = src_room
            else:
                # Occupied: leave the moved lesson without a classroom and
                # tell the caller so the UI can prompt for a new pick.
                new_row.classroom_name = None
                room_cleared = True
                cleared_room = src_room
    active.obj_value = float(v1)
    # Non dichiarare "feasible" quello che non lo e\`: se la mossa e\`
    # passata solo perche\` la base era gia\` infattibile, il flag deve
    # dirlo, altrimenti la dashboard mostra verde su un orario rotto.
    active.metrics_json = json.dumps(
        {**m1, "feasible": not baseline_infeasible})
    db.commit()
    return {
        "accepted": True,
        "baseline_infeasible": baseline_infeasible,
        "reason": ("Miglioramento di "
                   f"{int(v0 - v1)} punti SOFT" if v1 < v0 else
                   ("Stesso valore SOFT" if v1 == v0
                    else f"Peggioramento di {int(v1 - v0)} punti SOFT")),
        "obj_before": float(v0),
        "obj_after": float(v1),
        "delta": float(v1 - v0),
        "metrics_before": m0,
        "metrics_after": m1,
        "room_cleared": room_cleared,
        "cleared_room": cleared_room,
    }
