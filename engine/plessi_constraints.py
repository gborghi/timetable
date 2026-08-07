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

    home_classroom_by_class: dict[str, str] = field(default_factory=dict)
    """``class_name -> classroom_name`` of the class's HOME room (the
    ``ClassroomClassPreference`` row with ``is_home=True``). It is what
    tells Phase B where a class -- and so any teacher teaching it --
    physically is, at a point in the pipeline where no room has been
    assigned to any lesson yet. See :func:`class_plesso_pins`."""

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
    {h: i for i, h in enumerate(hours_list)}

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


def _pair_violates_rule(
    rule: CommutingRule, h_a: int, h_b: int,
) -> bool:
    """Return True if being in plesso_a at `h_a` and in plesso_b at
    `h_b` (same day, ``h_a < h_b``) violates `rule`.

    Generalises :func:`_adjacent_violates_rule` to non-adjacent pairs,
    which is what the Phase-B day solver needs: there the two lessons
    that straddle a site change are often NOT next to each other, and
    checking only ``h+1`` would wave through a teacher who teaches in
    plesso A at the 1st hour and in plesso B at the 3rd with nothing
    in between -- a move the rule is precisely meant to forbid.

    Semantics:
      - ``min_gap_hours = g``: at least ``g`` free hours must sit
        strictly between the two lessons.
      - ``allowed_break_only``: the site change may only happen ACROSS
        the break, i.e. the last lesson in the departure plesso must
        end by ``break_start_hour`` and the first in the arrival one
        may not start before ``break_end_hour``. (For adjacent hours
        this reduces to the historical ``h_a == bs and h_b == be``.)
      - neither: any pair is fine.
    """
    if h_a > h_b:
        h_a, h_b = h_b, h_a
    free_between = h_b - h_a - 1
    if rule.min_gap_hours and free_between < rule.min_gap_hours:
        return True
    if rule.allowed_break_only:
        bs = rule.break_start_hour
        be = rule.break_end_hour
        if bs is None or be is None:
            return True  # malformed rule -> conservative reject
        if not (h_a <= bs and h_b >= be):
            return True
    return False


def _adjacent_violates_rule(
    rule: CommutingRule, h_a: int, h_b: int,
) -> bool:
    """Adjacent-pair specialisation of :func:`_pair_violates_rule`,
    kept as the name the classroom-assignment helpers call."""
    return _pair_violates_rule(rule, h_a, h_b)


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


# ---------- Class-kind variants for classroom assignment ----------

def add_plesso_commuting_constraints_class_kind(
    model,
    x: dict,
    eligible: dict,
    plessi: PlessiData,
    *,
    days: Iterable[int],
    hours: Iterable[int],
) -> int:
    """Class-kind commuting constraints: forbid (room_a, room_b)
    where the SAME class would cross plessi at adjacent hours and
    a class-kind rule says no.

    Each lesson_key carries its class as ``key[0]``, so no extra
    mapping is needed.

    Returns number of pair-forbid constraints emitted.
    """
    if not plessi.commuting_rules:
        return 0
    # Group lesson_keys by (class, day, hour).
    by_c_d_h: dict[tuple[str, int, int], list[tuple]] = {}
    for key in x:
        # x is keyed by (lesson_key, room_name); skip the room
        # dimension by using `eligible.keys()` instead.
        pass
    by_c_d_h = {}
    for key in eligible.keys():
        cl, subj, d, h = key
        by_c_d_h.setdefault((cl, d, h), []).append(key)

    days_list = sorted(set(days))
    hours_list = sorted(set(hours))
    n_emitted = 0

    classes = sorted({k[0] for k in eligible.keys()})
    for cl_name in classes:
        class_id = plessi.class_name_to_id.get(cl_name)
        for d in days_list:
            for i, h_a in enumerate(hours_list[:-1]):
                h_b = hours_list[i + 1]
                keys_a = by_c_d_h.get((cl_name, d, h_a), [])
                keys_b = by_c_d_h.get((cl_name, d, h_b), [])
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
                                    "class", class_id)
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


