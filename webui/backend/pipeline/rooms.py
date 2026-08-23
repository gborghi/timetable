"""Classroom-assignment step and mock-room generation.

Used standalone (`run_classroom_assignment`) and as a post-step of
Phase B / meta / the full pipeline (`_apply_rooms_to_solution`).
"""
from __future__ import annotations

from typing import Any

from .. import engine_io, models
from ..db import SessionLocal
from ..run_manager import create_run, start_thread, update_run
from .preflight import _read_locked_lessons


def _log_room_pins(pins: dict, prefix: str = "rooms") -> None:
    r"""Rende visibili nel log i preset aule attivi per questo run.

    Il vincolo di aula base e\` HARD e senza traccia nel log un
    INFEASIBLE dello step aule sarebbe indistinguibile da un problema
    di capienza. `fissa_senza_aula` e\` una configurazione incompleta
    (preset 'fissa' senza aula base): si degrada a 'ibrida' e lo si
    dice, invece di far fallire il run.
    """
    pin = pins.get("pin") or {}
    forb = pins.get("forbidden") or {}
    orfane = pins.get("fissa_senza_aula") or []
    if pin:
        print(f"[{prefix}] {len(pin)} classi con aula fissa (HARD); "
              "le materie con aula speciale richiesta derogano")
    if forb:
        n = sum(len(v) for v in forb.values())
        print(f"[{prefix}] {n} divieti classe-aula (HARD) "
              f"su {len(forb)} classi")
    if orfane:
        print(f"[{prefix}] ATTENZIONE: {len(orfane)} classi hanno preset "
              f"'fissa' ma nessuna aula base: {', '.join(orfane[:10])}"
              + (" ..." if len(orfane) > 10 else ""))
        print(f"[{prefix}] per queste classi il preset non ha effetto "
              "(si comportano come 'ibrida'). Assegna un'aula base "
              "dalla scheda Aule per renderlo operativo.")

def _room_map_from_joint_x(solver, cp_solver) -> dict | None:
    r"""Extract ``{(class, subject, day, hour) -> room_name}`` from the joint
    room vars stashed on the week solver (``solver._joint_room_x``, set by
    ``_add_joint_rooms``). Returns None when the solver carried no joint room
    vars (non-joint run). Covers non-rider cells; riders inherit downstream.
    """
    x = getattr(solver, "_joint_room_x", None)
    if not x:
        return None
    rm: dict = {}
    for (cell, rn), var in x.items():
        try:
            if cp_solver.Value(var) == 1:
                rm[cell] = rn
        except Exception:  # noqa: BLE001
            pass
    return rm


def _apply_joint_room_map(sid: int, room_map: dict,
                          *, log_prefix: str = "rooms.joint") -> dict | None:
    r"""Write the JOINT week solve's OWN room assignment (captured from its
    room vars) onto solution ``sid`` -- so the joint room objective
    (home / continuity) reaches the output, instead of re-solving with the
    standalone solver + greedy fallback (which discards it).

    ``room_map`` covers non-rider cells; compresenza riders inherit the room
    of a host cell in the same ``(class, day, hour)``. Returns metrics, or
    ``None`` when some lesson can't be roomed (coverage gap) so the caller
    falls back to the standalone step rather than leaving it roomless.
    """
    with SessionLocal() as db:
        lessons = engine_io.lessons_for_classroom_step(db, sid)
    host_room: dict = {}
    for (cl, _subj, d, h), rn in room_map.items():
        host_room.setdefault((cl, d, h), rn)
    final = dict(room_map)
    unroomed = 0
    for L in lessons:
        key = (L["class"], L["subject"], int(L["day"]), int(L["hour"]))
        if key in final:
            continue
        inh = host_room.get((L["class"], int(L["day"]), int(L["hour"])))
        if inh:
            final[key] = inh
        else:
            unroomed += 1
    if unroomed:
        print(f"[{log_prefix}] {unroomed}/{len(lessons)} lessons have no "
              f"joint room; falling back to standalone room step")
        return None
    with SessionLocal() as db:
        n = engine_io.apply_room_mapping(db, sid, final, clear_missing=True)
    print(f"[{log_prefix}] {n}/{len(lessons)} lessons roomed from the joint "
          f"solve's own room vars (home/continuity preserved)")
    return {
        "rooms_assigned": n,
        "rooms_total_lessons": len(lessons),
        "rooms_exact_status": "JOINT",
        "rooms_fallback": False,
        "rooms_joint": True,
    }


