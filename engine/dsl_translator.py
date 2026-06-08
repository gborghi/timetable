"""Translator: special-purpose constraint tables -> generic DSL.

The system has many ORM tables that each store one specific kind of
constraint with its own column shape:

  - TeacherUnavailability       (teacher, day, hour, state)
  - ClassUnavailability         (class,   day, hour, state)
  - ClassroomUnavailability     (room,    day, hour, state)
  - TeacherMandatoryFreeDay     (teacher, day)
  - CoteachGroup                (class | group, subject, n_hours, teachers)
  - PlessoCommutingRule         (from_pl, to_pl, kind, entity, gap)
  - PlessoEntityPolicy          (kind, entity, policy, plesso_id)
  - LogicalUnavailability       (entity, expression, parsed_dnf)
  - CurriculumLogicalConstraint (curriculum, year_filter, expression)

Each one is consumed by the legacy hardcoded paths inside
``cpsat_v2_timetable.py`` / classroom_assignment / plessi_constraints
/ etc. The architecture goal is to flatten ALL of them into a single
DSL stream that ``DSLConstraintCompiler`` then translates into
CP-SAT constraints uniformly across mono solver, every BP pricer,
metaheuristics, and Ryan-Foster nodes.

This module is the translation layer. Each ``*_to_dsl(row)`` function
returns a DSL string that the parser/compiler accepts verbatim. The
loader ``load_all_dsl_constraints(db, scope=None)`` aggregates over
every table and returns a list of ``(label, kind, expression, weight)``
tuples ready to feed into ``ConstraintModel.add_all_dsl_constraints``.

Mapping invariants
------------------
- entity name strings match what the slot key carries: teacher names
  ("Rossi"), class names ("1A"), classroom names ("A1"), subject
  names ("Matematica"). The DSL parser supports literal identifiers
  AND quoted strings; we use quoted strings to handle names with
  spaces.
- day codes are 1..6 ints (lun..sab); hour codes are 8..13 ints.
- ``state == "hard"`` rows produce HARD DSL rules; ``state == "soft"``
  rows produce SOFT rules with the row's ``soft_penalty`` weight.
  SOFT-cost integration HAS landed: ``DSLConstraintCompiler`` reifies
  each SOFT violation into a BoolVar and appends ``(weight, var)`` to
  ``compiler.soft_cost_terms``, which the owning model folds into its
  objective. SOFT rows are emitted only when the loader is called with
  ``include_soft=True`` -- and every PRODUCTION solver currently passes
  ``include_soft=False`` (cpsat_v2_timetable, metaheuristics,
  optimization), so SOFT table rules are wired but DORMANT in
  production; only ``test_free_day_constraint`` exercises the path.
  Enabling them needs more than the flag (per-day objective wiring +
  the week-mono loop must forward ``is_hard``/``soft_weight``) -- see
  ``ConstraintModel.add_all_dsl_constraints_from_db``.
"""
from __future__ import annotations

from typing import Any


def _quote(s: str) -> str:
    """Quote a literal string so the DSL tokenizer reads it as a
    single STRING token. Uses double-quotes; escapes inner double-
    quotes."""
    return '"' + str(s).replace('\\', '\\\\').replace('"', '\\"') + '"'


# ---------------------------------------------------------------------
# Translators (one per ORM model)
# ---------------------------------------------------------------------


def teacher_unavailability_to_dsl(teacher_name: str, day: int,
                                    hour: int) -> str:
    """A HARD/SOFT teacher unavailability row becomes:

        forall l in lessons where l.teacher == "<name>"
                              and l.day == <d>
                              and l.hour == <h>: false
    """
    return (f'forall l in lessons where l.teacher == {_quote(teacher_name)}'
            f' and l.day == {int(day)} and l.hour == {int(hour)}: false')


def class_unavailability_to_dsl(class_name: str, day: int,
                                  hour: int) -> str:
    return (f'forall l in lessons where l.class == {_quote(class_name)}'
            f' and l.day == {int(day)} and l.hour == {int(hour)}: false')


def classroom_unavailability_to_dsl(classroom_name: str, day: int,
                                      hour: int) -> str:
    """Classroom availability is post-CG (rooms decided by the
    classroom-assignment solver). The DSL form is identical -- it
    constrains lessons placed in that room. Compilation skips when
    the slot model has no classroom dimension; the helper still
    yields a parseable expression so callers can store it
    uniformly."""
    return (f'forall l in lessons where l.classroom == {_quote(classroom_name)}'
            f' and l.day == {int(day)} and l.hour == {int(hour)}: false')