def add_plesso_entity_policy_constraints_class_kind(
    model,
    x: dict,
    eligible: dict,
    plessi: PlessiData,
    *,
    days: Iterable[int],
) -> int:
    """Class-kind entity policies on the classroom-assignment
    CP-SAT.

    Implemented:
      - ``single_plesso_per_day``: per (class, day), at most one
        plesso may host that class's lessons.
      - ``single_plesso_total``: every room hosting any of that
        class's lessons must lie in ``policy.plesso_id``.
      - ``any``: no constraint.

    Returns number of constraints / variables emitted.
    """
    if not plessi.entity_policies:
        return 0

    by_c_d: dict[tuple[str, int], list[tuple]] = {}
    for key in eligible.keys():
        cl, subj, d, h = key
        by_c_d.setdefault((cl, d), []).append(key)

    days_list = sorted(set(days))
    n_emitted = 0
    classes = sorted({k[0] for k in eligible.keys()})

    for cl_name in classes:
        class_id = plessi.class_name_to_id.get(cl_name)
        policy = resolve_entity_policy(plessi, "class", class_id)
        if policy is None or policy.policy == "any":
            continue

        if policy.policy == "single_plesso_total":
            target = policy.plesso_id
            for d in days_list:
                for key in by_c_d.get((cl_name, d), []):
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
            for d in days_list:
                keys_today = by_c_d.get((cl_name, d), [])
                if not keys_today:
                    continue
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
                        f"plclday_{cl_name}_{d}_{pl}")
                    ind[pl] = iv
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


# ---------- Phase-B (day solver) integration ----------
#
# Phase B decides WHEN each lesson happens; rooms are assigned only
# afterwards, by `classroom_assignment`. So none of the helpers above
# apply: they all read the plesso off a classroom that does not exist
# yet. Asking Phase B to ignore plessi and hoping the room step fixes
# it later does not work either -- by then the hours are frozen, and a
# teacher scheduled in both sites at consecutive hours has no room
# assignment that can rescue them. The site has to be known while the
# hours are still free.
#
# What IS known that early is where a CLASS sits: a class stays in its
# own room all week, so its plesso is a fixed property of the class,
# not of the individual lesson. That gives a teacher's plesso at every
# hour -- it is the plesso of the class they teach in that hour.


def class_plesso_pins(
    plessi: PlessiData,
    *,
    home_classroom_by_class: dict[str, str] | None = None,
) -> dict[str, int]:
    """``class_name -> plesso_id`` for the classes whose site is known.

    Two sources, most explicit first:

      1. a ``single_plesso_total`` policy on that class with a non-null
         ``plesso_id`` -- somebody stated where the class lives;
      2. the class's HOME classroom (``ClassroomClassPreference.is_home``),
         whose plesso is the class's by construction.

    A class with neither is simply absent from the map, and no Phase-B
    plesso constraint mentions it. That is deliberate: an unknown site
    must not be silently guessed as "plesso 1" -- it would forbid real
    timetables on the strength of missing data.
    """
    pins: dict[str, int] = {}
    rooms = home_classroom_by_class or plessi.home_classroom_by_class
    for cl_name, room in (rooms or {}).items():
        pl = plessi.classroom_to_plesso.get(room)
        if pl is not None:
            pins[cl_name] = pl
    for cl_name, cl_id in plessi.class_name_to_id.items():
        pol = resolve_entity_policy(plessi, "class", cl_id)
        if (pol is not None and pol.policy == "single_plesso_total"
                and pol.plesso_id is not None):
            pins[cl_name] = pol.plesso_id
    return pins