def _unplaced_from_status(status: str | None) -> int:
    """Parse the ``.../UNPLACED:<n>`` suffix the room solver appends when a
    capacity/plesso shortage forced it to leave lessons without a real room.
    Returns 0 when the status carries no such suffix (or is None)."""
    if not status or "/UNPLACED:" not in status:
        return 0
    try:
        return int(status.rsplit("/UNPLACED:", 1)[1])
    except (ValueError, IndexError):
        return 0


def _rooms_unplaced_count(lessons: list[dict], result: dict) -> int:
    """Lessons left without a real room, counted off the mapping actually
    shipped rather than off the exact solver's ``/UNPLACED:<n>`` suffix --
    the suffix describes the exact solve, and the greedy branch (fallback
    or rescue) produces a different mapping with a different shortfall."""
    keys = {(L["class"], L["subject"], int(L["day"]), int(L["hour"]))
            for L in lessons}
    return sum(1 for k in keys if k not in (result or {}))


def _rooms_with_greedy_fallback(result, status, *, lessons, rooms,
                                prefer_home: bool, locked_classrooms,
                                plessi_data, log_prefix: str = "rooms"):
    r"""Decide what the room step actually ships, given the exact solve's
    outcome. Returns ``(result, rooms_fallback, rooms_rescued)``.

    Two distinct reasons to reach for the greedy heuristic:

    1. the exact solve returned nothing at all (`result is None`): solver
       failure, NO_CLASSROOMS/NO_ELIGIBLE/LOCKED_INELIGIBLE. Greedy is the
       only thing left -- that is `rooms_fallback`, and it has always run;
    2. the exact solve came back cut short AND with lessons unplaced.
       Since `allow_unplaced` gives every lesson a virtual "no room"
       fallback, the model is trivially feasible, so a timeout no longer
       yields None -- it yields a FEASIBLE incumbent that may have parked
       a pile of lessons on the virtual room simply because the search
       never got far. The old `result is None` test could not see that
       case, so the greedy branch was dead on timeout and a badly-timed
       solve shipped its degraded incumbent unchallenged. Here we run
       greedy too and keep whichever placed more lessons: greedy is fast,
       lock- and plesso-aware, and on an OPTIMAL status we don't bother
       (nothing can beat it, unplaced there is a real shortage).
    """
    from classroom_assignment import (  # type: ignore
        greedy_classroom_assignment,
    )
    if result is None:
        print(f"[{log_prefix}] CP-SAT infeasible ({status}); fallback greedy")
        # Greedy is now lock-aware (FU-2): forward the same
        # locked_classrooms list so the fallback honours every lock.
        # It must also see `plessi_data`, or the fallback places lessons
        # plesso-blind while the exact model would have honoured the
        # single-plesso policies (finding 35b).
        return greedy_classroom_assignment(
            lessons, rooms, prefer_home=prefer_home,
            locked_classrooms=locked_classrooms or None,
            plessi_data=plessi_data,
        ), True, 0
    unplaced = _unplaced_from_status(status)
    if not unplaced or (status or "").startswith("OPTIMAL"):
        return result, False, 0
    print(f"[{log_prefix}] {status}: {unplaced} lezioni senza aula da una "
          "ricerca troncata; provo il greedy come controprova")
    alt = greedy_classroom_assignment(
        lessons, rooms, prefer_home=prefer_home,
        locked_classrooms=locked_classrooms or None,
        plessi_data=plessi_data,
    )
    rescued = len(alt) - len(result)
    if rescued <= 0:
        print(f"[{log_prefix}] il greedy non fa meglio ({len(alt)} vs "
              f"{len(result)} lezioni collocate); tengo la soluzione esatta")
        return result, False, 0
    print(f"[{log_prefix}] il greedy colloca {rescued} lezioni in piu'; "
          "uso quella")
    return alt, True, rescued