def teacher_mandatory_free_day_to_dsl(teacher_name: str, day: int) -> str:
    """All-day-off rule: the teacher has zero lessons on the given day."""
    return (f'count l in lessons where l.teacher == {_quote(teacher_name)}'
            f' and l.day == {int(day)} == 0')


def teacher_at_least_n_free_days_to_dsl(teacher_name: str, n: int) -> str:
    """Free-day floor: the teacher must have at least ``n`` days
    in the week with zero lessons. Emitted as the canonical pragma
    ``teacher_at_least_n_free_days("<name>", n)``.

    With n=1 this is the universal CCNL-style "at least one free day"
    rule. The compiler builds per-(teacher, day) busy indicators and
    constrains their sum to be at most ``num_days - n``."""
    return (f'teacher_at_least_n_free_days('
            f'{_quote(teacher_name)}, {int(n)})')


def teacher_preferred_free_day_penalty_to_dsl(teacher_name: str,
                                                day: int,
                                                weight: int) -> str:
    """SOFT preference: pay ``weight`` if the teacher has any lesson on
    ``day``. Emitted as the canonical pragma
    ``teacher_preferred_free_day_penalty("<name>", day, weight)``.

    Used to express the priority-ordered free-day preferences (the
    UI's 1st/2nd/3rd choice with weights 30/20/10 by default). The
    solver minimises the sum of these soft costs so the higher-weight
    choice is honored first."""
    return (f'teacher_preferred_free_day_penalty('
            f'{_quote(teacher_name)}, {int(day)}, {int(weight)})')


def teacher_max_consecutive_to_dsl(teacher_name: str, n: int) -> str:
    """Teacher cannot exceed ``n`` consecutive hours per day.

    Emitted as the canonical pragma ``teacher_max_consecutive(name, n)``,
    which the compiler expands into per-day sliding-window constraints:
    in any window of (n+1) consecutive hours the teacher occupies at
    most n of them (no run of n+1). This replaces an earlier generic
    nested-forall/count form whose dynamic window the compiler could
    not translate (it was stored but silently skipped)."""
    return (f'teacher_max_consecutive('
            f'{_quote(teacher_name)}, {int(n)})')


def class_no_holes_to_dsl(class_name: str) -> str:
    """No-holes per class. Emitted as a canonical-pattern pragma the
    DSL compiler recognises directly (``no_holes_class("<name>")``)
    and translates into the same compact non-increasing-chain
    encoding that the legacy ``add_class_no_holes`` uses. The
    pragma lives in the DSL function vocabulary and parses cleanly
    via ``general_dsl``."""
    return f'no_holes_class({_quote(class_name)})'


def class_h11_presence_to_dsl(class_name: str) -> str:
    """If the class has any lesson on a day, the slot at h=11 must
    be busy (HARD-2 / "uscita non prima delle 12"). Emitted as
    ``class_present_at_hour("<name>", 11)``."""
    return f'class_present_at_hour({_quote(class_name)}, 11)'


def class_day_load_in_to_dsl(class_name: str,
                                allowed: list[int]) -> str:
    """The class' daily busy-hour count must lie in the given set
    (legacy HARD-1+HARD-2 packed: ``cl_day_load in {0,4,5,6}``).
    Emitted as ``class_day_load_in("<name>", v1, v2, ...)``."""
    parts = [_quote(class_name)] + [str(int(v)) for v in allowed]
    return f'class_day_load_in({", ".join(parts)})'


def teacher_max_per_day_to_dsl(teacher_name: str, n: int) -> str:
    """Teacher daily load cap (legacy HARD-C: max 5 hours/day).
    Emitted as ``teacher_max_per_day("<name>", n)``."""
    return f'teacher_max_per_day({_quote(teacher_name)}, {int(n)})'


def cattedra_max_per_day_to_dsl(teacher_name: str, class_name: str,
                                  subject: str, n: int) -> str:
    """Per-cattedra daily cap (legacy MAX_PER_DAY_TRIPLE = 2).
    Emitted as ``cattedra_max_per_day("<t>", "<c>", "<s>", n)``."""
    return (
        f'cattedra_max_per_day({_quote(teacher_name)}, '
        f'{_quote(class_name)}, {_quote(subject)}, {int(n)})')