def add_plesso_constraints_phase_b(
    model,
    slot: dict,
    plessi: PlessiData,
    *,
    day: int,
    hours: Iterable[int],
    class_to_plesso: dict[str, int],
) -> int:
    """Teacher-side plesso constraints for ONE day of Phase B.

    ``slot`` is the 5-tuple view ``(teacher, class, subject, day, hour)
    -> BoolVar`` (the same one the DSL compiler gets). Only entries on
    ``day`` are read.

    Emits two families:

    - **commuting rules** -- for every teacher and every pair of hours
      whose classes sit in different plessi, if the applicable rule
      says that transition is not possible, forbid the two lessons from
      both being scheduled (``AddBoolOr([a.Not(), b.Not()])``).
    - **entity policies** -- ``single_plesso_per_day`` confines a
      teacher to one site for the whole day. ``single_plesso_total``
      with a fixed ``plesso_id`` forbids every other site outright;
      with a null ``plesso_id`` (solver picks the site) the day solver
      enforces the per-day relaxation, which is implied by the weekly
      rule and is the strongest thing one day in isolation can know.

    Class-side commuting rules are NOT emitted: a class is pinned to
    its plesso for the week, so it never commutes and the rule is
    vacuous. Class-side *room* choices remain the room step's business.

    Returns the number of constraints emitted (0 when the school has no
    plessi configured, which is the common case).
    """
    if not plessi.commuting_rules and not plessi.entity_policies:
        return 0
    if not class_to_plesso:
        return 0

    hours_list = sorted(set(hours))
    # (teacher, hour) -> [(plesso_id, var), ...] for this day.
    by_t_h: dict[tuple[str, int], list[tuple[int, object]]] = {}
    for key, var in slot.items():
        if len(key) != 5:
            continue
        t, cl, _s, d, h = key
        if d != day:
            continue
        pl = class_to_plesso.get(cl)
        if pl is None:
            continue
        by_t_h.setdefault((t, h), []).append((pl, var))

    teachers = sorted({t for (t, _h) in by_t_h})
    n_emitted = 0

    for t_name in teachers:
        t_id = plessi.teacher_name_to_id.get(t_name)

        # --- commuting rules over every hour pair of the day ---
        if plessi.commuting_rules:
            for i, h_a in enumerate(hours_list):
                for h_b in hours_list[i + 1:]:
                    for (pl_a, va) in by_t_h.get((t_name, h_a), []):
                        for (pl_b, vb) in by_t_h.get((t_name, h_b), []):
                            if pl_a == pl_b:
                                continue
                            rule = resolve_commuting_rule(
                                plessi, pl_a, pl_b, "teacher", t_id)
                            if rule is None:
                                continue
                            if not _pair_violates_rule(rule, h_a, h_b):
                                continue
                            model.AddBoolOr([va.Not(), vb.Not()])
                            n_emitted += 1

        # --- entity policies ---
        if not plessi.entity_policies:
            continue
        policy = resolve_entity_policy(plessi, "teacher", t_id)
        if policy is None or policy.policy == "any":
            continue

        vars_by_plesso: dict[int, list] = {}
        for h in hours_list:
            for (pl, var) in by_t_h.get((t_name, h), []):
                vars_by_plesso.setdefault(pl, []).append(var)
        if len(vars_by_plesso) <= 1:
            continue

        if (policy.policy == "single_plesso_total"
                and policy.plesso_id is not None):
            for pl, vars_ in vars_by_plesso.items():
                if pl == policy.plesso_id:
                    continue
                for var in vars_:
                    model.Add(var == 0)
                    n_emitted += 1
            continue

        # single_plesso_per_day, or single_plesso_total with a free
        # choice of site: at most one plesso may be used today.
        ind = {}
        for pl in vars_by_plesso:
            ind[pl] = model.NewBoolVar(f"pltday_{t_name}_{day}_{pl}")
        for pl, vars_ in vars_by_plesso.items():
            for var in vars_:
                model.Add(ind[pl] >= var)
                n_emitted += 1
        model.Add(sum(ind.values()) <= 1)
        n_emitted += 1

    return n_emitted


# ---------- Solution-side diagnostic ----------