def _apply_rooms_to_solution(sid: int, *, time_limit_s: float,
                             workers: int, prefer_home: bool,
                             log_prefix: str = "rooms",
                             log: bool = False) -> dict[str, Any]:
    """Run the classroom-assignment step on solution `sid` synchronously
    (inside another run's worker thread). Returns a metrics dict that
    can be merged into the parent run's metrics_json.

    Used by:
      - run_phase_b / run_meta when their `optimize_rooms` toggle is on
      - run_full_pipeline when one of its steps in the pipeline list
        carries the per-step rooms toggle
      - the standalone "rooms" pipeline step
    """
    from classroom_assignment import (  # type: ignore
        solve_classroom_assignment,
    )
    try:
        from plessi_constraints import (  # type: ignore
            load_plessi_data,
        )
    except ImportError:
        from engine.plessi_constraints import (  # type: ignore
            load_plessi_data,
        )
    with SessionLocal() as db:
        pins = engine_io.room_pins_from_db(db)
        lessons = engine_io.lessons_for_classroom_step(db, sid, pins=pins)
        rooms = engine_io.classrooms_dicts_from_db(db)
        # Native lock for the classroom step: read the snapshot of
        # locked Lessons that have a classroom_name and force the
        # solver to assign that room to that lesson.
        locked_snap = _read_locked_lessons(db)
        plessi_data = load_plessi_data(db)
    locked_classrooms = [
        (d["class_name"], d["subject"], int(d["day"]), int(d["hour"]),
         d["classroom_name"])
        for d in locked_snap
        if d.get("day") is not None and d.get("hour") is not None
        and d.get("classroom_name")
    ]
    if not rooms:
        print(f"[{log_prefix}] no rooms in DB; skipping room step")
        return {"rooms_skipped": "no_rooms"}
    if not lessons:
        print(f"[{log_prefix}] solution has no lessons; skipping room step")
        return {"rooms_skipped": "no_lessons"}
    print(f"[{log_prefix}] {len(lessons)} lessons, {len(rooms)} rooms"
          + (f", {len(locked_classrooms)} classroom locks"
             if locked_classrooms else ""))
    _log_room_pins(pins, log_prefix)
    result, status = solve_classroom_assignment(
        lessons, rooms, time_limit_s=time_limit_s,
        workers=workers, log=log,
        locked_classrooms=locked_classrooms or None,
        plessi_data=plessi_data,
    )
    result, rooms_fallback, rooms_rescued = _rooms_with_greedy_fallback(
        result, status, lessons=lessons, rooms=rooms,
        prefer_home=prefer_home, locked_classrooms=locked_classrooms,
        plessi_data=plessi_data, log_prefix=log_prefix)
    rooms_unplaced = _rooms_unplaced_count(lessons, result)
    with SessionLocal() as db:
        # Esaustivo: `result` nasce da TUTTE le lezioni della soluzione,
        # quindi chi non c'e\` e\` rimasto senza aula per davvero e l'aula
        # del run precedente va tolta, non lasciata li\`.
        n_rooms = engine_io.apply_room_mapping(db, sid, result,
                                               clear_missing=True)
    print(f"[{log_prefix}] {n_rooms}/{len(lessons)} lessons got a room"
          + (f" ({rooms_unplaced} senza aula per capienza/plesso)"
             if rooms_unplaced else ""))
    # Surface the exact-vs-fallback outcome so a silent greedy fallback
    # stops reading as "assegnazione riuscita" (finding 35a). With the
    # unplaced fallback the exact solve stays feasible under a slot
    # shortage, so the two signals now mean different things:
    # `rooms_fallback` = the exact solve returned nothing at all (solver
    # failure, or NO_ELIGIBLE: a lesson with no eligible room anywhere,
    # which is a configuration error read off `rooms_exact_status`);
    # `rooms_unplaced` = the exact solve succeeded but could not fit N
    # lessons for capacity/plesso reasons (findings 33/34).
    # `rooms_rescued` > 0 means the second case above: the exact incumbent
    # was truncated and the greedy placed more, so `rooms_fallback` here
    # says "what you are looking at is the greedy's mapping", not "the
    # exact solve died".
    return {"rooms_assigned": n_rooms, "rooms_total_lessons": len(lessons),
            "rooms_exact_status": status, "rooms_fallback": rooms_fallback,
            "rooms_unplaced": rooms_unplaced,
            "rooms_rescued": rooms_rescued}