def subject_pair_must_to_dsl(class_name: str, subject: str) -> str:
    """When ``subject`` has 2 hours/day for ``class``, they MUST be
    consecutive (Scienzemotorie pattern). Emitted as
    ``subject_pair_must("<class>", "<subject>")``."""
    return (
        f'subject_pair_must({_quote(class_name)}, {_quote(subject)})')


def subject_pair_exists_to_dsl(class_name: str, subject: str) -> str:
    """When ``subject`` has >= 2 hours/day, at least one consecutive
    pair must exist (Mat/Ita pattern). Emitted as
    ``subject_pair_exists("<class>", "<subject>")``."""
    return (
        f'subject_pair_exists({_quote(class_name)}, '
        f'{_quote(subject)})')


# ---------------------------------------------------------------------
# Coteach + plessi (kept simpler -- richer semantics in follow-up)
# ---------------------------------------------------------------------


def coteach_group_to_dsl(class_name: str, subject: str,
                          teacher_names: list[str], n_hours: int,
                          required: bool) -> list[str]:
    """A coteach group is multi-clause:

      1. Each teacher in the group has exactly n_hours of (class,
         subject) per week.
      2. Teachers' hours coincide on the same slots (slot-equality).

    Returns a list of DSL strings (one per clause). If ``required``
    is False, the rules are SOFT (compiler TODO).
    """
    if not teacher_names or len(teacher_names) < 2:
        return []
    out: list[str] = []
    # Clause 1: per teacher, count == n_hours
    for t in teacher_names:
        out.append(
            f'count l in lessons where l.class == {_quote(class_name)}'
            f' and l.subject == {_quote(subject)}'
            f' and l.teacher == {_quote(t)} == {int(n_hours)}')
    # Clause 2: pair-wise slot equality between principal and each codoc.
    principal = teacher_names[0]
    for t in teacher_names[1:]:
        out.append(
            f'forall l1 in lessons where l1.class == {_quote(class_name)}'
            f' and l1.subject == {_quote(subject)}'
            f' and l1.teacher == {_quote(principal)}: '
            f'forall l2 in lessons where l2.class == {_quote(class_name)}'
            f' and l2.subject == {_quote(subject)}'
            f' and l2.teacher == {_quote(t)}: '
            f'same_day(l1.slot, l2.slot)')
    return out


