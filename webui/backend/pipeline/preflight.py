"""Pre-flight checks run before every solver launch.

Lock-set consistency, coteach/sostegno/potenziamento/group invariants,
and PLESSI configuration. Called synchronously so a bad config is a
400 on POST, not a failed background run.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import engine_io, models
from ..db import SessionLocal


def _locked_day_count_from_snapshot(snapshot: list[dict]
                                     ) -> dict[tuple, int]:
    """Aggregate a Lesson-level snapshot into a Phase A floor:
    {(teacher_name, class_name, subject, day) -> n_locked_in_that_day}.
    Used by the native-lock CP-SAT path: each entry becomes a
    `model.Add(day_count[k] >= n)` constraint."""
    out: dict[tuple, int] = {}
    for snap in snapshot:
        if snap.get("day") is None or snap.get("hour") is None:
            continue
        k = (snap["teacher_name"], snap["class_name"],
             snap["subject"], int(snap["day"]))
        out[k] = out.get(k, 0) + 1
    return out


def _locked_slots_by_day(snapshot: list[dict]
                          ) -> dict[int, list[tuple]]:
    """Group a Lesson-level snapshot by day into the
    `(prof, class, subject, hour)` tuples consumed by
    solve_phase_b_for_day's `locked_slots_for_day` parameter."""
    out: dict[int, list[tuple]] = {}
    for snap in snapshot:
        if snap.get("day") is None or snap.get("hour") is None:
            continue
        d = int(snap["day"])
        out.setdefault(d, []).append((
            snap["teacher_name"], snap["class_name"],
            snap["subject"], int(snap["hour"]),
        ))
    return out



def _apply_locked_classrooms(db: Session, solution_id: int,
                              snapshot: list[dict]) -> int:
    """After a NATIVE-lock solve, the day/hour of each locked Lesson
    is already correct (the solver enforced it). This helper just
    re-applies the locked classroom_name and cotaught_with attributes
    to the matching Lesson rows. No deletion, no relocation -- the
    solver did the heavy lifting.
    """
    if not snapshot:
        return 0
    n_touched = 0
    for snap in snapshot:
        if snap.get("day") is None or snap.get("hour") is None:
            continue
        l = db.query(models.Lesson).filter(
            models.Lesson.solution_id == solution_id,
            models.Lesson.teacher_name == snap["teacher_name"],
            models.Lesson.class_name == snap["class_name"],
            models.Lesson.subject == snap["subject"],
            models.Lesson.day == int(snap["day"]),
            models.Lesson.hour == int(snap["hour"]),
        ).first()
        if l is None:
            # Should not happen with native locks; if it does, the
            # solver returned INFEASIBLE earlier or an upstream error
            # dropped the Lesson. Skip silently and let the caller
            # decide based on the run's status.
            continue
        if snap.get("classroom_name"):
            l.classroom_name = snap["classroom_name"]
        if snap.get("cotaught_with"):
            l.cotaught_with = snap["cotaught_with"]
        # Carry the pin forward: the snapshot only ever holds genuinely
        # pinned lessons now, so the re-placed copy stays pinned across
        # successive regenerations (finding 26 -- incremental work).
        l.locked = True
        n_touched += 1
    return n_touched

# Engine HARD constants mirrored here so the pre-flight check
# doesn't need to import the CP-SAT module just to read them.
_LOCK_MAX_PER_DAY_TRIPLE = 2     # max ore stessa cattedra/giorno
_LOCK_MAX_PER_DAY_PROF_CL = 3    # max ore (prof, class)/giorno
_LOCK_MAX_PROF_HOURS_PER_DAY = 5 # max ore prof/giorno