def run_classroom_assignment(time_limit_s: float, workers: int, log: bool,
                             prefer_home: bool = True) -> int:
    """Step 'Assegna aule' — uses engine/classroom_assignment.py."""
    params = dict(time_limit_s=time_limit_s, workers=workers, log=log,
                  prefer_home=prefer_home)
    run_id = create_run("rooms", "Assegnazione aule", None, params)

    def target(rid: int):
        from classroom_assignment import (  # type: ignore
            solve_classroom_assignment,
        )
        try:
            from plessi_constraints import (  # type: ignore
                load_plessi_data,
            )
        except ImportError:
            from engine.plessi_constraints import (  # type: ignore
                load_plessi_data,
            )
        with SessionLocal() as db:
            active = engine_io.get_active_solution(db)
            if active is None:
                raise RuntimeError(
                    "Nessuna soluzione attiva: esegui prima Phase B."
                )
            pins = engine_io.room_pins_from_db(db)
            lessons = engine_io.lessons_for_classroom_step(
                db, active.id, pins=pins)
            rooms = engine_io.classrooms_dicts_from_db(db)
            locked_snap = _read_locked_lessons(db)
            plessi_data = load_plessi_data(db)
        locked_classrooms = [
            (d["class_name"], d["subject"], int(d["day"]), int(d["hour"]),
             d["classroom_name"])
            for d in locked_snap
            if d.get("day") is not None and d.get("hour") is not None
            and d.get("classroom_name")
        ]
        if not rooms:
            raise RuntimeError(
                "Nessuna aula nel DB: importa o genera la lista aule prima."
            )
        if not lessons:
            raise RuntimeError("Soluzione attiva senza lezioni.")
        print(f"[rooms] {len(lessons)} lezioni, {len(rooms)} aule"
              + (f", {len(locked_classrooms)} aule lockate"
                 if locked_classrooms else ""))
        _log_room_pins(pins)
        result, status = solve_classroom_assignment(
            lessons, rooms, time_limit_s=time_limit_s,
            workers=workers, log=log,
            locked_classrooms=locked_classrooms or None,
            plessi_data=plessi_data,
        )
        result, rooms_fallback, rooms_rescued = _rooms_with_greedy_fallback(
            result, status, lessons=lessons, rooms=rooms,
            prefer_home=prefer_home, locked_classrooms=locked_classrooms,
            plessi_data=plessi_data)
        rooms_unplaced = _rooms_unplaced_count(lessons, result)
        with SessionLocal() as db:
            n = engine_io.apply_room_mapping(db, active.id, result,
                                             clear_missing=True)
        # `rooms_fallback` tells the UI the exact solve returned nothing
        # (timeout/unknown, or NO_ELIGIBLE -- a lesson with no eligible
        # room anywhere, which `rooms_exact_status` names) and what it
        # holds is the approximate greedy placement, instead of reading as
        # a clean success (finding 35a). `rooms_unplaced` reports the
        # lessons the (feasible) exact solve could not fit into any real
        # room -- a capacity/plesso shortage the headmaster must resolve,
        # not a solver failure (findings 33/34). `rooms_rescued` > 0 marks
        # the third case: l'esatto era troncato e il greedy ha collocato
        # piu\` lezioni, quindi cio\` che si vede e\` la mappa del greedy.
        update_run(rid, progress=1.0, metrics={
            "rooms_assigned": n, "lessons": len(lessons),
            "rooms_exact_status": status, "rooms_fallback": rooms_fallback,
            "rooms_unplaced": rooms_unplaced,
            "rooms_rescued": rooms_rescued,
        })
        print(f"[rooms] {n}/{len(lessons)} lezioni hanno un'aula"
              + (f" ({rooms_unplaced} senza aula per capienza/plesso)"
                 if rooms_unplaced else ""))

    start_thread(run_id, target)
    return run_id