def plesso_commuting_rule_to_dsl(
    rule, *, teacher_name: str | None = None,
) -> list[str]:
    """Translate one PlessoCommutingRule into a list of DSL strings.

    The DSL relies on the chained ``l.classroom.plesso`` accessor
    introduced in Step 3a + the canonical ``consecutive(slot, slot)``
    DSL function. Compilation requires the caller to plumb
    ``classroom_for_slot`` and ``plessi_data`` through
    ``add_dsl_constraint`` so the static evaluator can resolve the
    classroom -> plesso chain.

    Supported rule shapes (entity_kind='teacher'):

      - ``min_gap_hours >= 1``: any adjacent (h, h+1) slot pair
        crossing the (from_plesso, to_plesso) pair is forbidden.
      - ``allowed_break_only=True`` with both break hours set: every
        adjacent pair is forbidden except the
        (break_start, break_end) pair (and its reverse for symmetric
        rules).
      - ``min_gap_hours == 0`` and not ``allowed_break_only``: no
        constraint -> empty list.
      - ``entity_id`` set + ``teacher_name`` provided -> per-teacher;
        ``entity_id is None`` -> kind-wide (every teacher).

    Returns the list of DSL clause strings (one per directed plesso
    pair). For symmetric rules both directions are emitted.

    Raises ``NotImplementedError`` for entity_kind in {'class',
    'group'}; those use a slightly different structure (class-side
    iteration) and can be added incrementally.
    """
    kind = getattr(rule, "entity_kind", None) or rule.get("entity_kind")
    if kind != "teacher":
        raise NotImplementedError(
            f"plesso_commuting_rule_to_dsl: entity_kind={kind!r} "
            "not yet supported (only 'teacher')")

    def _attr(name, default=None):
        if hasattr(rule, name):
            return getattr(rule, name)
        if isinstance(rule, dict):
            return rule.get(name, default)
        return default

    from_pl = int(_attr("from_plesso_id"))
    to_pl = int(_attr("to_plesso_id"))
    entity_id = _attr("entity_id")
    min_gap = int(_attr("min_gap_hours", 0) or 0)
    allowed_break_only = bool(_attr("allowed_break_only", False))
    bs = _attr("break_start_hour")
    be = _attr("break_end_hour")
    symmetric = bool(_attr("symmetric", True))

    # Decide whether the rule forbids adjacency at all.
    if min_gap < 1 and not allowed_break_only:
        return []

    pairs = [(from_pl, to_pl)]
    if symmetric:
        pairs.append((to_pl, from_pl))

    # Teacher filter
    if entity_id is not None and teacher_name:
        l1_teacher = (
            f' and l1.teacher == {_quote(teacher_name)}')
        l2_teacher = (
            f' and l2.teacher == {_quote(teacher_name)}')
    else:
        # Kind-wide: pair shares a teacher (resolved via
        # l1/l2 binding).
        l1_teacher = ''
        l2_teacher = ' and l2.teacher == l1.teacher'

    # Allowed break exception (only for allowed_break_only).
    if allowed_break_only and bs is not None and be is not None:
        bs_i, be_i = int(bs), int(be)
        # Forbid pair (l1.hour, l2.hour) UNLESS
        #   (l1.hour, l2.hour) in {(bs, be), (be, bs)}.
        # Encoded by adding a where clause that excludes the
        # break pair, leaving the non-break adjacency as the
        # forbidden region.
        break_excl = (
            f' and not ((l1.hour == {bs_i} and l2.hour == {be_i})'
            f' or (l1.hour == {be_i} and l2.hour == {bs_i}))')
    else:
        break_excl = ''

    out: list[str] = []
    for (from_p, to_p) in pairs:
        clause = (
            f'forall l1 in lessons where '
            f'l1.classroom.plesso == {int(from_p)}'
            f'{l1_teacher}: '
            f'forall l2 in lessons where '
            f'l2.classroom.plesso == {int(to_p)}'
            f'{l2_teacher}'
            f' and consecutive(l1.slot, l2.slot)'
            f'{break_excl}: '
            f'false'
        )
        out.append(clause)
    return out


# ---------------------------------------------------------------------
# Seed generator: in-memory DSL forms for the legacy hardcoded HARD
# constraints in ``cpsat_v2_timetable``. The function takes the same
# inputs the legacy solvers receive (profs map + dc_value cattedra-
# day demand) and returns a list of DSL strings that, when compiled
# onto a ``MonolithicSolver``, produce the same HARD constraints as
# the legacy hardcoded path (zero-drift property).
#
# Coverage (the legacy invariants):
#   - cattedra_max_per_day(t, c, s, MAX_PER_DAY_TRIPLE=2)        per cattedra
#   - teacher_max_per_day(t, MAX_PROF_HOURS_PER_DAY=5)           per docente
#   - subject_pair_must(c, "Scienzemotorie")                     HARD-B
#   - subject_pair_exists(c, "Matematica") + Italiano            HARD-A
#   - class_day_load_in(c, 0, 4, 5, 6)                           HARD-1+HARD-2
#   - no_holes_class(c)                                          enforce_no_holes
#   - class_present_at_hour(c, 11)                               HARD-3
#
# Out-of-scope here (handled separately or by other paths):
#   - TeacherUnavailability / ClassUnavailability rows           load_all_dsl_constraints
#   - CoteachGroup / parallel groups / sostegno / potenziamento  function-based wiring
#     (these have richer multi-clause structure that is best
#      kept in the function-based legacy until the OO/DSL path
#      grows the matching pragmas)
# ---------------------------------------------------------------------


# Default constants (mirror cpsat_v2_timetable module-level values).
DEFAULT_MAX_PER_DAY_TRIPLE = 2
DEFAULT_MAX_PROF_HOURS_PER_DAY = 5
DEFAULT_CLASS_DAY_LOAD_ALLOWED = (0, 4, 5, 6)
DEFAULT_H3_HOUR = 11