def validate_locks_vs_constraints(snapshot: list[dict]) -> list[str]:
    """Pre-flight check: detect locks that already violate the
    structural HARD constraints of the engine, BEFORE spending a
    minute on the solver only to get an INFEASIBLE message.

    Returns a list of human-readable violation strings; empty list
    means the lock set is consistent with the HARD constraints we
    can check at this layer.

    Catches:
      - >MAX_PER_DAY_TRIPLE locks for the same cattedra in one day
      - >MAX_PER_DAY_PROF_CL locks for the same (prof, class) in one
        day
      - >MAX_PROF_HOURS_PER_DAY locks for the same prof in one day
      - two locks at the same (class, day, hour) but with different
        teachers (a class cannot be in two lessons at once)
      - two locks at the same (prof, day, hour) (a prof cannot be
        in two classes at once)
      - two locks with the same classroom_name at the same
        (day, hour) but different (class, subject), unless the
        classroom is multi_class -- but we don't have the
        Classroom row here so we just flag it; the engine layer
        will resolve / accept multi_class as appropriate.

    Does NOT catch:
      - free_day collisions (the engine free_day is a 3-way choice;
        the solver will pick a different candidate when one is
        locked)
      - hard_motorie_pairs / hard_dual_math etc. -- these are
        per-class flags that interact with the structure of
        day_count and are non-trivial to reproduce here. The
        engine returns a clear INFEASIBLE message when violated.
    """
    if not snapshot:
        return []
    violations: list[str] = []

    by_triple_day: dict[tuple, int] = {}
    by_profcl_day: dict[tuple, int] = {}
    by_prof_day: dict[tuple, int] = {}
    by_class_slot: dict[tuple, list[tuple]] = {}
    by_prof_slot: dict[tuple, list[tuple]] = {}
    by_room_slot: dict[tuple, list[tuple]] = {}

    for snap in snapshot:
        if snap.get("day") is None or snap.get("hour") is None:
            continue
        t = snap["teacher_name"]
        c = snap["class_name"]
        s = snap["subject"]
        d = int(snap["day"])
        h = int(snap["hour"])
        room = snap.get("classroom_name")

        by_triple_day[(t, c, s, d)] = by_triple_day.get((t, c, s, d), 0) + 1
        by_profcl_day[(t, c, d)] = by_profcl_day.get((t, c, d), 0) + 1
        by_prof_day[(t, d)] = by_prof_day.get((t, d), 0) + 1
        by_class_slot.setdefault((c, d, h), []).append((t, s))
        by_prof_slot.setdefault((t, d, h), []).append((c, s))
        if room:
            by_room_slot.setdefault((room, d, h), []).append((c, s, t))

    for (t, c, s, d), n in by_triple_day.items():
        if n > _LOCK_MAX_PER_DAY_TRIPLE:
            violations.append(
                f"cattedra {t}/{c}/{s} ha {n} lock in giorno {d} "
                f"ma il massimo per cattedra/giorno e' "
                f"{_LOCK_MAX_PER_DAY_TRIPLE}"
            )
    for (t, c, d), n in by_profcl_day.items():
        if n > _LOCK_MAX_PER_DAY_PROF_CL:
            violations.append(
                f"docente {t} in classe {c} ha {n} lock in giorno {d} "
                f"ma il massimo per (docente,classe)/giorno e' "
                f"{_LOCK_MAX_PER_DAY_PROF_CL}"
            )
    for (t, d), n in by_prof_day.items():
        if n > _LOCK_MAX_PROF_HOURS_PER_DAY:
            violations.append(
                f"docente {t} ha {n} lock in giorno {d} "
                f"ma il massimo per docente/giorno e' "
                f"{_LOCK_MAX_PROF_HOURS_PER_DAY}"
            )
    for (c, d, h), entries in by_class_slot.items():
        teachers = {e[0] for e in entries}
        if len(teachers) > 1:
            violations.append(
                f"classe {c} ha {len(entries)} lock simultanei in "
                f"giorno {d} ora {h} ({sorted(teachers)}): la classe "
                f"non puo' stare in piu' lezioni contemporaneamente"
            )
    for (t, d, h), entries in by_prof_slot.items():
        classes = {e[0] for e in entries}
        if len(classes) > 1:
            violations.append(
                f"docente {t} ha {len(entries)} lock simultanei in "
                f"giorno {d} ora {h} ({sorted(classes)}): il docente "
                f"non puo' stare in piu' classi contemporaneamente"
            )
    for (room, d, h), entries in by_room_slot.items():
        if len(entries) > 1:
            classes = {e[0] for e in entries}
            if len(classes) > 1:
                violations.append(
                    f"aula {room} ha {len(entries)} lock simultanei in "
                    f"giorno {d} ora {h} ({sorted(classes)}): se l'aula "
                    f"non e' multi_class l'engine restituira' "
                    f"INFEASIBLE")
    return violations

