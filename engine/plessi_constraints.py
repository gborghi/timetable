"""CP-SAT constraints for the PLESSI feature.

This module is a pipeline-agnostic helper that adds the
inter-plesso constraints (commuting rules + entity policies) on top
of an existing CP-SAT model whose slot variables are indexed by
``(teacher, class, subject, day, hour)``.

The two callers (Phase B day-solver, full timetable solver) hand in:
- ``model``: the ``cp_model.CpModel`` instance,
- ``slot``: a ``dict[tuple, IntVar]`` keying every active
  ``(teacher, class, subject, day, hour)`` to its Boolean variable,
- ``classroom_assignment``: optional ``dict[tuple, str]`` mapping
  ``(class, day, hour)`` to the ``classroom_name``. When None the
  caller has not yet decided rooms (and inter-plesso constraints
  cannot be applied yet).
- ``plessi_data``: a thin DTO with the resolved tables (see
  :func:`load_plessi_data` for the canonical shape).

The module is fully usable in unit tests without a database: feed
``plessi_data`` directly.

The helper is conservative: when the configuration would render
the model infeasible at the LP relaxation level (e.g. a commuting
rule requiring a 2-hour gap between two consecutive lessons), the
helper adds a hard CP-SAT constraint that forbids the offending
pair. Soft variants would be a follow-up.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass
class CommutingRule:
    """One row of the ``plesso_commuting_rules`` table."""
    id: int
    from_plesso_id: int
    to_plesso_id: int
    entity_kind: str   # 'teacher' | 'class' | 'group'
    entity_id: int | None
    min_gap_hours: int = 0
    allowed_break_only: bool = False
    break_start_hour: int | None = None
    break_end_hour: int | None = None
    symmetric: bool = True
    priority: int = 0


@dataclass
class EntityPolicy:
    """One row of the ``plesso_entity_policies`` table."""
    id: int
    entity_kind: str   # 'teacher' | 'class'
    entity_id: int | None
    policy: str        # 'any' | 'single_plesso_per_day' | 'single_plesso_total'
    plesso_id: int | None = None
    priority: int = 0


@dataclass
class PlessiData:
    """In-memory snapshot of the PLESSI configuration plus the
    classroom -> plesso lookup. The CP-SAT helper expects this
    structure; the loader (DB-side) builds it from the ORM rows.
    """
    classroom_to_plesso: dict[str, int | None] = field(default_factory=dict)
    """``classroom_name -> plesso_id`` (None when the classroom has
    no plesso)."""

    teacher_name_to_id: dict[str, int] = field(default_factory=dict)
    class_name_to_id: dict[str, int] = field(default_factory=dict)
    group_name_to_id: dict[str, int] = field(default_factory=dict)

    commuting_rules: list[CommutingRule] = field(default_factory=list)
    entity_policies: list[EntityPolicy] = field(default_factory=list)


# ---------- Rule resolution ----------

def resolve_commuting_rule(
    plessi: PlessiData,
    from_plesso_id: int,
    to_plesso_id: int,
    entity_kind: str,
    entity_id: int | None,
) -> CommutingRule | None:
    """Find the most-specific commuting rule applicable to a move
    of (entity_kind, entity_id) between (from_plesso, to_plesso).

    Order of preference:
      1. Rule with entity_id == entity_id (per-entity override).
      2. Rule with entity_id is None (kind-wide).
      3. None (no rule -> any movement allowed).

    Symmetric rules also match when the (from, to) pair is
    swapped.
    """
    candidates: list[CommutingRule] = []
    for r in plessi.commuting_rules:
        if r.entity_kind != entity_kind:
            continue
        match = (r.from_plesso_id == from_plesso_id
                 and r.to_plesso_id == to_plesso_id)
        if not match and r.symmetric:
            match = (r.from_plesso_id == to_plesso_id
                     and r.to_plesso_id == from_plesso_id)
        if not match:
            continue
        if r.entity_id is not None and entity_id is not None \
                and r.entity_id != entity_id:
            continue
        candidates.append(r)
    if not candidates:
        return None
    # Prefer entity-specific override, then highest priority.
    candidates.sort(key=lambda r: (
        0 if r.entity_id is not None else 1,
        -r.priority))
    return candidates[0]


def resolve_entity_policy(
    plessi: PlessiData,
    entity_kind: str,
    entity_id: int | None,
) -> EntityPolicy | None:
    """Find the policy for (entity_kind, entity_id):
      1. Per-entity override (entity_id == entity_id).
      2. Kind-wide (entity_id is None).
    Higher priority wins among ties. Returns None if no policy
    applies.
    """
    candidates: list[EntityPolicy] = []
    for p in plessi.entity_policies:
        if p.entity_kind != entity_kind:
            continue
        if p.entity_id is not None and entity_id is not None \
                and p.entity_id != entity_id:
            continue
        candidates.append(p)
    if not candidates:
        return None
    candidates.sort(key=lambda p: (
        0 if p.entity_id is not None else 1,
        -p.priority))
    return candidates[0]


# ---------- CP-SAT integration ----------

def add_plesso_commuting_constraints_for_teacher(
    model,
    slot: dict,
    plessi: PlessiData,
    teacher_name: str,
    *,
    days: Iterable[int],
    hours: Iterable[int],
    classroom_for_slot: dict,
):
    """Add commuting-rule constraints for ONE teacher.

    For every pair of adjacent slots (d, h) and (d, h+1) on the
    same day, look up the classroom assigned to each slot and
    its plesso. If the two plessi differ AND a commuting rule
    requires `min_gap_hours >= 1` (or `allowed_break_only=True`
    outside the break window), forbid both slots from being
    simultaneously active.

    Implementation: for each forbidden pair `(slot_a, slot_b)`,
    add `model.AddBoolOr([slot_a.Not(), slot_b.Not()])` -- at
    most one of the two can be true.

    `slot` is keyed by (teacher, class, subject, day, hour).
    `classroom_for_slot` is keyed by (class, day, hour) (since
    classroom assignment is at the class-slot level in piTantum).
    """
    if not plessi.commuting_rules:
        return

    teacher_id = plessi.teacher_name_to_id.get(teacher_name)

    # Group slots by (day, hour) for this teacher.
    by_d_h: dict[tuple[int, int], list[tuple]] = {}
    for key, var in slot.items():
        if len(key) != 5:
            continue
        t, cl, s, d, h = key
        if t != teacher_name:
            continue
        by_d_h.setdefault((d, h), []).append((cl, s, var))

    days_list = sorted(set(days))
    hours_list = sorted(set(hours))
    h_index = {h: i for i, h in enumerate(hours_list)}

    for d in days_list:
        for i, h_a in enumerate(hours_list[:-1]):
            h_b = hours_list[i + 1]
            slots_a = by_d_h.get((d, h_a), [])
            slots_b = by_d_h.get((d, h_b), [])
            if not slots_a or not slots_b:
                continue
            for (cl_a, _s_a, va) in slots_a:
                room_a = classroom_for_slot.get((cl_a, d, h_a))
                if room_a is None:
                    continue
                pl_a = plessi.classroom_to_plesso.get(room_a)
                if pl_a is None:
                    continue
                for (cl_b, _s_b, vb) in slots_b:
                    room_b = classroom_for_slot.get((cl_b, d, h_b))
                    if room_b is None:
                        continue
                    pl_b = plessi.classroom_to_plesso.get(room_b)
                    if pl_b is None or pl_b == pl_a:
                        continue
                    rule = resolve_commuting_rule(
                        plessi, pl_a, pl_b, "teacher", teacher_id)
                    if rule is None:
                        continue
                    if _adjacent_violates_rule(rule, h_a, h_b):
                        # Forbid both: at most one of (va, vb) is true.
                        model.AddBoolOr([va.Not(), vb.Not()])


def _adjacent_violates_rule(
    rule: CommutingRule, h_a: int, h_b: int,
) -> bool:
    """Return True if having a teacher in (plesso_a, h_a) and in
    (plesso_b, h_b) with h_b == h_a + 1 violates `rule`.

    Rules:
      - min_gap_hours >= 1: adjacent slots are NOT allowed.
      - allowed_break_only=True: adjacent slots are allowed only
        if (h_a, h_b) == (break_start_hour, break_end_hour).
      - Otherwise (min_gap=0, no break-only): adjacent is OK.
    """
    if rule.min_gap_hours and rule.min_gap_hours >= 1:
        return True
    if rule.allowed_break_only:
        bs = rule.break_start_hour
        be = rule.break_end_hour
        if bs is None or be is None:
            return True  # malformed rule -> conservative reject
        if not (h_a == bs and h_b == be):
            return True
    return False


# ---------- Classroom-assignment integration ----------
#
# The function above (`add_plesso_commuting_constraints_for_teacher`)
# is for the case where slots are decision vars and classrooms are
# already fixed. The helpers below are for the opposite direction:
# the classroom-assignment CP-SAT, where (class, subject, day, hour)
# slots are FIXED (they come from the timetable solution) and the
# decision is which room to use. In this regime we tighten directly
# on the room-choice variables `x[(lesson_key, room_name)]`.

def add_plesso_commuting_constraints_classroom_assignment(
    model,
    x: dict,
    eligible: dict,
    plessi: PlessiData,
    *,
    teacher_for_lesson: dict[tuple, list[str]],
    days: Iterable[int],
    hours: Iterable[int],
) -> int:
    """Forbid (room_a, room_b) pairs where the SAME teacher would
    cross plessi at adjacent hours (h, h+1) on the same day and a
    commuting rule says that's not allowed.

    `x`: ``(lesson_key, room_name) -> BoolVar`` -- the room-choice
    decision variables. ``lesson_key`` is ``(class, subject, day,
    hour)``.
    `eligible`: ``lesson_key -> list[room_name]`` -- the rooms that
    can host that lesson (built by the caller after the HARD
    eligibility filter).
    `teacher_for_lesson`: ``lesson_key -> list[str]`` -- principal
    plus co-teachers for that slot.

    Returns the number of pair-forbid constraints emitted (useful for
    diagnostics).
    """
    if not plessi.commuting_rules:
        return 0

    by_t_d_h: dict[tuple[str, int, int], list[tuple]] = {}
    for key, t_list in teacher_for_lesson.items():
        cl, subj, d, h = key
        for t_name in t_list:
            by_t_d_h.setdefault((t_name, d, h), []).append(key)

    days_list = sorted(set(days))
    hours_list = sorted(set(hours))

    n_emitted = 0
    teachers = sorted({t for (t, _, _) in by_t_d_h})
    for t_name in teachers:
        teacher_id = plessi.teacher_name_to_id.get(t_name)
        for d in days_list:
            for i, h_a in enumerate(hours_list[:-1]):
                h_b = hours_list[i + 1]
                keys_a = by_t_d_h.get((t_name, d, h_a), [])
                keys_b = by_t_d_h.get((t_name, d, h_b), [])
                if not keys_a or not keys_b:
                    continue
                for key_a in keys_a:
                    for room_a in eligible.get(key_a, []):
                        pl_a = plessi.classroom_to_plesso.get(room_a)
                        if pl_a is None:
                            continue
                        for key_b in keys_b:
                            for room_b in eligible.get(key_b, []):
                                pl_b = plessi.classroom_to_plesso.get(
                                    room_b)
                                if pl_b is None or pl_b == pl_a:
                                    continue
                                rule = resolve_commuting_rule(
                                    plessi, pl_a, pl_b,
                                    "teacher", teacher_id)
                                if rule is None:
                                    continue
                                if not _adjacent_violates_rule(
                                        rule, h_a, h_b):
                                    continue
                                va = x.get((key_a, room_a))
                                vb = x.get((key_b, room_b))
                                if va is None or vb is None:
                                    continue
                                model.AddBoolOr(
                                    [va.Not(), vb.Not()])
                                n_emitted += 1
    return n_emitted


def add_plesso_entity_policy_constraints_classroom_assignment(
    model,
    x: dict,
    eligible: dict,
    plessi: PlessiData,
    *,
    teacher_for_lesson: dict[tuple, list[str]],
    days: Iterable[int],
) -> int:
    """Apply teacher entity policies on the classroom-assignment CP-SAT.

    Implemented:
      - ``single_plesso_per_day``: per (teacher, day), at most one
        plesso may host that teacher's lessons.
      - ``single_plesso_total``: every room hosting any of that
        teacher's lessons must lie in ``policy.plesso_id``.
      - ``any``: no constraint emitted.

    Class-side and group-side policies are TODO; they require the
    class_name -> id and group_name -> id maps and a similar pattern
    grouped by (class, day) instead of (teacher, day).

    Returns the number of constraints / variables emitted.
    """
    if not plessi.entity_policies:
        return 0

    by_t_d: dict[tuple[str, int], list[tuple]] = {}
    for key, t_list in teacher_for_lesson.items():
        cl, subj, d, h = key
        for t_name in t_list:
            by_t_d.setdefault((t_name, d), []).append(key)

    days_list = sorted(set(days))
    n_emitted = 0
    teachers = sorted({t for (t, _) in by_t_d})

    for t_name in teachers:
        teacher_id = plessi.teacher_name_to_id.get(t_name)
        policy = resolve_entity_policy(plessi, "teacher", teacher_id)
        if policy is None or policy.policy == "any":
            continue

        if policy.policy == "single_plesso_total":
            target = policy.plesso_id
            for d in days_list:
                for key in by_t_d.get((t_name, d), []):
                    for room in eligible.get(key, []):
                        pl = plessi.classroom_to_plesso.get(room)
                        if pl is None or pl == target:
                            continue
                        var = x.get((key, room))
                        if var is not None:
                            model.Add(var == 0)
                            n_emitted += 1
            continue

        if policy.policy == "single_plesso_per_day":
            # Per (teacher, day, plesso) indicator: 1 iff this
            # teacher uses that plesso on that day. Cap sum <= 1.
            for d in days_list:
                keys_today = by_t_d.get((t_name, d), [])
                if not keys_today:
                    continue
                # Collect all plessi reachable today
                plessi_today: set[int] = set()
                for key in keys_today:
                    for room in eligible.get(key, []):
                        pl = plessi.classroom_to_plesso.get(room)
                        if pl is not None:
                            plessi_today.add(pl)
                if len(plessi_today) <= 1:
                    continue
                ind = {}
                for pl in plessi_today:
                    iv = model.NewBoolVar(
                        f"plday_{t_name}_{d}_{pl}")
                    ind[pl] = iv
                # Link: x[(key, room)] => ind[plesso(room)] = 1
                for key in keys_today:
                    for room in eligible.get(key, []):
                        pl = plessi.classroom_to_plesso.get(room)
                        if pl is None:
                            continue
                        var = x.get((key, room))
                        if var is None:
                            continue
                        model.Add(ind[pl] >= var)
                        n_emitted += 1
                model.Add(sum(ind.values()) <= 1)
                n_emitted += 1
            continue
        # Unknown policy: ignore (validated upstream).

    return n_emitted


# ---------- DB-side loader (kept thin for testability) ----------

def load_plessi_data(db) -> PlessiData:
    """Build a :class:`PlessiData` snapshot from the ORM models.

    Imported lazily so this module stays usable in unit tests
    without the backend package on sys.path.
    """
    from backend import models  # type: ignore

    data = PlessiData()
    data.classroom_to_plesso = {
        c.name: c.plesso_id for c in db.query(models.Classroom).all()
    }
    data.teacher_name_to_id = {
        t.name: t.id for t in db.query(models.Teacher).all()
    }
    data.class_name_to_id = {
        c.name: c.id for c in db.query(models.SchoolClass).all()
    }
    if hasattr(models, "StudyGroup"):
        data.group_name_to_id = {
            g.name: g.id for g in db.query(models.StudyGroup).all()
        }

    for r in db.query(models.PlessoCommutingRule).all():
        data.commuting_rules.append(CommutingRule(
            id=r.id,
            from_plesso_id=r.from_plesso_id,
            to_plesso_id=r.to_plesso_id,
            entity_kind=r.entity_kind,
            entity_id=r.entity_id,
            min_gap_hours=r.min_gap_hours or 0,
            allowed_break_only=bool(r.allowed_break_only),
            break_start_hour=r.break_start_hour,
            break_end_hour=r.break_end_hour,
            symmetric=bool(r.symmetric),
            priority=r.priority or 0,
        ))
    for p in db.query(models.PlessoEntityPolicy).all():
        data.entity_policies.append(EntityPolicy(
            id=p.id,
            entity_kind=p.entity_kind,
            entity_id=p.entity_id,
            policy=p.policy or "any",
            plesso_id=p.plesso_id,
            priority=p.priority or 0,
        ))
    return data