def auto_generate_classrooms(overrides: dict[str, int | None] | None = None
                             ) -> dict[str, Any]:
    """Synchronous helper: build the classrooms via the recipe and persist.

    The recipe scales with the number of classes currently in the DB.
    `overrides` is a partial dict {kind: count}; any kind not present
    falls back to the proportional default returned by
    `compute_default_counts`. Returns a summary dict including the
    counts actually used."""
    from .. import mock_classrooms
    out = {"created": 0, "updated": 0, "counts_used": {}, "n_classes": 0}
    with SessionLocal() as db:
        class_names = [c.name for c in db.query(models.SchoolClass).all()]
        if not class_names:
            raise RuntimeError(
                "Nessuna classe nel DB: importa o genera la scuola prima."
            )
        n_classes = len(class_names)
        defaults = mock_classrooms.compute_default_counts(n_classes)
        counts_used = dict(defaults)
        if overrides:
            for k, v in overrides.items():
                if v is not None and k in counts_used:
                    counts_used[k] = max(0, int(v))
        out["n_classes"] = n_classes
        out["counts_used"] = counts_used
        recipe = mock_classrooms.build_recipe_for_classes(
            class_names, n_classes=n_classes, overrides=counts_used
        )
        # Wipe existing classrooms (cascades remove tag assignments
        # via the ClassroomTagAssignment FK).
        db.query(models.ClassroomSubjectPreference).delete()
        db.query(models.ClassroomClassPreference).delete()
        db.query(models.ClassroomUnavailability).delete()
        db.query(models.ClassroomTagAssignment).delete()
        db.query(models.Classroom).delete()
        db.commit()
        # Cache to avoid re-querying for repeated tag names.
        tag_id_by_name: dict[str, int] = {
            t.name: t.id
            for t in db.query(models.ClassroomTag).all()
        }
        for r in recipe:
            cr = models.Classroom(
                name=r["name"], kind=r["kind"],
                capacity=r["capacity"],
                multi_class=r["multi_class"],
                multi_class_max=r["multi_class_max"],
                multi_class_pref=r["multi_class_pref"],
            )
            db.add(cr)
            db.flush()
            for subj in r.get("subject_required", []):
                db.add(models.ClassroomSubjectPreference(
                    classroom_id=cr.id, subject=subj,
                    # `state` e\` la fonte di verita\`: scrivere solo
                    # `required=True` non funziona, perche\` il listener
                    # `_sync_csp_required` lo ricalcola da `state` (che
                    # senza questo argomento resterebbe 'allowed') e lo
                    # riporta a False. I laboratori uscivano quindi
                    # senza alcuna restrizione di materia.
                    state="enforced", weight=10.0,
                ))
            home = r.get("is_home_for_class")
            if home:
                db.add(models.ClassroomClassPreference(
                    classroom_id=cr.id, class_name=home,
                    weight=20.0, is_home=True,
                ))
            # Auto-tag based on the recipe (kind + curriculum hints +
            # common Italian subjects). The mock-school workflow ends
            # up with a fully-tagged set out of the box.
            for tname in r.get("tags", []) or []:
                tname_l = (tname or "").strip().lower()
                if not tname_l:
                    continue
                tid = tag_id_by_name.get(tname_l)
                if tid is None:
                    new_tag = models.ClassroomTag(name=tname_l)
                    db.add(new_tag)
                    db.flush()
                    tid = new_tag.id
                    tag_id_by_name[tname_l] = tid
                db.add(models.ClassroomTagAssignment(
                    classroom_id=cr.id, tag_id=tid,
                ))
            out["created"] += 1
        db.commit()
    return out