def _snapshot_and_validate_locks(db: Session) -> list[dict]:
    """Read the locked-Lesson snapshot AND run the pre-flight
    validation. If the lock set violates a structural HARD,
    raise RuntimeError with a multi-line message listing every
    violation, BEFORE the solver thread is spawned. The router's
    HTTPException handler maps RuntimeError to a 400 with code
    `engine_error`.
    """
    snap = _read_locked_lessons(db)
    if snap:
        violations = validate_locks_vs_constraints(snap)
        if violations:
            raise RuntimeError(
                "Lock incompatibili con i vincoli HARD attuali: "
                + "; ".join(violations)
                + ". Sblocca le lezioni in conflitto o rimuovi i "
                  "vincoli incompatibili e riprova."
            )
    return snap

def validate_coteach_sostegno_potenziamento(db: Session) -> list[str]:
    """Pre-flight check for the Task C1 schema additions. Catches:

    - CoteachGroup.n_hours > principal teacher's Assignment.hours.
    - CoteachGroup.n_hours != codoc's Assignment.hours (codoc is
      supposed to have exactly n_hours of weekly hours -- all in
      compresenza).
    - Support assignment with no schedulable target: no pupil, no
      group and no class, or a pupil who isn't in any class (there
      would be no lessons to shadow).
    - Potenziamento assignment with class_id set (malformed).
    - Potenziamento total per teacher > 30 (5 hours/day * 6 days).
    """
    violations: list[str] = []
    teachers_by_id = {t.id: t for t in db.query(models.Teacher).all()}
    classes_by_id = {c.id: c for c in db.query(models.SchoolClass).all()}

    # Coteach groups
    for g in db.query(models.CoteachGroup).all():
        members = db.query(models.Assignment).filter(
            models.Assignment.coteach_group_id == g.id
        ).all()
        if not members:
            continue
        members_sorted = sorted(
            members,
            key=lambda a: (-int(a.hours or 0),
                            teachers_by_id.get(a.teacher_id).name
                            if a.teacher_id in teachers_by_id else ""),
        )
        principal = members_sorted[0]
        if g.n_hours > (principal.hours or 0):
            cl = classes_by_id.get(g.class_id)
            cn = cl.name if cl else f"#{g.class_id}"
            violations.append(
                f"compresenza ({cn}, {g.subject}): n_hours={g.n_hours} "
                f"> ore principale ({principal.hours})"
            )
        for codoc in members_sorted[1:]:
            if (codoc.hours or 0) != g.n_hours:
                t = teachers_by_id.get(codoc.teacher_id)
                cn = (classes_by_id.get(g.class_id).name
                      if g.class_id in classes_by_id else "?")
                violations.append(
                    f"compresenza ({cn}, {g.subject}): codoc "
                    f"{t.name if t else codoc.teacher_id} ha "
                    f"{codoc.hours} ore ma il gruppo richiede "
                    f"esattamente {g.n_hours}"
                )

    # Support assignments
    _support_students = {s.id: s for s in db.query(models.Student).all()}
    for a in db.query(models.Assignment).filter(
        models.Assignment.is_support == True  # noqa: E712
    ).all():
        t = teachers_by_id.get(a.teacher_id)
        tn = t.name if t else f"#{a.teacher_id}"
        # A sostegno row targets a pupil (normal), a StudyGroup (Task
        # C3, the pupil followed into an articulated group) or -- for
        # rows predating the per-pupil model -- a bare class. Only a
        # row that resolves to none of the three is unschedulable.
        # The old check demanded class_id and so rejected every
        # group-targeted sostegno, blocking the whole run.
        if a.group_id is not None:
            continue
        if a.student_id is not None:
            st = _support_students.get(a.student_id)
            if st is None:
                violations.append(
                    f"sostegno {tn}: alunno #{a.student_id} "
                    f"inesistente."
                )
            elif st.class_id is None or st.class_id not in classes_by_id:
                violations.append(
                    f"sostegno {tn}: l'alunno "
                    f"{st.last_name} {st.first_name} non ha una "
                    f"classe, quindi non ci sono lezioni da seguire. "
                    f"Assegna l'alunno a una classe."
                )
            continue
        if a.class_id is None or a.class_id not in classes_by_id:
            violations.append(
                f"sostegno {tn}: nessun bersaglio (ne' alunno, ne' "
                f"gruppo, ne' classe). Associa il docente all'alunno "
                f"da seguire."
            )

    # Potenziamento assignments
    pot_by_teacher: dict[int, int] = {}
    for a in db.query(models.Assignment).filter(
        models.Assignment.is_potenziamento == True  # noqa: E712
    ).all():
        if a.class_id is not None:
            t = teachers_by_id.get(a.teacher_id)
            tn = t.name if t else f"#{a.teacher_id}"
            violations.append(
                f"potenziamento {tn}: ha class_id={a.class_id} ma "
                f"deve essere class_id NULL (cattedra senza classe)"
            )
        pot_by_teacher[a.teacher_id] = (
            pot_by_teacher.get(a.teacher_id, 0) + int(a.hours or 0))
    for tid, total in pot_by_teacher.items():
        if total > 30:
            t = teachers_by_id.get(tid)
            tn = t.name if t else f"#{tid}"
            violations.append(
                f"potenziamento {tn}: {total} ore > 30 (cap "
                f"settimanale; 5 ore/giorno x 6 giorni)"
            )

    # Task C3: group assignments validations.
    groups_by_id = {g.id: g for g in db.query(models.StudyGroup).all()}
    students_by_id = {s.id: s for s in db.query(models.Student).all()}
    for a in db.query(models.Assignment).filter(
        models.Assignment.group_id != None  # noqa: E711
    ).all():
        t = teachers_by_id.get(a.teacher_id)
        tn = t.name if t else f"#{a.teacher_id}"
        # XOR with class_id
        if a.class_id is not None:
            violations.append(
                f"gruppo {tn}: ha sia class_id={a.class_id} che "
                f"group_id={a.group_id}; XOR (esattamente una delle "
                f"due valorizzata)."
            )
        if a.group_id not in groups_by_id:
            violations.append(
                f"gruppo {tn}: group_id={a.group_id} inesistente."
            )
            continue
        g = groups_by_id[a.group_id]
        # Group must have at least one member
        members = db.query(models.GroupMembership).filter(
            models.GroupMembership.group_id == g.id
        ).all()
        if not members:
            violations.append(
                f"gruppo '{g.name}' (Assignment di {tn}): nessuno "
                f"studente assegnato. Aggiungi membri al gruppo "
                f"prima di creare un'Assignment di gruppo."
            )
        # All members must have a home class
        bad = [m.student_id for m in members
               if students_by_id.get(m.student_id) is None
               or students_by_id[m.student_id].class_id is None]
        if bad:
            violations.append(
                f"gruppo '{g.name}': {len(bad)} studenti senza "
                f"classe-madre; il solver non puo' propagare "
                f"class-busy."
            )
        # Hours sanity
        if (a.hours or 0) <= 0:
            violations.append(
                f"gruppo '{g.name}' (Assignment di {tn}): hours="
                f"{a.hours} non valido (deve essere > 0)."
            )
    return violations