def seed_implicit_hardcoded(
    profs: dict,
    classes: list | None = None,
    *,
    max_per_day_triple: int = DEFAULT_MAX_PER_DAY_TRIPLE,
    max_prof_hours_per_day: int = DEFAULT_MAX_PROF_HOURS_PER_DAY,
    class_day_load_allowed: tuple = DEFAULT_CLASS_DAY_LOAD_ALLOWED,
    h3_hour: int = DEFAULT_H3_HOUR,
    enforce_no_holes: bool = True,
    enforce_h3_presence: bool = True,
    enforce_motorie_pair: bool = True,
    enforce_math_italian_pair: bool = True,
    enforce_class_day_load: bool = True,
    enforce_max_per_day_triple: bool = True,
    enforce_max_prof_hours_per_day: bool = True,
) -> list[str]:
    """Return the list of DSL strings that encode the legacy
    hardcoded HARD constraints for the given ``profs`` map.

    The output is fed to ``ConstraintModel.add_all_dsl_constraints``
    and produces the same CP-SAT encoding as the legacy methods
    (``add_class_no_holes``, ``add_h3_presence_at_11``,
    ``add_motorie_pair``, ``add_math_italian_pair``, ...). Each
    flag toggles whether to emit the corresponding family.

    Determinism: rules are emitted in a stable order
    (by class name, then teacher name, then subject) so the CP-SAT
    model construction order matches across runs.
    """
    out: list[str] = []
    profs = profs or {}
    if classes is None:
        classes = sorted({c for p in profs.values()
                          for c in p.get("classi", {})})
    classes = sorted(classes)

    # --- per-cattedra cap (MAX_PER_DAY_TRIPLE) ---
    if enforce_max_per_day_triple:
        triples: list[tuple[str, str, str]] = []
        for t, info in profs.items():
            for cl, subjs in info.get("classi", {}).items():
                for s in subjs:
                    triples.append((t, cl, s))
        triples.sort()
        for (t, cl, s) in triples:
            out.append(cattedra_max_per_day_to_dsl(
                t, cl, s, max_per_day_triple))

    # --- per-teacher daily cap (MAX_PROF_HOURS_PER_DAY) ---
    if enforce_max_prof_hours_per_day:
        for t in sorted(profs):
            out.append(teacher_max_per_day_to_dsl(
                t, max_prof_hours_per_day))

    # --- HARD-1 + HARD-2: cl_day_load in {0, 4, 5, 6} ---
    if enforce_class_day_load:
        for cl in classes:
            out.append(class_day_load_in_to_dsl(
                cl, list(class_day_load_allowed)))

    # --- enforce_no_holes per class ---
    if enforce_no_holes:
        for cl in classes:
            out.append(class_no_holes_to_dsl(cl))

    # --- HARD-3: presence at h=11 per class ---
    if enforce_h3_presence:
        for cl in classes:
            if h3_hour == 11:
                out.append(class_h11_presence_to_dsl(cl))
            else:
                out.append(
                    f'class_present_at_hour({_quote(cl)}, '
                    f'{int(h3_hour)})')

    # --- HARD-B: motorie pair (must_pair) ---
    if enforce_motorie_pair:
        for cl in classes:
            # Only emit the pragma when the class actually has a
            # Scienzemotorie cattedra; otherwise the pragma is a
            # no-op but still valid DSL.
            has_motorie = any(
                "Scienzemotorie" in p.get("classi", {}).get(cl, {})
                for p in profs.values())
            if has_motorie:
                out.append(subject_pair_must_to_dsl(
                    cl, "Scienzemotorie"))

    # --- HARD-A: Mat/Ita pair_exists ---
    if enforce_math_italian_pair:
        for cl in classes:
            for subj in ("Matematica", "Italiano"):
                has_subj = any(
                    subj in p.get("classi", {}).get(cl, {})
                    for p in profs.values())
                if has_subj:
                    out.append(subject_pair_exists_to_dsl(cl, subj))

    return out


