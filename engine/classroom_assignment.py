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
          'shares_room': bool,      # compresenza: vedi sotto
        }
    classrooms: list di dict
        {
          'name':           str,
          'kind':           str,    # standard / lab_* / palestra / ...
          'capacity':       int,
          'multi_class':    bool,
          'multi_class_max':int,    # HARD: max classi simultanee
          'unavailability': set[(day, hour)],
          'subject_required': set[str],   # HARD: solo queste materie
          'subject_forbidden':set[str],   # HARD: tutte tranne queste
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
- Compresenze su materia DIVERSA (sostegno, potenziamento, ITP,
  madrelingua): la chiave sopra non basta, perche\` la lezione del
  docente in compresenza porta un'altra `subject` e diventerebbe una
  seconda richiesta d'aula per la stessa classe nella stessa ora. Chi
  porta `shares_room=True` viene percio\` escluso dal modello e riceve
  a valle l'aula dell'ospite (vedi `compresenza_map`). Senza questo, in
  una scuola con molto sostegno il modello e\` insoddisfacibile: le
  richieste d'aula superano le celle realmente esistenti.
  Attenzione: NON si puo\` dedurre la regola da "stessa classe, stessa
  ora", perche\` gli sdoppiamenti veri (Religione / Attivita\`
  alternativa, gruppi di lingua) mettono davvero la classe in due aule.
  Serve il dato esplicito, che il backend deriva da
  `Teacher.compresenza`.
- Lab-required: se l'aula ha `subject_required` non vuoto, accetta solo
  lezioni con subject in quell'insieme. Le altre lezioni NON possono
  essere assegnate a quell'aula.
- Required-kind (HARD): se la lezione porta `required_kind` non vuoto
  (es. 'palestra' per Educazione Fisica), la lezione e\` ammessa solo
  nelle aule con `kind` corrispondente. La chiave viene popolata da
  `Subject.required_kind` nel webui-side `lessons_for_classroom_step`.
- Capacit\`a (HARD): se la lezione porta `n_students > 0` la lezione e\`
  ammessa solo nelle aule con `capacity >= n_students`. Lezioni senza
  `n_students` (chiave assente o 0) bypassano il vincolo - usato
  storicamente quando i dati di classe non includevano lo studente
  count.
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

try:
    from . import solver_config as _solvercfg  # type: ignore
except ImportError:  # direct script import (no package context)
    import solver_config as _solvercfg  # type: ignore


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
    out.setdefault("subject_forbidden", set())
    out.setdefault("subject_pref_weight", {})
    out.setdefault("class_pref_weight", {})
    out.setdefault("is_home_for", set())
    return out


def _can_host(room: dict, lesson: dict) -> bool:
    """HARD eligibility: subject compatibility + capacity + required-
    kind + aula base + room not unavailable on that slot."""
    subj = lesson["subject"]
    day = lesson["day"]
    hour = lesson["hour"]
    if (day, hour) in room["unavailability"]:
        return False
    # HARD divieto per classe: assoluto, non deroga per nessuna materia.
    if room["name"] in (lesson.get("forbidden_rooms") or ()):
        return False
    # Lab-required rooms only accept their subjects
    if room["subject_required"] and subj not in room["subject_required"]:
        return False
    # HARD divieto per materia (state='forbidden'): l'opposto del
    # precedente -- l'aula accetta tutto TRANNE queste materie.
    if subj in room["subject_forbidden"]:
        return False
    # HARD subject->kind: when the lesson carries a non-empty
    # `required_kind`, the room must match. e.g. Educazione Fisica
    # (required_kind='palestra') rejects every non-palestra room.
    req_kind = lesson.get("required_kind") or ""
    if req_kind and str(room.get("kind", "standard")) != req_kind:
        return False
    # HARD aula base: la lezione porta `home_room` quando la classe ha
    # il preset 'fissa' (o una riga 'enforced'), e allora nessun'altra
    # aula e\` ammessa.
    #
    # La deroga per `req_kind` non e\` una comodita\`: senza di essa il
    # preset sarebbe insoddisfacibile in qualunque scuola con una
    # palestra, perche\` Scienze motorie chiederebbe insieme l'aula base
    # e un'aula di tipo palestra. Le due regole vivono su assi diversi
    # -- la materia vince sulla classe.
    home_room = lesson.get("home_room") or ""
    if home_room and not req_kind and room["name"] != home_room:
        return False
    # HARD capacity: room.capacity >= class.n_students. Skipped silently
    # when the lesson doesn't carry n_students (legacy callers).
    n_stud = int(lesson.get("n_students") or 0)
    if n_stud > 0 and int(room.get("capacity", 0) or 0) < n_stud:
        return False
    return True


def _lesson_key(L: dict) -> tuple[str, str, int, int]:
    return (L["class"], L["subject"], int(L["day"]), int(L["hour"]))


def compresenza_map(lessons: list[dict]) -> dict[tuple, tuple]:
    r"""Chi si accoda a chi per l'aula.

    Ritorna ``{lesson_key_che_segue -> lesson_key_ospite}``. Le chiavi
    presenti NON devono ricevere un'aula propria: prendono quella
    dell'ospite, perche\` una compresenza e\` per definizione due docenti
    nella stessa stanza.

    La regola NON e\` "stessa classe + stessa ora => stessa aula": gli
    sdoppiamenti veri (Religione / Attivita\` alternativa, gruppi di
    lingua) dividono la classe fra due aule ed e\` giusto che chiedano
    due stanze. Si accoda solo chi porta ``shares_room=True``, che il
    backend deriva da ``Teacher.compresenza``.

    Due precisazioni che sembrano dettagli e non lo sono:

    - ``shares_room`` e\` una proprieta\` del docente, quindi e\` vera
      anche nelle ore in cui quel docente ha una cattedra tutta sua. Per
      questo ci si accoda SOLO se nella cella esiste un'altra lezione:
      da soli si prenota un'aula normalmente.
    - se nella cella ci sono solo lezioni in compresenza e nessun
      ospite (nessuno "titolare"), una viene promossa a ospite e le
      altre la seguono, invece di chiedere N stanze.
    """
    rides_by_key: dict[tuple, bool] = {}
    cells: dict[tuple[str, int, int], list[tuple]] = {}
    for L in lessons:
        key = _lesson_key(L)
        rides = bool(L.get("shares_room"))
        if key in rides_by_key:
            # Stessa chiave, piu\` docenti (codocenza sulla stessa
            # materia): e\` gia\` una sola lezione e una sola aula. Conta
            # come ospite se almeno uno dei suoi docenti non si accoda.
            rides_by_key[key] = rides_by_key[key] and rides
            continue
        rides_by_key[key] = rides
        cells.setdefault((L["class"], int(L["day"]), int(L["hour"])),
                         []).append(key)

    riders: dict[tuple, tuple] = {}
    for _cell, keys in cells.items():
        if len(keys) < 2:
            continue
        rider_keys = [k for k in keys if rides_by_key[k]]
        if not rider_keys:
            continue
        hosts = [k for k in keys if not rides_by_key[k]]
        if hosts:
            host = hosts[0]
        else:
            host, rider_keys = rider_keys[0], rider_keys[1:]
        for k in rider_keys:
            riders[k] = host
    return riders


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

    # Compresenze: chi si accoda non entra nel modello, riceve a valle
    # l'aula del suo ospite.
    riders = compresenza_map(lessons)

    # Build the locked-room map keyed by lesson_key. Un lock su una
    # lezione in compresenza vale in realta\` per l'ospite: e\` la stessa
    # stanza, e la chiave della lezione accodata non esiste nel modello.
    locks_by_lesson: dict[tuple, str] = {}
    for entry in (locked_classrooms or []):
        if len(entry) != 5:
            continue
        cl_l, s_l, d_l, h_l, room_name = entry
        if not room_name:
            continue
        key = (cl_l, s_l, int(d_l), int(h_l))
        locks_by_lesson[riders.get(key, key)] = room_name

    # Group lessons by (class, subject, day, hour) — multiple co-teachers
    # share one lesson and one room.
    lesson_keys: list[tuple[str, str, int, int]] = []
    seen = set()
    for L in lessons:
        key = _lesson_key(L)
        if key in seen or key in riders:
            continue
        seen.add(key)
        lesson_keys.append(key)

    # Sanity: each lesson_key must have at least one eligible room.
    eligible: dict[tuple, list[str]] = {}
    for L in lessons:
        key = _lesson_key(L)
        if key in eligible or key in riders:
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
            key = _lesson_key(L)
            # I docenti in compresenza stanno nell'aula dell'ospite,
            # quindi ai fini di plesso e spostamenti contano su quella.
            key = riders.get(key, key)
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
            # `b` e\` una magnitudine positiva: "quanto e\` gradita questa
            # aula". Il segno viene normalizzato all'origine da
            # engine_io, dove `state` e\` la fonte di verita\` e il segno
            # della colonna `weight` non lo e\` (la UI scrive -20 per
            # 'preferred', il generatore mock +10). Il modello minimizza,
            # quindi il bonus entra negato.
            if b:
                bonus_terms.append(-int(round(b)) * x[(key, rn)])

    # Objective: minimize overflow penalty - bonuses
    objective_terms = list(overflow_terms) + list(bonus_terms)
    if objective_terms:
        model.Minimize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_search_workers = workers
    solver.parameters.log_search_progress = log
    t0 = time.time()
    _solvercfg.configure_solver(solver)
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
    # Le lezioni in compresenza ereditano l'aula dell'ospite.
    for rider_key, host_key in riders.items():
        if host_key in out:
            out[rider_key] = out[host_key]
    print(
        f"[classroom] status={solver.StatusName(status)} "
        f"elapsed={elapsed:.1f}s lessons={len(lesson_keys)} "
        f"rooms={len(rooms)}"
        + (f" compresenze={len(riders)}" if riders else "")
        + (f" plessi(commute={n_pl_commute}, policy={n_pl_policy})"
           if (n_pl_commute or n_pl_policy) else "")
    )
    return out, solver.StatusName(status)


def add_joint_room_vars(
    model,
    cell_occ: dict[tuple, Any],
    cell_lessons: dict[tuple, dict],
    classrooms: list[dict],
    *,
    soft_weights: dict[str, float] | None = None,
    plessi_data=None,
    candidate_rooms: dict | None = None,
    want_home_bonus: bool = True,
    want_room_pref: bool = True,
    want_overflow: bool = True,
    want_plessi: bool = True,
) -> tuple[dict, list, dict]:
    r"""Fonde l'assegnazione delle aule dentro un modello di orario GIA\`
    esistente -- il modello *joint* (giorno, ora, aula) in un solo solve.

    ``cell_occ[(cl, subj, d, h)]`` e\` l'indicatore di occupazione della
    cella prodotto dal modello di orario (una BoolVar dello scheduler, o
    il letterale ``1`` per una cella fissata da un lock): e\` questo che
    rende la scelta dell'aula CONGIUNTA con quella dello slot. Per ogni
    cella emettiamo le var aula con ``sum_r x[cell, r] == cell_occ[cell]``,
    cosi\` una lezione consuma un'aula solo quando e\` davvero collocata li\`,
    e il solutore puo\` spostare una lezione a un'altra ora per soddisfare
    un vincolo di aula / plesso / capienza (cosa che il passo aule
    sequenziale, a orario congelato, non puo\` fare).

    ``cell_lessons[(cl, subj, d, h)]`` porta i metadati che ``_can_host``
    consuma (``home_room``, ``forbidden_rooms``, ``required_kind``,
    ``n_students``, ``teacher``, ``co_teachers``). Le celle in compresenza
    (``shares_room``) NON vanno passate: ereditano a valle l'aula
    dell'ospite, esattamente come nel solutore aule standalone.

    Ritorna ``(x, obj_terms, info)``. ``obj_terms`` sono termini di
    MINIMIZZAZIONE (i bonus sono gia\` negati) che il chiamante folda nel
    proprio obiettivo; i flag ``want_*`` permettono di escludere un
    singolo termine dall'ottimizzazione senza toccare i vincoli HARD.
    """
    soft = dict(soft_weights or {})
    soft.setdefault("home_bonus", 20.0)
    soft.setdefault("subject_pref_bonus", 10.0)
    soft.setdefault("class_pref_bonus", 10.0)
    soft.setdefault("multi_class_overflow", 30.0)

    rooms = [_normalize_classroom(r) for r in classrooms]
    room_by_name = {r["name"]: r for r in rooms}

    # HARD eligibility per cella; una cella senza aule ammissibili non puo\`
    # mai essere occupata -> forziamo occ == 0 (vincolo joint: non
    # collocare li\` una lezione che nessuna aula puo\` ospitare).
    eligible: dict[tuple, list[str]] = {}
    no_room_cells: list[tuple] = []
    for cell, L in cell_lessons.items():
        elig = [r["name"] for r in rooms if _can_host(r, L)]
        # Pruning: restrict an ORDINARY lesson to its class' candidate pool
        # (home + a few alternates in-plesso) so the model does not carry a
        # var per (cell, every interchangeable room). Special-kind lessons
        # (gym/lab) keep their required-kind rooms. Never prune to empty --
        # if the pool intersects nothing, keep the full eligible set.
        if candidate_rooms and not (L.get("required_kind") or ""):
            pool = candidate_rooms.get(L.get("class") or "")
            if pool:
                pruned = [rn for rn in elig if rn in pool]
                if pruned:
                    elig = pruned
        eligible[cell] = elig
        if not elig:
            no_room_cells.append(cell)

    x: dict[tuple, Any] = {}
    for cell, occ in cell_occ.items():
        elig = eligible.get(cell, [])
        if not elig:
            # Nessuna aula: la cella non puo\` essere occupata.
            model.Add(occ == 0)
            continue
        for rn in elig:
            x[(cell, rn)] = model.NewBoolVar(f"jx_{rn}_{cell}")
        # Esattamente un'aula SE la cella e\` occupata, zero altrimenti.
        model.Add(sum(x[(cell, rn)] for rn in elig) == occ)

    # Capienza per (aula, giorno, ora): al piu\` multi_class_max celle.
    by_slot: dict[tuple[str, int, int], list[tuple]] = defaultdict(list)
    for (cell, rn) in x:
        _cl, _s, d, h = cell
        by_slot[(rn, d, h)].append(cell)
    overflow_terms: list[Any] = []
    for (rn, d, h), cells in by_slot.items():
        room = room_by_name[rn]
        max_c = room["multi_class_max"] if room["multi_class"] else 1
        terms = [x[(c, rn)] for c in cells]
        model.Add(sum(terms) <= max_c)
        pref = max(1, int(room["multi_class_pref"]))
        if want_overflow and pref < max_c:
            ov = model.NewIntVar(0, max_c - pref, f"jov_{rn}_{d}_{h}")
            model.Add(ov >= sum(terms) - pref)
            overflow_terms.append(
                int(soft["multi_class_overflow"] *
                    room["multi_class_pref_weight"]) * ov
            )

    # Bonus SOFT (negati, il modello minimizza): home-room + preferenze.
    bonus_terms: list[Any] = []
    if want_home_bonus or want_room_pref:
        for (cell, rn), var in x.items():
            cl, subj, _d, _h = cell
            room = room_by_name[rn]
            b = 0.0
            if want_home_bonus and cl in room["is_home_for"]:
                b += soft["home_bonus"]
            if want_room_pref and subj in room["subject_pref_weight"]:
                b += float(room["subject_pref_weight"][subj]) * \
                     soft["subject_pref_bonus"] / 10.0
            if want_room_pref and cl in room["class_pref_weight"]:
                b += float(room["class_pref_weight"][cl]) * \
                     soft["class_pref_bonus"] / 10.0
            if b:
                bonus_terms.append(-int(round(b)) * var)

    # Plessi (commuting + policy): riusa gli stessi helper del solutore
    # standalone, che ragionano su ``x`` e ``eligible`` -- validi anche qui
    # perche\` una cella non occupata ha ``sum_r x == 0`` (nessun plesso).
    n_pl_commute = 0
    n_pl_policy = 0
    if (want_plessi and plessi_data is not None
            and getattr(plessi_data, "classroom_to_plesso", None)):
        teacher_for_lesson: dict[tuple, list[str]] = {}
        for cell, L in cell_lessons.items():
            t_list = teacher_for_lesson.setdefault(cell, [])
            if L.get("teacher"):
                t_list.append(L["teacher"])
            for ct in L.get("co_teachers") or []:
                if ct and ct not in t_list:
                    t_list.append(ct)
        days_set = sorted({c[2] for c in cell_occ})
        hours_set = sorted({c[3] for c in cell_occ})
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

    obj_terms = list(overflow_terms) + list(bonus_terms)
    info = {
        "n_cells": len(cell_occ),
        "n_room_vars": len(x),
        "no_room_cells": no_room_cells,
        "n_plessi_commute": n_pl_commute,
        "n_plessi_policy": n_pl_policy,
    }
    return x, obj_terms, info


def add_room_continuity_constraints(
    model,
    x: dict,
    cell_lessons: dict,
    modes: dict,
    *,
    weight: int = 40,
) -> list:
    r"""Room-continuity requirements on the JOINT room vars ``x`` (from
    :func:`add_joint_room_vars`). A class should change room as seldom as
    possible: this models that as HARD or SOFT, per class.

    ``modes`` is ``{class_name -> "day" | "week" | "soft"}``:

    * ``"day"``  -- HARD: all the class' ORDINARY lessons in one day sit
      in the SAME room (it may still change from day to day).
    * ``"week"`` -- HARD: the same ordinary room for the WHOLE week (the
      ``fissa`` preset, derived rather than pinned to a named room).
    * ``"soft"`` -- SOFT: minimise the number of DISTINCT ordinary rooms
      the class uses over the week (``weight`` per extra room).

    Lessons carrying a ``required_kind`` (gym / lab) are EXEMPT: forcing
    Scienze motorie into the class' ordinary room would be infeasible.
    They are simply not tied to the class' continuity room -- the same
    derogation ``room_policy='fissa'`` already grants via ``_can_host``.

    Returns SOFT objective terms (minimised; empty for HARD-only modes),
    which the caller folds into the joint objective.
    """
    if not modes:
        return []
    # Index x vars by class -> only ORDINARY cells (no required_kind).
    by_class_day: dict[tuple, list] = defaultdict(list)   # (cl,d) -> [(cell,r,var)]
    by_class: dict[str, list] = defaultdict(list)         # cl -> [(cell,r,var)]
    rooms_by_class: dict[str, set] = defaultdict(set)
    for (cell, rn), var in x.items():
        cl, subj, d, h = cell
        if cl not in modes:
            continue
        if (cell_lessons.get(cell, {}).get("required_kind") or ""):
            continue  # special-kind lesson: exempt from ordinary continuity
        by_class_day[(cl, d)].append((cell, rn, var))
        by_class[cl].append((cell, rn, var))
        rooms_by_class[cl].add(rn)

    obj_terms: list = []
    for cl, mode in modes.items():
        rnames = sorted(rooms_by_class.get(cl, ()))
        if len(rnames) <= 1:
            continue  # 0/1 candidate room -> nothing to constrain
        if mode == "day":
            days = sorted({d for (c, d) in by_class_day if c == cl})
            for d in days:
                triples = by_class_day.get((cl, d), [])
                if not triples:
                    continue
                use = {}
                for rn in rnames:
                    ur = model.NewBoolVar(f"crd_{cl}_{d}_{rn}")
                    use[rn] = ur
                for (cell, rn, var) in triples:
                    model.Add(var <= use[rn])
                model.Add(sum(use.values()) <= 1)
        elif mode == "week":
            use = {}
            for rn in rnames:
                ur = model.NewBoolVar(f"crw_{cl}_{rn}")
                use[rn] = ur
            for (cell, rn, var) in by_class.get(cl, []):
                model.Add(var <= use[rn])
            model.Add(sum(use.values()) <= 1)
        elif mode == "soft":
            use = {}
            for rn in rnames:
                ur = model.NewBoolVar(f"crs_{cl}_{rn}")
                use[rn] = ur
                obj_terms.append(int(weight) * ur)
            for (cell, rn, var) in by_class.get(cl, []):
                model.Add(var <= use[rn])
    return obj_terms


def _plesso_pins(plessi_data) -> dict[tuple[str, int], int]:
    r"""``{('class'|'teacher', entity_id) -> plesso_id}`` per le policy
    che inchiodano un'entita\` a un plesso preciso."""
    pins: dict[tuple[str, int], int] = {}
    for p in (getattr(plessi_data, "entity_policies", None) or []):
        if p.entity_id is None or p.plesso_id is None:
            continue
        if p.policy in ("single_plesso_total", "single_plesso_per_day"):
            pins[(p.entity_kind, int(p.entity_id))] = int(p.plesso_id)
    return pins


def greedy_classroom_assignment(
    lessons: list[dict],
    classrooms: list[dict],
    *,
    prefer_home: bool = True,
    locked_classrooms: list[tuple] | None = None,
    plessi_data=None,
) -> dict:
    r"""Fallback greedy: per slot, prefer the lesson's home room if free.
    Used when CP-SAT is unnecessary or as a warm start.

    `locked_classrooms` (optional): list of
    (class, subject, day, hour, classroom_name) tuples. The greedy
    pre-assigns those slots first so any subsequent placement
    treats the locked room as occupied (counted in `busy`). Locks
    pointing at an ineligible room are still emitted so the upstream
    _apply_locked_classrooms step has the right answer; the
    capacity bookkeeping for that slot is bumped regardless.

    `plessi_data` (optional): stesso oggetto passato al modello esatto.
    Il greedy ne usa la parte che si puo\` rispettare decidendo una
    lezione alla volta:

    - HARD, le policy che inchiodano una classe (o un docente) a un
      plesso: le aule degli altri plessi vengono scartate;
    - preferenza forte per la CONTINUITA\`, cioe\` restare nel plesso in
      cui la classe si trova gia\` quel giorno.

    Le regole di pendolarismo (`commuting_rules`, con i loro intervalli
    minimi fra due spostamenti) NON sono modellate qui: richiedono di
    guardare avanti e indietro nella giornata, cosa che un greedy per
    slot non fa. Restano garantite solo dal ramo CP-SAT. Questa
    funzione e\` una rete di sicurezza per quando il modello esatto non
    conclude, non un suo sostituto.
    """
    rooms = [_normalize_classroom(r) for r in classrooms]
    out: dict = {}
    busy: dict[tuple[str, int, int], int] = defaultdict(int)
    by_key: dict[tuple, dict] = {}
    riders = compresenza_map(lessons)
    for L in lessons:
        key = _lesson_key(L)
        if key in riders:
            continue
        by_key.setdefault(key, L)

    room_plesso = dict(
        getattr(plessi_data, "classroom_to_plesso", None) or {})
    class_ids = dict(getattr(plessi_data, "class_name_to_id", None) or {})
    teacher_ids = dict(
        getattr(plessi_data, "teacher_name_to_id", None) or {})
    pins = _plesso_pins(plessi_data) if plessi_data is not None else {}
    # Plesso in cui ogni classe si trova gia\`, quel giorno.
    day_plesso: dict[tuple[str, int], int] = {}

    def _pinned_plesso(L: dict, cl: str) -> int | None:
        cid = class_ids.get(cl)
        if cid is not None and ("class", cid) in pins:
            return pins[("class", cid)]
        for tname in ([L.get("teacher")] + list(L.get("co_teachers") or [])):
            tid = teacher_ids.get(tname) if tname else None
            if tid is not None and ("teacher", tid) in pins:
                return pins[("teacher", tid)]
        return None

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
        key = riders.get(key, key)
        out[key] = room_name
        busy[(room_name, int(d_l), int(h_l))] += 1
        locked_keys.add(key)
        pl = room_plesso.get(room_name)
        if pl is not None:
            day_plesso.setdefault((key[0], int(d_l)), pl)

    for key in sorted(by_key):
        if key in locked_keys:
            continue
        L = by_key[key]
        cl, subj, d, h = key
        candidates = [r for r in rooms if _can_host(r, L)]
        pin = _pinned_plesso(L, cl)
        if pin is not None:
            hard = [r for r in candidates
                    if room_plesso.get(r["name"]) == pin]
            # Se il vincolo di plesso non lascia nessuna aula, meglio
            # collocare la lezione altrove che lasciarla senza aula:
            # il greedy e\` gia\` il ramo degradato.
            candidates = hard or candidates
        if not candidates:
            continue
        want_plesso = day_plesso.get((cl, d), pin)

        def _fits(room: dict) -> bool:
            cap = room["multi_class_max"] if room["multi_class"] else 1
            return busy[(room["name"], d, h)] < cap

        def _place(room: dict) -> None:
            out[key] = room["name"]
            busy[(room["name"], d, h)] += 1
            pl = room_plesso.get(room["name"])
            if pl is not None:
                day_plesso.setdefault((cl, d), pl)

        if prefer_home:
            home = [r for r in candidates if cl in r["is_home_for"]]
            if home and _fits(home[0]):
                _place(home[0])
                continue
        # Preferenze: prima restare nel plesso della giornata, poi le
        # materie che quell'aula gradisce (magnitudine positiva, vedi
        # engine_io), infine le aule non condivise.
        candidates.sort(key=lambda r: (
            0 if (want_plesso is not None
                  and room_plesso.get(r["name"]) == want_plesso) else 1,
            -float(r["subject_pref_weight"].get(subj, 0.0)),
            r["multi_class"],  # avoid multi-class rooms first
        ))
        for room in candidates:
            if _fits(room):
                _place(room)
                break

    for rider_key, host_key in riders.items():
        if host_key in out:
            out[rider_key] = out[host_key]
    return out