def validate_plessi_rules(db: Session) -> list[str]:
    """Validate the consistency of PLESSI configuration:

    - Every PlessoCommutingRule references plessi that exist; if
      `entity_id` is set it must match a row of the kind given by
      `entity_kind`.
    - `min_gap_hours >= 0`; `break_start_hour <= break_end_hour`
      when both are set; if `allowed_break_only=True` then both
      break hours must be set.
    - PlessoEntityPolicy: `entity_id` (if set) refers to a teacher
      or class depending on `entity_kind` (groups are NOT in this
      table by design); `policy in {'any',
      'single_plesso_per_day', 'single_plesso_total'}`; if
      `policy == 'single_plesso_total'` and `plesso_id` is set the
      plesso must exist.
    - No two kind-wide rules for the same (from, to, kind) (this
      is NOT enforced by the DB UNIQUE constraint because SQL
      treats NULL entity_id as distinct).

    Returns a list of human-readable Italian error messages
    (empty on success).
    """
    violations: list[str] = []

    plesso_ids = {
        p.id for p in db.query(models.Plesso.id).all()
    } if db.bind.dialect.has_table(db.connection(), "plessi") else set()
    if not plesso_ids:
        return violations  # No plessi configured: no rules to validate.

    teacher_ids = {
        t.id for t in db.query(models.Teacher.id).all()
    }
    class_ids = {
        c.id for c in db.query(models.SchoolClass.id).all()
    }
    group_ids = {
        g.id for g in db.query(models.StudyGroup.id).all()
    } if hasattr(models, "StudyGroup") else set()

    # PlessoCommutingRule checks.
    rules = db.query(models.PlessoCommutingRule).all()
    seen_kindwide: set[tuple] = set()
    for r in rules:
        if r.from_plesso_id not in plesso_ids:
            violations.append(
                f"commuting rule #{r.id}: from_plesso_id="
                f"{r.from_plesso_id} non esiste")
        if r.to_plesso_id not in plesso_ids:
            violations.append(
                f"commuting rule #{r.id}: to_plesso_id="
                f"{r.to_plesso_id} non esiste")
        if r.entity_kind not in ("teacher", "class", "group"):
            violations.append(
                f"commuting rule #{r.id}: entity_kind="
                f"{r.entity_kind!r} non valido (atteso: "
                f"teacher | class | group)")
        if r.entity_id is not None:
            ok = (
                (r.entity_kind == "teacher"
                 and r.entity_id in teacher_ids)
                or (r.entity_kind == "class"
                    and r.entity_id in class_ids)
                or (r.entity_kind == "group"
                    and r.entity_id in group_ids)
            )
            if not ok:
                violations.append(
                    f"commuting rule #{r.id}: entity_id="
                    f"{r.entity_id} non trovato per kind "
                    f"{r.entity_kind!r}")
        if r.min_gap_hours is not None and r.min_gap_hours < 0:
            violations.append(
                f"commuting rule #{r.id}: min_gap_hours non puo' "
                f"essere negativo ({r.min_gap_hours})")
        if r.allowed_break_only:
            if (r.break_start_hour is None
                    or r.break_end_hour is None):
                violations.append(
                    f"commuting rule #{r.id}: allowed_break_only "
                    f"richiede sia break_start_hour che "
                    f"break_end_hour")
            elif r.break_start_hour > r.break_end_hour:
                violations.append(
                    f"commuting rule #{r.id}: break_start_hour "
                    f"({r.break_start_hour}) > break_end_hour "
                    f"({r.break_end_hour})")
        if r.entity_id is None:
            key = (r.from_plesso_id, r.to_plesso_id, r.entity_kind)
            if key in seen_kindwide:
                violations.append(
                    f"commuting rule #{r.id}: esiste gia' una "
                    f"regola kind-wide per "
                    f"(from={r.from_plesso_id}, "
                    f"to={r.to_plesso_id}, kind={r.entity_kind})")
            seen_kindwide.add(key)

    # PlessoEntityPolicy checks.
    policies = db.query(models.PlessoEntityPolicy).all()
    for pol in policies:
        if pol.entity_kind not in ("teacher", "class"):
            violations.append(
                f"entity policy #{pol.id}: entity_kind="
                f"{pol.entity_kind!r} non valido (atteso: "
                f"teacher | class)")
        if pol.entity_id is not None:
            ok = (
                (pol.entity_kind == "teacher"
                 and pol.entity_id in teacher_ids)
                or (pol.entity_kind == "class"
                    and pol.entity_id in class_ids)
            )
            if not ok:
                violations.append(
                    f"entity policy #{pol.id}: entity_id="
                    f"{pol.entity_id} non trovato per kind "
                    f"{pol.entity_kind!r}")
        if pol.policy not in (
                "any", "single_plesso_per_day",
                "single_plesso_total"):
            violations.append(
                f"entity policy #{pol.id}: policy="
                f"{pol.policy!r} non valida")
        if pol.policy == "single_plesso_total":
            if pol.plesso_id is not None and pol.plesso_id not in plesso_ids:
                violations.append(
                    f"entity policy #{pol.id}: plesso_id="
                    f"{pol.plesso_id} non esiste "
                    f"(per single_plesso_total)")
        else:
            if pol.plesso_id is not None:
                violations.append(
                    f"entity policy #{pol.id}: plesso_id e' "
                    f"impostato ma policy="
                    f"{pol.policy!r} non lo usa "
                    f"(rimuovi plesso_id o usa "
                    f"single_plesso_total)")

    return violations