def build_soft_pragmas(profs, classes, *, scale_mode="default", level=None):
    """Return the structural soft-pragma DSL stream for a pipeline.

    ``scale_mode`` selects the weights + which penalties apply:
      - ``'default'``: per-slot sixth (``PENALTY_SIXTH``), buchi
        (``PENALTY_BUCHI``), five (``PENALTY_FIVE``), one
        (``PENALTY_ONE``).
      - ``'phase_b_per_day'``: per-class-busy sixth (``PENALTY_SIXTH_PD``),
        buchi (``PENALTY_BUCHI_PD``); five/one are excluded because the
        per-day decomposition has no weekly day-count to penalize.

    Weights are imported from ``cp_sat_constraint_model`` so the numbers
    are read from today's constants, not retyped. This emitter is unused
    by any pipeline here; sub-project B feeds the returned stream into
    each pipeline's ``DSLConstraintCompiler``. The ``profs`` / ``classes``
    / ``level`` params are part of the stable sub-project-B-facing
    signature even though the structural pragmas do not need them yet.
    """
    try:
        from engine import cp_sat_constraint_model as csm  # type: ignore
    except ImportError:
        import cp_sat_constraint_model as csm  # type: ignore
    out: list[str] = []
    if scale_mode == "default":
        out.append(f'class_sixth_penalty({csm.PENALTY_SIXTH}, "slot")')
        out.append(f'teacher_buchi_penalty({csm.PENALTY_BUCHI})')
        out.append(f'teacher_five_penalty({csm.PENALTY_FIVE})')
        out.append(f'teacher_one_penalty({csm.PENALTY_ONE})')
    elif scale_mode == "phase_b_per_day":
        out.append(f'class_sixth_penalty({csm.PENALTY_SIXTH_PD}, "class_busy")')
        out.append(f'teacher_buchi_penalty({csm.PENALTY_BUCHI_PD})')
    else:
        raise ValueError(f"unknown scale_mode {scale_mode!r}")
    return out


# ---------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------