def check_solution_against_plessi(
    solution: dict,
    plessi: PlessiData,
) -> list[dict]:
    """Audit a finalised solution against the plessi rules and return
    a flat list of violation dicts.

    `solution` is a dict keyed by ``(teacher, class_name, subject,
    day, hour) -> classroom_name`` (the canonical solution shape used
    elsewhere in the engine). The helper does NOT modify the solution;
    it only inspects what was scheduled.

    Each violation dict has at minimum:
      - ``kind``: one of ``"commuting"`` / ``"single_per_day"`` /
        ``"single_total"`` / ``"unknown_classroom"`` /
        ``"unknown_plesso"``;
      - ``entity_kind`` and ``entity_name``;
      - source data (slots, plessi, rule id) sufficient to render a
        readable message in the UI.

    Two intended uses:
      1. The monitor UI calls this on the active solution to show a
         live "plessi violations" badge with a drill-down list.
      2. Pre-commit / smoke test on solutions produced by pipelines
         that do NOT yet wire plessi constraints (Phase B,
         decompositions, meta) -- the helper makes the gap visible.
    """
    if not solution:
        return []

    violations: list[dict] = []

    # Decode every assignment into (entity_role, entity, day, hour,
    # plesso_id). We track teacher AND class roles per assignment.
    cl_to_pl = plessi.classroom_to_plesso

    # by_teacher_day_hour and by_class_day_hour index the schedule
    # for adjacency / per-day checks.
    by_t_d_h: dict[tuple[str, int, int], list[tuple]] = {}
    by_c_d_h: dict[tuple[str, int, int], list[tuple]] = {}
    by_t_total: dict[str, list[tuple]] = {}
    by_c_total: dict[str, list[tuple]] = {}

    for key, room in solution.items():
        if room is None or len(key) != 5:
            continue
        t, cl, subj, d, h = key
        d, h = int(d), int(h)
        if room not in cl_to_pl:
            violations.append({
                "kind": "unknown_classroom",
                "classroom": room,
                "key": (t, cl, subj, d, h),
            })
            continue
        pl = cl_to_pl[room]
        if pl is None:
            # Classroom exists but has no plesso assigned: outside
            # the plessi system, can't violate plessi rules.
            continue
        slot = (t, cl, subj, d, h, room, pl)
        by_t_d_h.setdefault((t, d, h), []).append(slot)
        by_c_d_h.setdefault((cl, d, h), []).append(slot)
        by_t_total.setdefault(t, []).append(slot)
        by_c_total.setdefault(cl, []).append(slot)

    # ---- commuting rules (teacher kind) ----
    for t, slots in by_t_total.items():
        teacher_id = plessi.teacher_name_to_id.get(t)
        # Build per-day (h, plesso) lists.
        by_d: dict[int, list[tuple[int, int, str]]] = {}
        for (_t, _cl, _s, d, h, room, pl) in slots:
            by_d.setdefault(d, []).append((h, pl, room))
        for d, lst in by_d.items():
            lst.sort()
            for i in range(len(lst) - 1):
                h_a, pl_a, room_a = lst[i]
                h_b, pl_b, room_b = lst[i + 1]
                if pl_a == pl_b:
                    continue
                rule = resolve_commuting_rule(
                    plessi, pl_a, pl_b, "teacher", teacher_id)
                if rule is None:
                    continue
                if h_b - h_a >= max(1, rule.min_gap_hours + 1) - 1 \
                        and rule.min_gap_hours <= h_b - h_a - 1:
                    # Gap is enough to satisfy min_gap_hours.
                    if not rule.allowed_break_only:
                        continue
                # break_only check
                if rule.allowed_break_only and (
                        rule.break_start_hour is not None
                        and rule.break_end_hour is not None
                        and h_a == rule.break_start_hour
                        and h_b == rule.break_end_hour):
                    continue
                violations.append({
                    "kind": "commuting",
                    "entity_kind": "teacher",
                    "entity_name": t,
                    "day": d,
                    "hour_a": h_a,
                    "hour_b": h_b,
                    "plesso_a": pl_a,
                    "plesso_b": pl_b,
                    "room_a": room_a,
                    "room_b": room_b,
                    "rule_id": rule.id,
                    "min_gap_hours": rule.min_gap_hours,
                })

    # ---- commuting rules (class kind) ----
    for cl_name, slots in by_c_total.items():
        class_id = plessi.class_name_to_id.get(cl_name)
        by_d: dict[int, list[tuple[int, int, str]]] = {}
        for (_t, _cl, _s, d, h, room, pl) in slots:
            by_d.setdefault(d, []).append((h, pl, room))
        for d, lst in by_d.items():
            lst.sort()
            for i in range(len(lst) - 1):
                h_a, pl_a, room_a = lst[i]
                h_b, pl_b, room_b = lst[i + 1]
                if pl_a == pl_b:
                    continue
                rule = resolve_commuting_rule(
                    plessi, pl_a, pl_b, "class", class_id)
                if rule is None:
                    continue
                if rule.min_gap_hours <= h_b - h_a - 1 \
                        and not rule.allowed_break_only:
                    continue
                if rule.allowed_break_only and (
                        rule.break_start_hour is not None
                        and rule.break_end_hour is not None
                        and h_a == rule.break_start_hour
                        and h_b == rule.break_end_hour):
                    continue
                violations.append({
                    "kind": "commuting",
                    "entity_kind": "class",
                    "entity_name": cl_name,
                    "day": d,
                    "hour_a": h_a,
                    "hour_b": h_b,
                    "plesso_a": pl_a,
                    "plesso_b": pl_b,
                    "room_a": room_a,
                    "room_b": room_b,
                    "rule_id": rule.id,
                    "min_gap_hours": rule.min_gap_hours,
                })

    # ---- entity policies (teacher + class) ----
    def _check_policies(by_total, kind_name, name_to_id):
        for ent_name, slots in by_total.items():
            ent_id = name_to_id.get(ent_name)
            policy = resolve_entity_policy(plessi, kind_name, ent_id)
            if policy is None or policy.policy == "any":
                continue
            if policy.policy == "single_plesso_total":
                target = policy.plesso_id
                bad = [(t, cl, s, d, h, room, pl)
                       for (t, cl, s, d, h, room, pl) in slots
                       if pl != target]
                if bad:
                    violations.append({
                        "kind": "single_total",
                        "entity_kind": kind_name,
                        "entity_name": ent_name,
                        "expected_plesso": target,
                        "n_slots_in_wrong_plesso": len(bad),
                        "rule_id": policy.id,
                    })
                continue
            if policy.policy == "single_plesso_per_day":
                by_d: dict[int, set[int]] = {}
                for (_t, _cl, _s, d, _h, _room, pl) in slots:
                    by_d.setdefault(d, set()).add(pl)
                for d, plessi_today in by_d.items():
                    if len(plessi_today) > 1:
                        violations.append({
                            "kind": "single_per_day",
                            "entity_kind": kind_name,
                            "entity_name": ent_name,
                            "day": d,
                            "plessi": sorted(plessi_today),
                            "rule_id": policy.id,
                        })

    _check_policies(by_t_total, "teacher",
                     plessi.teacher_name_to_id)
    _check_policies(by_c_total, "class",
                     plessi.class_name_to_id)

    return violations


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

    # Home rooms: the only pre-room-assignment evidence of where a class
    # sits, hence of where its teachers are. Best-effort -- a school with
    # no home rooms configured simply yields an empty map, and the
    # Phase-B helper then adds nothing.
    try:
        rooms_by_id = {c.id: c.name
                       for c in db.query(models.Classroom).all()}
        for pref in (db.query(models.ClassroomClassPreference)
                       .filter(models.ClassroomClassPreference.is_home
                               == True).all()):  # noqa: E712
            room_name = rooms_by_id.get(pref.classroom_id)
            if pref.class_name and room_name:
                data.home_classroom_by_class[pref.class_name] = room_name
    except Exception:
        pass

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