def _preflight_lock_check() -> None:
    """Sync wrapper for the pre-flight check. Called by every
    run_xxx entry-point BEFORE create_run + start_thread, so a lock
    violation surfaces as a 400 on the synchronous POST instead of
    silently failing the run later. Opens its own session: cheap
    and short-lived.

    Also validates Task C1 invariants (coteach n_hours, sostegno
    class_id, potenziamento total cap) AND the PLESSI configuration
    (commuting rules + entity policies coherence).
    """
    with SessionLocal() as db:
        snap = _read_locked_lessons(db)
        cs_violations = validate_coteach_sostegno_potenziamento(db)
        plessi_violations = validate_plessi_rules(db)
    violations = list(cs_violations) + list(plessi_violations)
    if snap:
        violations.extend(validate_locks_vs_constraints(snap))
    if violations:
        raise RuntimeError(
            "Configurazione incompatibile con i vincoli HARD: "
            + "; ".join(violations)
            + ". Correggi le anomalie e riprova."
        )

def _read_locked_lessons(db: Session) -> list[dict]:
    """Capture the individually PINNED lessons of the active solution
    (``Lesson.locked``) so Phase B / meta keep them exactly where they are.

    Finding 26: this used to pin every lesson of a LOCKED *Assignment*,
    conflating "confirmed cattedra" (don't reassign the teacher) with
    "immovable hour". The effect was that a school which correctly loaded
    its cattedre as ``locked`` froze its whole timetable and could never
    regenerate. Now only a genuine per-slot pin (``Lesson.locked``) is an
    immovable slot; ``Assignment.locked`` no longer freezes any hour, so a
    plain re-run is free to re-place everything.
    """
    active = engine_io.get_active_solution(db)
    if active is None:
        return []
    out: list[dict] = []
    for l in db.query(models.Lesson).filter(
        models.Lesson.solution_id == active.id,
        models.Lesson.locked == True,  # noqa: E712
    ).all():
        out.append({
            "teacher_name": l.teacher_name,
            "class_name": l.class_name,
            "subject": l.subject,
            "day": l.day, "hour": l.hour,
            "classroom_name": l.classroom_name,
            "cotaught_with": l.cotaught_with,
        })
    return out