def load_all_dsl_constraints(db,
                              *,
                              include_soft: bool = False) -> list[dict]:
    """Aggregate every constraint table into a unified list of DSL
    expressions ready for ``ConstraintModel.add_all_dsl_constraints``.

    Parameters
    ----------
    db : Session
        SQLAlchemy session.
    include_soft : bool
        when False (default), only HARD rules are returned. SOFT
        translation is TODO; the compiler currently logs SOFT rules
        in diagnostics rather than enforcing them.

    Returns
    -------
    list of dicts ``{source, scope_kind, scope_id, expression,
    is_hard, weight, label}`` where ``expression`` is a DSL string.

    The returned ordering is stable: TeacherUnavailability rows
    first, then ClassUnavailability, then ClassroomUnavailability,
    then TeacherMandatoryFreeDay, then per-teacher
    `teacher_at_least_n_free_days` HARD floor (sourced from
    Teacher.min_free_days), then per-teacher
    `teacher_preferred_free_day_penalty` priority preferences
    (sourced from TeacherFreeDayPreference rows), then
    CoteachGroup, then LogicalUnavailability, then
    CurriculumLogicalConstraint, then GeneralConstraint (the
    user-authored DSL rules saved via /api/constraints/general for
    any scope -- global / teacher / class / classroom / group /
    subject / curriculum). This determinism keeps the CP-SAT model
    construction order stable across runs.
    """
    try:
        from webui.backend import models  # type: ignore
    except ImportError:
        from backend import models  # type: ignore

    out: list[dict] = []
    teachers = {t.id: t.name for t in db.query(models.Teacher).all()}
    classes = {c.id: c.name for c in db.query(models.SchoolClass).all()}
    rooms = {r.id: r.name for r in db.query(models.Classroom).all()}

    # 1. TeacherUnavailability
    for r in db.query(models.TeacherUnavailability).all():
        is_hard = (r.state == "hard")
        if not is_hard and not include_soft:
            continue
        n = teachers.get(r.teacher_id)
        if not n:
            continue
        out.append({
            "source": "teacher_unavailability",
            "scope_kind": "teacher", "scope_id": r.teacher_id,
            "expression": teacher_unavailability_to_dsl(
                n, r.day, r.hour),
            "is_hard": is_hard,
            "weight": 0 if is_hard else int(r.soft_penalty or 100),
            "label": f"Docente {n} non disp. {r.day}-{r.hour}",
        })

    # 2. ClassUnavailability
    for r in db.query(models.ClassUnavailability).all():
        is_hard = (r.state == "hard")
        if not is_hard and not include_soft:
            continue
        n = classes.get(r.class_id)
        if not n:
            continue
        out.append({
            "source": "class_unavailability",
            "scope_kind": "class", "scope_id": r.class_id,
            "expression": class_unavailability_to_dsl(
                n, r.day, r.hour),
            "is_hard": is_hard,
            "weight": 0 if is_hard else int(r.soft_penalty or 100),
            "label": f"Classe {n} non disp. {r.day}-{r.hour}",
        })

    # 3. ClassroomUnavailability
    for r in db.query(models.ClassroomUnavailability).all():
        is_hard = (r.state == "hard")
        if not is_hard and not include_soft:
            continue
        n = rooms.get(r.classroom_id)
        if not n:
            continue
        out.append({
            "source": "classroom_unavailability",
            "scope_kind": "classroom", "scope_id": r.classroom_id,
            "expression": classroom_unavailability_to_dsl(
                n, r.day, r.hour),
            "is_hard": is_hard,
            "weight": 0 if is_hard else int(r.soft_penalty or 100),
            "label": f"Aula {n} non disp. {r.day}-{r.hour}",
        })

    # 4. TeacherMandatoryFreeDay
    for r in db.query(models.TeacherMandatoryFreeDay).all():
        n = teachers.get(r.teacher_id)
        if not n:
            continue
        out.append({
            "source": "teacher_mandatory_free_day",
            "scope_kind": "teacher", "scope_id": r.teacher_id,
            "expression": teacher_mandatory_free_day_to_dsl(
                n, r.day),
            "is_hard": True,
            "weight": 0,
            "label": f"Docente {n} giorno libero {r.day}",
        })

    # 4b. Per-teacher HARD floor "at least N free days" sourced from
    # Teacher.min_free_days (default 1 = CCNL "almeno un giorno libero",
    # but per-teacher overrides support 2 or 3 free days for part-time
    # contracts and similar). Emitted as the canonical
    # `teacher_at_least_n_free_days(name, n)` pragma so it works in
    # both Phase A and Phase B contexts -- previously this rule was
    # implicit in the Phase A `free_day_choice_3way` pragma, which
    # got bypassed by the cpsat_week / cpsat_day_skip_phase_a /
    # cpsat_day_soft_hint techniques. With the new pragma the floor
    # is enforced uniformly regardless of solver scope. n=0 is treated
    # as "no constraint" and skipped.
    for t in db.query(models.Teacher).all():
        n_floor = int(getattr(t, "min_free_days", 1) or 0)
        if n_floor <= 0:
            continue
        out.append({
            "source": "teacher_at_least_n_free_days",
            "scope_kind": "teacher", "scope_id": t.id,
            "expression": teacher_at_least_n_free_days_to_dsl(
                t.name, n_floor),
            "is_hard": True,
            "weight": 0,
            "label": (f"Docente {t.name} almeno {n_floor} "
                      f"giorn{'o' if n_floor == 1 else 'i'} liber"
                      f"{'o' if n_floor == 1 else 'i'}/sett."),
        })

    # 4b-bis. Per-teacher "max consecutive hours per day" HARD cap
    # sourced from Teacher.max_consecutive. Emitted as the canonical
    # `teacher_max_consecutive(name, n)` pragma (phase_b: it constrains
    # slot runs). Only emitted when 1 <= n < DAILY_HOURS so the rule
    # can actually bind: n >= the day length is a guaranteed no-op and
    # would only flood every pipeline with vacuous constraints. n <= 0
    # is treated as "unlimited" and skipped.
    DAILY_HOURS = 6  # canonical 8..13 grid; n >= 6 never binds
    for t in db.query(models.Teacher).all():
        n_mc = int(getattr(t, "max_consecutive", 0) or 0)
        if n_mc < 1 or n_mc >= DAILY_HOURS:
            continue
        out.append({
            "source": "teacher_max_consecutive",
            "scope_kind": "teacher", "scope_id": t.id,
            "expression": teacher_max_consecutive_to_dsl(t.name, n_mc),
            "is_hard": True,
            "weight": 0,
            "label": (f"Docente {t.name} max {n_mc} ore consecutive/giorno"),
        })

    # 4c. Per-teacher priority-ordered free-day preferences sourced
    # from the dedicated `TeacherFreeDayPreference` table. Each row
    # is (teacher_id, day, priority) where priority in {1, 2, 3}
    # maps to weights {30, 20, 10} -- the 1st choice costs the most
    # to ignore so the solver honors it first under minimisation.
    if include_soft and hasattr(models, "TeacherFreeDayPreference"):
        PRIORITY_WEIGHT = {1: 30, 2: 20, 3: 10}
        for r in (db.query(models.TeacherFreeDayPreference)
                    .order_by(
                        models.TeacherFreeDayPreference.teacher_id,
                        models.TeacherFreeDayPreference.priority)
                    .all()):
            n = teachers.get(r.teacher_id)
            if not n:
                continue
            weight = PRIORITY_WEIGHT.get(int(r.priority))
            if weight is None or weight == 0:
                continue
            day = int(r.day)
            if day < 1 or day > 6:
                continue
            out.append({
                "source": "teacher_free_day_preference",
                "scope_kind": "teacher", "scope_id": r.teacher_id,
                "expression": teacher_preferred_free_day_penalty_to_dsl(
                    n, day, weight),
                "is_hard": False,
                "weight": weight,
                "label": (f"Docente {n} preferenza giorno libero "
                          f"{day} (SOFT pri.{int(r.priority)}, "
                          f"w={weight})"),
            })

    # 5. CoteachGroup (HARD when required=True)
    if hasattr(models, "CoteachGroup"):
        for g in db.query(models.CoteachGroup).all():
            if not g.required and not include_soft:
                continue
            cl_name = (
                classes.get(g.class_id) if g.class_id is not None
                else None)
            if cl_name is None:
                continue
            t_names = []
            for asg in (g.assignments or []):
                tn = teachers.get(asg.teacher_id)
                if tn and tn not in t_names:
                    t_names.append(tn)
            if len(t_names) < 2:
                continue
            for clause in coteach_group_to_dsl(
                    cl_name, g.subject, t_names,
                    int(g.n_hours), bool(g.required)):
                out.append({
                    "source": "coteach_group",
                    "scope_kind": "class", "scope_id": g.class_id,
                    "expression": clause,
                    "is_hard": bool(g.required),
                    "weight": 0 if g.required else int(g.weight or 100),
                    "label": (f"Coteach {cl_name}/"
                              f"{g.subject} ({len(t_names)} doc.)"),
                })

    # 6. LogicalUnavailability (already DSL, just pass through)
    for r in db.query(models.LogicalUnavailability).all():
        is_hard = bool(r.is_hard) and (r.kind in ("hard", "enforced"))
        if not is_hard and not include_soft:
            continue
        out.append({
            "source": "logical_unavailability",
            "scope_kind": r.entity_type,
            "scope_id": r.entity_id,
            "expression": r.expression,
            "is_hard": is_hard,
            "weight": 0 if is_hard else int(r.soft_penalty or 100),
            "label": f"DSL {r.entity_type}#{r.entity_id}",
        })

    # 7. CurriculumLogicalConstraint
    if hasattr(models, "CurriculumLogicalConstraint"):
        for r in db.query(models.CurriculumLogicalConstraint).all():
            is_hard = bool(r.is_hard) and (r.kind in ("hard", "enforced"))
            if not is_hard and not include_soft:
                continue
            out.append({
                "source": "curriculum_logical_constraint",
                "scope_kind": "curriculum",
                "scope_id": r.curriculum_id,
                "expression": r.expression,
                "is_hard": is_hard,
                "weight": 0 if is_hard else int(r.soft_penalty or 100),
                "label": (r.label
                          or f"Curriculum#{r.curriculum_id}"),
            })

    # 8. GeneralConstraint (user-authored DSL via /api/constraints/general).
    # Any scope is forwarded to the compiler via scope_kind/scope_id; the
    # DSLConstraintCompiler treats the expression as a top-level rule and
    # the entity scoping is informational (the rule body itself filters
    # via `forall l in lessons where l.teacher == ...`).
    if hasattr(models, "GeneralConstraint"):
        for r in db.query(models.GeneralConstraint).all():
            is_hard = (r.level in ("hard", "enforced"))
            if not is_hard and not include_soft:
                continue
            out.append({
                "source": "general_constraint",
                "scope_kind": r.scope or "global",
                "scope_id": r.owner_id,
                "expression": r.expression,
                "is_hard": is_hard,
                "weight": 0 if is_hard else int(r.weight or 100),
                "label": (r.label or f"DSL #{r.id}"),
            })

    return out
