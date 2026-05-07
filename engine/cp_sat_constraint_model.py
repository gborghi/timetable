"""Object-oriented CP-SAT constraint model for piTantum.

This module introduces a class-based abstraction over the CP-SAT
sub-problems that piTantum builds: the monolithic Phase B solver and
each Branch-and-Price pricer. Both share the same slot variables and
the same HARD/SOFT constraint catalogue; they differ only in scope
(which slots are decision variables vs fixed) and in the objective
(real soft cost for the mono, dual-driven reduced cost for pricers).

Class hierarchy
---------------

    ConstraintModel      -- base: variables, scope filter, every
                            add_*_constraint() method, soft-cost expr.
        MonolithicSolver -- Phase-B-style mono: minimize soft cost.
        PricerSolver     -- BP pricer: minimize soft - dual_bonus,
                            with optional Ryan-Foster branching
                            constraints.
            TeacherPricer -- per-teacher granularity (PoC).
            (8 more pricer subclasses to follow in later commits.)

Slot key convention
-------------------

The base class stores ``slot[(teacher, class_name, subject, day, hour)]``
as the canonical 5-tuple BoolVar dictionary. Sub-classes filter the
domain by ``scope`` so that, e.g., ``TeacherPricer(scope=("teacher",
"Rossi"))`` only allocates slot vars whose first element is "Rossi".
The legacy Phase B in ``cpsat_v2_timetable.py`` keeps its existing
4-tuple per-day encoding; ``MonolithicSolver`` is provided as the
forward-looking equivalent, but is NOT yet wired into the pipeline
(the function-style Phase B continues to run untouched).

Why a single hierarchy
----------------------

Every HARD/SOFT constraint of the school timetabling problem (no-holes,
math/italian dual pair, motorie pair, h=11 presence, max-per-day cap,
locks, coteaching, sostegno, potenziamento, parallel groups, plessi
commuting/policies, ...) is a ``add_*`` method on the base. New
constraints (e.g. plessi entity policies) are added once on the base
and inherited by every solver. No drift between mono and pricers.

This commit lands the scaffolding plus the methods needed to migrate
``_pricing_subproblem_teacher`` to ``TeacherPricer``. Future commits
extend the catalogue (motorie pairs, h=11, coteaching, ...) and the
pricer subclasses.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from ortools.sat.python import cp_model

try:
    from . import metaheuristics as meta  # type: ignore
except ImportError:  # direct script import (no package context)
    import metaheuristics as meta  # type: ignore


DAYS = meta.DAYS
HOURS = meta.HOURS

# Integer scaling for fractional duals (kept identical to
# column_generation.py so reduced-cost arithmetic is consistent).
SCALE = 100

# SOFT penalty constants -- derived from meta.OBJECTIVE_WEIGHTS so
# the CP-SAT objective tracks meta.compute_soft term by term.
PENALTY_SIXTH = meta.OBJECTIVE_WEIGHTS["sixth"] * SCALE
PENALTY_BUCHI = meta.OBJECTIVE_WEIGHTS["buchi"] * SCALE
PENALTY_FIVE = meta.OBJECTIVE_WEIGHTS["five"] * SCALE
PENALTY_ONE = meta.OBJECTIVE_WEIGHTS["one"] * SCALE
SIXTH_HOUR = 13


@dataclass
class ConstraintConfig:
    """Bundle of HARD/SOFT toggles + payload data the model uses."""
    enforce_no_holes: bool = True
    enforce_h3_presence_at_11: bool = True
    enforce_motorie_pair: bool = True
    enforce_math_italian_pair: bool = True
    locks: list = field(default_factory=list)
    coteach_groups: list = field(default_factory=list)
    support_assignments: list = field(default_factory=list)
    potenziamento_assignments: list = field(default_factory=list)
    parallel_groups: list = field(default_factory=list)
    group_assignments: list = field(default_factory=list)
    plessi_data: Any = None


# ============================================================
# ConstraintModel base
# ============================================================

class ConstraintModel:
    """Base CP-SAT model with the full HARD/SOFT constraint catalogue.

    Sub-classes pick a *scope* (e.g. ``("teacher", "Rossi")``,
    ``("class", "1A")``, ``("class_day", "1A", 2)``) which restricts
    the slot vars to that slice. They then call
    ``add_all_hard_constraints()`` (or a subset) to populate the model
    and define their own objective via ``compute_soft_cost_expr()``
    plus, for pricers, a dual-driven bonus.

    The mono solver populates every slot var that has positive demand
    in the input ``dc_value``; pricers populate only the slots their
    scope covers (the rest stays in the greedy base / fixed load).
    """

    def __init__(
        self,
        profs: dict,
        dc_value: dict,
        config: ConstraintConfig | None = None,
        *,
        scope: tuple | None = None,
        days: Iterable[int] | None = None,
        hours: Iterable[int] | None = None,
        classroom_for_slot: dict | None = None,
    ):
        self.profs = profs
        self.dc_value = dc_value
        self.config = config or ConstraintConfig()
        self.scope = scope
        self.days = list(days) if days is not None else list(DAYS)
        self.hours = list(hours) if hours is not None else list(HOURS)
        self.model = cp_model.CpModel()
        # slot[(teacher, class_name, subject, day, hour)] -> BoolVar
        self.slot: dict[tuple, Any] = {}
        # Greedy/locked fixed contributions outside the CP-SAT scope:
        # fixed_load[(teacher, day, hour)] = 1 means "this teacher is
        # busy at (day, hour) for some out-of-scope assignment".
        self.fixed_load: dict[tuple, int] = {}
        # Cattedra-day demand expanded from dc_value, scoped:
        # triples[(teacher, class, subject)] = list[(day, q)] with q>0
        self.triples: dict[tuple, list] = {}
        # Optional ``(class, day, hour) -> classroom_name`` mapping,
        # used by the DSL compiler to resolve ``l.classroom`` /
        # ``l.classroom.plesso`` references when the post-CG
        # classroom assignment is already known. ``None`` means
        # rooms are still unassigned and DSL rules touching the
        # classroom dimension will be skipped with a diagnostic.
        self.classroom_for_slot = classroom_for_slot
        self._build_slot_variables()

    # ----- variable construction -----

    def _scope_includes_teacher(self, teacher: str) -> bool:
        if self.scope is None:
            return True
        kind = self.scope[0]
        if kind == "teacher":
            return self.scope[1] == teacher
        if kind == "teacher_class":
            return self.scope[1] == teacher
        if kind == "teacher_class_subject":
            return self.scope[1] == teacher
        if kind == "teacher_subject":
            return self.scope[1] == teacher
        if kind == "teacher_day":
            return self.scope[1] == teacher
        # class-side scopes do not filter by teacher.
        return True

    def _scope_includes_slot(self, teacher: str, class_name: str,
                              subject: str, day: int) -> bool:
        if self.scope is None:
            return True
        kind = self.scope[0]
        if kind == "teacher":
            return self.scope[1] == teacher
        if kind == "teacher_class":
            return (self.scope[1] == teacher
                    and self.scope[2] == class_name)
        if kind == "teacher_class_subject":
            return (self.scope[1] == teacher
                    and self.scope[2] == class_name
                    and self.scope[3] == subject)
        if kind == "teacher_subject":
            return (self.scope[1] == teacher
                    and self.scope[2] == subject)
        if kind == "teacher_day":
            return (self.scope[1] == teacher
                    and self.scope[2] == day)
        if kind == "class":
            return self.scope[1] == class_name
        if kind == "class_day":
            return (self.scope[1] == class_name
                    and self.scope[2] == day)
        if kind == "day":
            return self.scope[1] == day
        # other scopes (curriculum, etc.) are managed by sub-classes
        # via override of _scope_includes_slot.
        return True

    def _build_slot_variables(self):
        """Populate ``self.slot`` and ``self.triples`` from
        ``self.profs`` and ``self.dc_value``, filtered by scope.

        Adds the cattedra-day equality constraint
            sum_h slot[(t, cl, s, d, h)] == dc_value[(t, cl, s, d)]
        for every active (t, cl, s, d).
        """
        for teacher, pdata in self.profs.items():
            if not self._scope_includes_teacher(teacher):
                continue
            classi = pdata.get("classi", {}) or {}
            for class_name, subjs in classi.items():
                for subject in subjs:
                    triples_key = (teacher, class_name, subject)
                    for d in self.days:
                        if not self._scope_includes_slot(
                                teacher, class_name, subject, d):
                            continue
                        q = int(self.dc_value.get(
                            (teacher, class_name, subject, d), 0))
                        if q <= 0:
                            continue
                        self.triples.setdefault(triples_key, []).append(
                            (d, q))
                        for h in self.hours:
                            v = self.model.NewBoolVar(
                                f"slot_{teacher}_{class_name}_"
                                f"{subject}_{d}_{h}")
                            self.slot[(teacher, class_name, subject,
                                        d, h)] = v
                        self.model.Add(
                            sum(self.slot[(teacher, class_name,
                                            subject, d, h)]
                                 for h in self.hours) == q)

    # ----- helpers -----

    def teachers_in_scope(self) -> list:
        return sorted({k[0] for k in self.slot})

    def classes_in_scope(self) -> list:
        return sorted({k[1] for k in self.slot})

    def slots_for_teacher_day_hour(self, teacher: str, day: int,
                                    hour: int) -> list:
        return [v for (t, _cl, _s, d, h), v in self.slot.items()
                if t == teacher and d == day and h == hour]

    def slots_for_class_day_hour(self, class_name: str, day: int,
                                  hour: int) -> list:
        return [v for (_t, cl, _s, d, h), v in self.slot.items()
                if cl == class_name and d == day and h == hour]

    # ============================================================
    # HARD constraint methods
    # ============================================================

    def add_teacher_no_overlap(self):
        """At most one slot per (teacher, day, hour)."""
        teachers = self.teachers_in_scope()
        for t in teachers:
            for d in self.days:
                for h in self.hours:
                    vs = self.slots_for_teacher_day_hour(t, d, h)
                    if len(vs) > 1:
                        self.model.Add(sum(vs) <= 1)

    def _classes_with_busy_aggregation(self) -> set[str]:
        """Real + home classes that should run busy aggregation.

        Excludes virtual group classes (``_group_triples`` keys: the
        group's ``group_name`` is its virtual class, with no curriculum
        no_holes / h11 / no_overlap obligation -- those rules apply to
        the home classes the group serves).
        """
        group_triples = getattr(self, "_group_triples", {})
        virtual = {gn for (_gp, gn, _gs) in group_triples}
        classes = set(c for c in self.classes_in_scope()
                      if c not in virtual)
        for (_gp, _gn, _gs), homes in group_triples.items():
            classes.update(homes)
        return classes

    def _build_class_busy_indicators(self, cl: str, d: int, h: int,
                                       *, name_suffix: str = "") -> list:
        """Return the list of class-busy indicators at ``(cl, d, h)``
        using the same bucket-by-busy-key + aggregation rules as
        ``add_class_no_overlap``. Used by ``add_class_no_overlap``,
        ``add_class_no_holes``, ``add_h3_presence_at_11`` and the
        equivalent DSL pragmas so all four enforce the same notion of
        "the class is busy at this slot".

        Aggregation rules (mirror the legacy ``solve_phase_b_for_day``
        ``keys_by_busy`` logic):

        * Coteach groups registered via ``add_coteach_groups`` are
          aggregated per (cl, subj) into a single class-busy indicator
          so the k members of a compresenza count as ONE class
          occupation.
        * Parallel groups (intra-class) registered via
          ``add_parallel_groups_intra_class`` are aggregated per group
          (different subjects, same slot): the k member slot vars are
          OR'd into a single indicator and count as ONE class
          occupation.
        * Sostegno (DVA) triples registered via
          ``add_support_assignments`` are excluded from the
          aggregation: the support slot shadows a non-support lesson
          and must not add a fresh class occupation.
        * Inter-class groups registered via
          ``add_parallel_groups_inter_class`` append the group's slot
          to each home class's busy aggregation under a
          ``__grp__<gn>__<subj>`` busy key.

        ``name_suffix`` is appended to the aggregator BoolVar names so
        callers from different methods don't share names (CP-SAT
        accepts duplicates but distinct names ease debugging).
        """
        coteach_busy_keys = getattr(self, "_coteach_busy_keys", set())
        support_triples = getattr(self, "_support_triples", set())
        parallel_busy_key = getattr(
            self, "_parallel_intra_busy_key", {})
        group_triples = getattr(self, "_group_triples", {})
        by_bk: dict[str, tuple[set[str], list]] = {}
        for k, v in self.slot.items():
            t, ccl, s, dd, hh = k
            if ccl != cl or dd != d or hh != h:
                continue
            if (t, ccl, s) in support_triples:
                continue
            if (t, ccl, s) in group_triples:
                # Group's virtual-class slot; aggregated under each
                # home class via the group_triples loop below.
                continue
            bk = parallel_busy_key.get((cl, s), s)
            if bk not in by_bk:
                by_bk[bk] = (set(), [])
            by_bk[bk][0].add(s)
            by_bk[bk][1].append(v)
        for (gp, gn, gs), homes in group_triples.items():
            if cl not in homes:
                continue
            if (gp, gn, gs) in support_triples:
                continue
            gv = self.slot.get((gp, gn, gs, d, h))
            if gv is None:
                continue
            gbk = f"__grp__{gn}__{gs}"
            if gbk not in by_bk:
                by_bk[gbk] = (set(), [])
            by_bk[gbk][1].append(gv)
        busy_indicators = []
        for bk, (subs, vs) in by_bk.items():
            if len(vs) <= 1:
                busy_indicators.extend(vs)
                continue
            is_aggregated = bk not in subs
            is_coteach = any(
                (cl, s) in coteach_busy_keys for s in subs)
            if is_aggregated or is_coteach:
                tag = f"_{name_suffix}" if name_suffix else ""
                ind = self.model.NewBoolVar(
                    f"agg{tag}_{cl}_{bk}_{d}_{h}")
                self.model.AddMaxEquality(ind, vs)
                busy_indicators.append(ind)
            else:
                busy_indicators.extend(vs)
        return busy_indicators

    def add_class_no_overlap(self):
        """At most one slot per (class, day, hour).

        Aggregation rules: see ``_build_class_busy_indicators``. The
        registries (``_coteach_busy_keys`` / ``_support_triples`` /
        ``_parallel_intra_busy_key`` / ``_group_triples``) start empty
        on a freshly-built model, and with all empty this method
        behaves exactly like the original ``sum(vs) <= 1`` formulation.
        """
        for cl in self._classes_with_busy_aggregation():
            for d in self.days:
                for h in self.hours:
                    busy = self._build_class_busy_indicators(
                        cl, d, h, name_suffix="nco")
                    if len(busy) > 1:
                        self.model.Add(sum(busy) <= 1)

    def add_coteach_groups(self, groups: list | None = None):
        """Co-teaching (compresenza) HARD constraint.

        For each group ``g = {group_id, class_name, subject, n_hours,
        teachers, required}`` create per-(day, hour) ``coslot`` BoolVars
        and force every active member's ``slot[(T, cl, subj, d, h)]``
        to equal ``coslot[g, d, h]``. The weekly total of ``coslot``
        equals ``n_hours`` so each member's count is exactly
        ``n_hours`` and the k members are co-active on the same slots.

        The pair ``(class_name, subject)`` is registered in
        ``self._coteach_busy_keys`` so the next
        ``add_class_no_overlap`` call aggregates the k member slots
        into a single class-busy indicator (as the legacy Phase B does
        via the ``coteach_members_by_cl_subj`` map).

        When ``groups`` is None, ``self.config.coteach_groups`` is
        used. SOFT groups (``required=False``) are skipped here; SOFT
        coteach belongs to the objective layer (TODO).
        """
        if groups is None:
            groups = list(self.config.coteach_groups or [])
        if not groups:
            return
        if not hasattr(self, "_coteach_busy_keys"):
            self._coteach_busy_keys: set[tuple[str, str]] = set()
        for g in groups:
            if not g.get("required"):
                continue
            gid = g["group_id"]
            gcl = g["class_name"]
            gsub = g["subject"]
            n_hours = int(g["n_hours"])
            teachers = list(g["teachers"])
            usable = [
                t for t in teachers
                if any((t, gcl, gsub, d, h) in self.slot
                       for d in self.days for h in self.hours)
            ]
            if len(usable) < 2:
                continue
            self._coteach_busy_keys.add((gcl, gsub))
            coslot: dict[tuple[int, int], Any] = {}
            for d in self.days:
                for h in self.hours:
                    cv = self.model.NewBoolVar(
                        f"co_{gid}_{d}_{h}")
                    coslot[(d, h)] = cv
                    for t in usable:
                        v = self.slot.get((t, gcl, gsub, d, h))
                        if v is None:
                            self.model.Add(cv == 0)
                        else:
                            self.model.Add(v == cv)
            self.model.Add(
                sum(coslot[(d, h)]
                    for d in self.days for h in self.hours)
                == n_hours
            )

    def add_support_assignments(self, assignments: list | None = None):
        """Sostegno (DVA support) HARD shadow constraint.

        For each ``support_assignment`` ``{teacher_name, class_name,
        subject, n_hours}`` the support teacher is in the class only
        when a non-support lesson is also in the class at the same
        (day, hour): ``slot[(t_sost, cl, subj_sost, d, h)]`` <= OR over
        non-support slots ``slot[(t, cl, *, d, h)]``. The (t, cl, subj)
        triple is registered in ``self._support_triples`` so the next
        ``add_class_no_overlap`` call EXCLUDES it from the per-(cl, d,
        h) busy aggregation: the support shadows the existing lesson,
        it does not add a fresh class occupation. Mirrors the legacy
        ``solve_phase_b_for_day`` shadow logic on
        ``support_triples_set``.

        ``is_group_target=True`` assignments (sostegno targeting an
        interclass StudyGroup) are skipped here -- they belong with
        Pattern 4 (``add_parallel_groups_inter_class``) since the
        shadow target is a group slot, not a class slot.
        """
        if assignments is None:
            assignments = list(self.config.support_assignments or [])
        if not assignments:
            return
        if not hasattr(self, "_support_triples"):
            self._support_triples: set[tuple[str, str, str]] = set()
        # Register every triple first so the OR-of-non-support check
        # below filters out ALL support entries even when multiple
        # support assignments share a class.
        for sa in assignments:
            if sa.get("is_group_target"):
                continue
            self._support_triples.add(
                (sa["teacher_name"], sa["class_name"], sa["subject"]))
        for sa in assignments:
            if sa.get("is_group_target"):
                continue
            sp = sa["teacher_name"]
            sc = sa["class_name"]
            ss = sa["subject"]
            for d in self.days:
                for h in self.hours:
                    sk = self.slot.get((sp, sc, ss, d, h))
                    if sk is None:
                        continue
                    non_support_vars = [
                        v for k, v in self.slot.items()
                        if k[1] == sc and k[3] == d and k[4] == h
                        and (k[0], k[1], k[2]) not in
                        self._support_triples
                    ]
                    if not non_support_vars:
                        self.model.Add(sk == 0)
                    elif len(non_support_vars) == 1:
                        self.model.Add(sk <= non_support_vars[0])
                    else:
                        cb = self.model.NewBoolVar(
                            f"clbusy_{sc}_{d}_{h}")
                        self.model.AddMaxEquality(cb, non_support_vars)
                        self.model.Add(sk <= cb)

    def add_potenziamento_assignments(
        self, assignments: list | None = None,
    ):
        """Potenziamento (cattedra senza classe) HARD constraint.

        For each ``pot_assignment`` ``{teacher_name, n_hours}`` create
        per-(day, hour) ``pot_slot[(t, d, h)]`` BoolVars whose weekly
        sum equals ``n_hours``. Multiple pot rows on the same teacher
        accumulate (the legacy Phase A does the same via
        ``pot_by_prof[teacher_name] += n_hours``).

        Mutual exclusion with the teacher's regular cattedra:
        ``pot_slot[(t, d, h)] + sum slot[(t, *, *, d, h)] <= 1`` per
        (t, d, h). The teacher cannot be in class AND in potenziamento
        at the same slot. ``add_teacher_no_overlap`` already covers
        ``sum slot <= 1`` for the regular side; the constraint above
        is what binds pot to the same calendar.

        The pot_slot vars are exposed on ``self.pot_slot`` so callers
        (and ``MonolithicSolver.solve``) can read them after solve.
        They produce no Lesson rows -- a potenziamento prof has no
        class to teach, the slot just blocks the teacher's calendar
        for the school's other purposes (e.g. exam prep, project
        hours, mandated free-time-with-students).
        """
        if assignments is None:
            assignments = list(
                self.config.potenziamento_assignments or [])
        if not assignments:
            return
        if not hasattr(self, "pot_slot"):
            self.pot_slot: dict[tuple[str, int, int], Any] = {}
        # Aggregate n_hours by teacher (multiple pot rows per teacher
        # merge into one weekly demand, matching the legacy logic).
        pot_by_teacher: dict[str, int] = {}
        for pa in assignments:
            t = pa["teacher_name"]
            if not self._scope_includes_teacher(t):
                continue
            pot_by_teacher[t] = (
                pot_by_teacher.get(t, 0) + int(pa["n_hours"]))
        for t, n_hours in pot_by_teacher.items():
            if n_hours <= 0:
                continue
            for d in self.days:
                for h in self.hours:
                    pv = self.model.NewBoolVar(f"pot_{t}_{d}_{h}")
                    self.pot_slot[(t, d, h)] = pv
            self.model.Add(
                sum(self.pot_slot[(t, d, h)]
                    for d in self.days for h in self.hours)
                == n_hours
            )
            for d in self.days:
                for h in self.hours:
                    regular_vars = self.slots_for_teacher_day_hour(
                        t, d, h)
                    pot_var = self.pot_slot[(t, d, h)]
                    if regular_vars:
                        self.model.Add(
                            pot_var + sum(regular_vars) <= 1)

    def add_parallel_groups_intra_class(
        self, groups: list | None = None,
    ):
        """Parallel groups (intra-class) HARD constraint.

        For each ``parallel_group`` ``{group_id, class_name, members}``
        with ``members`` a list of ``{teacher_name, subject}`` dicts,
        tie every (d, h) slot var of every member: they are all equal,
        so the k Assignments march together in their actual slot. The
        canonical use-case is religione/alternativa in the same class:
        two distinct subjects, same hour, students choose one or the
        other.

        Each member's ``(class_name, subject)`` is registered in
        ``self._parallel_intra_busy_key`` mapping to a stable group key
        ``__par__<gid>`` so the next ``add_class_no_overlap`` call
        aggregates the k member slot vars under a single class-busy
        indicator: they count as ONE class occupation per (cl, d, h),
        not k. Mirrors the legacy ``parallel_subj_to_busy_key`` map
        used by ``solve_phase_b_for_day``.

        Groups with fewer than 2 members are skipped (no parallelism
        to enforce).
        """
        if groups is None:
            groups = list(self.config.parallel_groups or [])
        if not groups:
            return
        if not hasattr(self, "_parallel_intra_busy_key"):
            self._parallel_intra_busy_key: dict[
                tuple[str, str], str] = {}
        for pg in groups:
            cl_name = pg["class_name"]
            members = pg.get("members", [])
            if len(members) < 2:
                continue
            gid = pg.get("group_id", id(pg))
            bkey = f"__par__{gid}"
            for m in members:
                self._parallel_intra_busy_key[
                    (cl_name, m["subject"])] = bkey
            m_keys = [(m["teacher_name"], cl_name, m["subject"])
                      for m in members]
            for d in self.days:
                for h in self.hours:
                    usable = [k for k in m_keys
                              if (k[0], k[1], k[2], d, h)
                              in self.slot]
                    if len(usable) < 2:
                        continue
                    ref = self.slot[
                        (usable[0][0], usable[0][1],
                         usable[0][2], d, h)]
                    for k in usable[1:]:
                        self.model.Add(
                            self.slot[(k[0], k[1], k[2], d, h)]
                            == ref)

    def add_parallel_groups_inter_class(
        self, assignments: list | None = None,
    ):
        """Parallel groups (inter-class / StudyGroup) HARD constraint.

        Each ``group_assignment`` ``{teacher_name, group_id,
        group_name, subject, n_hours, home_class_names}`` represents
        an interclass group: students from multiple home classes
        (e.g. 2A+2B for a second-language Spagnolo group) attend a
        shared lesson with one teacher. The group occupies the same
        slot for all home classes simultaneously -- whenever the
        group meets at (d, h), NONE of the home classes can hold a
        regular lesson at the same (d, h).

        Implementation:

        1. Slot vars are created at ``slot[(prof_g, group_name,
           subject, d, h)]`` (the group_name acts as a virtual class).
           If they already exist (e.g. group registered in
           ``profs[t]["classi"]`` and ``dc_value`` carries the
           per-day count via the standard cattedra path), this
           method only registers the home-class metadata; otherwise
           the vars are created here with weekly sum equal to
           ``n_hours``.

        2. ``(teacher_name, group_name, subject)`` is registered in
           ``self._group_triples`` -> list of home classes, so the
           next ``add_class_no_overlap`` call appends the group's
           slot var to each home class's busy aggregation under a
           ``__grp__<gn>__<subj>`` key. The home class is busy
           whenever the group meets, mirroring the legacy
           ``solve_phase_b_for_day`` ``__grp__`` busy-key extension.

        Note: ``add_class_no_holes`` does not (yet) propagate the
        group's busy state to the home class's per-hour presence,
        so users running with ``enforce_no_holes=True`` and an
        interclass group must be aware that holes around the group
        hour may not be detected. Tests for this method disable
        no_holes; full integration is a follow-up.
        """
        if assignments is None:
            assignments = list(self.config.group_assignments or [])
        if not assignments:
            return
        if not hasattr(self, "_group_triples"):
            self._group_triples: dict[
                tuple[str, str, str], list[str]] = {}
        for ga in assignments:
            gp = ga["teacher_name"]
            gn = ga["group_name"]
            gs = ga["subject"]
            n_hours = int(ga["n_hours"])
            home_classes = list(ga.get("home_class_names", []))
            gkey = (gp, gn, gs)
            self._group_triples[gkey] = home_classes
            if not self._scope_includes_teacher(gp):
                continue
            already_present = any(
                (gp, gn, gs, d, h) in self.slot
                for d in self.days for h in self.hours)
            if already_present:
                continue
            wk_vars = []
            for d in self.days:
                for h in self.hours:
                    if not self._scope_includes_slot(gp, gn, gs, d):
                        continue
                    v = self.model.NewBoolVar(
                        f"grp_{gp}_{gn}_{gs}_{d}_{h}")
                    self.slot[(gp, gn, gs, d, h)] = v
                    wk_vars.append(v)
            if wk_vars:
                self.model.Add(sum(wk_vars) == n_hours)

    def add_locks(self, locks: list | None = None):
        """Force ``slot[(t, cl, s, d, h)] == 1`` for every supplied
        lock (5-tuple). Locks pointing at slots not in the model are
        silently skipped (the caller is expected to keep the lock set
        consistent with the scope)."""
        if locks is None:
            locks = self.config.locks
        for entry in (locks or []):
            if len(entry) != 5:
                continue
            t, cl, s, d, h = entry
            v = self.slot.get((t, cl, s, int(d), int(h)))
            if v is not None:
                self.model.Add(v == 1)

    def add_class_no_holes(self):
        """For each (class, day) in scope, the busy slots must be
        contiguous starting at the earliest hour. Implemented via the
        non-increasing ``present[h+1] <= present[h]`` chain on the
        per-hour OR of class-busy indicators.

        The per-hour ``present[h]`` indicator is built via
        ``_build_class_busy_indicators`` so it shares the SAME
        exclusion + aggregation logic as ``add_class_no_overlap``:
        sostegno triples are excluded, coteach members are OR'd into a
        single indicator, parallel intra-class members are OR'd, and
        inter-class groups appear in their home classes' aggregation.
        Without this alignment a sostegno hour would falsely "fill"
        the no-holes chain and a parallel-intra group would be
        double-counted.

        Virtual group classes (registered via
        ``add_parallel_groups_inter_class``) are skipped: the legacy
        Phase B excludes them from ``cls_with_direct_triples`` for the
        same reason -- a group is not subject to the curriculum
        no-holes / 4-hours-min logic.
        """
        virtual = {gn for (_gp, gn, _gs)
                    in getattr(self, "_group_triples", {})}
        classes = [c for c in self.classes_in_scope()
                    if c not in virtual]
        for cl in classes:
            for d in self.days:
                present_per_h = []
                for h in self.hours:
                    busy = self._build_class_busy_indicators(
                        cl, d, h, name_suffix="nh")
                    if not busy:
                        present_per_h.append(self.model.NewConstant(0))
                        continue
                    if len(busy) == 1:
                        # Single indicator already represents the
                        # class-busy state at h; no extra OR needed.
                        present_per_h.append(busy[0])
                        continue
                    pr = self.model.NewBoolVar(f"pr_{cl}_{d}_{h}")
                    self.model.AddMaxEquality(pr, busy)
                    present_per_h.append(pr)
                # Class starts at the earliest hour if any are busy:
                # ap = OR(present); present[0] >= ap.
                ap = self.model.NewBoolVar(f"ap_{cl}_{d}")
                self.model.AddMaxEquality(ap, present_per_h)
                self.model.Add(present_per_h[0] >= ap)
                # Non-increasing: present[i+1] <= present[i].
                for i in range(len(present_per_h) - 1):
                    self.model.Add(
                        present_per_h[i + 1] <= present_per_h[i])

    def add_h3_presence_at_11(self):
        """If the class has any lessons that day, h=11 must be
        occupied. Phase B currently enforces this whenever the class
        is in ``cls_with_direct_triples``; the OO version applies it
        to every class in scope. Virtual group classes (registered
        via ``add_parallel_groups_inter_class``) are skipped --
        groups have no curriculum h=11 obligation.

        Both ``any_d`` (any lesson today) and ``pr11`` (lesson at
        h=11) are built from ``_build_class_busy_indicators`` so they
        apply the same exclusion + aggregation as
        ``add_class_no_overlap`` / ``add_class_no_holes``: sostegno
        is excluded, coteach/parallel intra members are OR'd into one
        indicator each, inter-class groups feed their home classes.
        """
        if 11 not in self.hours:
            return
        virtual = {gn for (_gp, gn, _gs)
                    in getattr(self, "_group_triples", {})}
        classes = [c for c in self.classes_in_scope()
                    if c not in virtual]
        for cl in classes:
            for d in self.days:
                # Build the per-hour busy indicators ONCE per (cl, d):
                # ``pr11`` reads the h=11 bucket and ``any_d`` reads
                # the union across all hours. Calling the helper
                # twice would create two parallel families of
                # aggregator BoolVars (wasteful, harmless).
                busy_per_h: dict[int, list] = {}
                for h in self.hours:
                    busy_per_h[h] = (
                        self._build_class_busy_indicators(
                            cl, d, h, name_suffix="h11"))
                bvs_11 = busy_per_h.get(11, [])
                if not bvs_11:
                    continue
                all_busy = [v for h in self.hours for v in busy_per_h[h]]
                if not all_busy:
                    continue
                any_d = self.model.NewBoolVar(f"ap11_{cl}_{d}")
                self.model.AddMaxEquality(any_d, all_busy)
                pr11 = self.model.NewBoolVar(f"pr11_{cl}_{d}")
                self.model.AddMaxEquality(pr11, bvs_11)
                self.model.Add(pr11 >= any_d)

    # ============================================================
    # SOFT cost expression
    # ============================================================

    def compute_soft_cost_expr(self) -> tuple[list, list]:
        """Return ``(obj_terms, aux_vars)`` -- a list of CP-SAT
        objective contributions and the auxiliary BoolVars/IntVars
        introduced. The four canonical components (sixth, buchi,
        five, one) are added per (teacher, day) using reified
        BoolVars that mirror ``meta.compute_soft``.

        ``self.fixed_load`` (set by sub-classes when greedy-base
        slots are out of CP-SAT scope) contributes a constant to the
        per-(teacher, day) hour count.
        """
        obj_terms: list = []
        aux_vars: list = []
        if not self.hours:
            return obj_terms, aux_vars
        h_min, h_max = min(self.hours), max(self.hours)
        # Sixth-hour penalty: per-slot at h=13 (matches
        # _cost_of_pattern's per-slot accounting).
        for (t, cl, s, d, h), v in self.slot.items():
            if h == SIXTH_HOUR:
                obj_terms.append(PENALTY_SIXTH * v)
        teachers = self.teachers_in_scope()
        for t in teachers:
            for d in self.days:
                cpsat_at_h: dict = {}
                base_at_h: dict = {}
                for h in self.hours:
                    cpsat_at_h[h] = self.slots_for_teacher_day_hour(
                        t, d, h)
                    base_at_h[h] = int(self.fixed_load.get(
                        (t, d, h), 0))
                base_count = sum(base_at_h.values())
                cpsat_all = [v for h in self.hours
                              for v in cpsat_at_h[h]]
                if not cpsat_all and base_count == 0:
                    continue
                # any_at_h indicators
                any_at_h: dict = {}
                for h in self.hours:
                    if base_at_h[h] >= 1:
                        any_at_h[h] = self.model.NewConstant(1)
                    elif not cpsat_at_h[h]:
                        any_at_h[h] = self.model.NewConstant(0)
                    else:
                        b = self.model.NewBoolVar(
                            f"any_{t}_{d}_{h}")
                        for v in cpsat_at_h[h]:
                            self.model.Add(b >= v)
                        self.model.Add(b <= sum(cpsat_at_h[h]))
                        aux_vars.append(b)
                        any_at_h[h] = b
                # day_count
                count_d = self.model.NewIntVar(
                    base_count, base_count + len(cpsat_all),
                    f"cnt_{t}_{d}")
                aux_vars.append(count_d)
                if cpsat_all:
                    self.model.Add(
                        count_d == base_count + sum(cpsat_all))
                else:
                    self.model.Add(count_d == base_count)
                # first_h, last_h via min/max over auxiliaries
                first_h = self.model.NewIntVar(
                    h_min, h_max + 1, f"fh_{t}_{d}")
                last_h = self.model.NewIntVar(
                    h_min - 1, h_max, f"lh_{t}_{d}")
                aux_vars.extend([first_h, last_h])
                hf_aux: list = []
                hl_aux: list = []
                for h in self.hours:
                    hf = self.model.NewIntVar(
                        h_min, h_max + 1, f"hf_{t}_{d}_{h}")
                    hl = self.model.NewIntVar(
                        h_min - 1, h_max, f"hl_{t}_{d}_{h}")
                    self.model.Add(hf == h).OnlyEnforceIf(any_at_h[h])
                    self.model.Add(hf == h_max + 1).OnlyEnforceIf(
                        any_at_h[h].Not())
                    self.model.Add(hl == h).OnlyEnforceIf(any_at_h[h])
                    self.model.Add(hl == h_min - 1).OnlyEnforceIf(
                        any_at_h[h].Not())
                    hf_aux.append(hf)
                    hl_aux.append(hl)
                self.model.AddMinEquality(first_h, hf_aux)
                self.model.AddMaxEquality(last_h, hl_aux)
                # buchi
                max_buchi = h_max - h_min
                buchi = self.model.NewIntVar(
                    0, max_buchi, f"bch_{t}_{d}")
                aux_vars.append(buchi)
                self.model.Add(buchi >= last_h - first_h + 1 - count_d)
                # is_five, is_one reified
                is_five = self.model.NewBoolVar(f"5_{t}_{d}")
                self.model.Add(count_d == 5).OnlyEnforceIf(is_five)
                self.model.Add(count_d != 5).OnlyEnforceIf(
                    is_five.Not())
                is_one = self.model.NewBoolVar(f"1_{t}_{d}")
                self.model.Add(count_d == 1).OnlyEnforceIf(is_one)
                self.model.Add(count_d != 1).OnlyEnforceIf(
                    is_one.Not())
                aux_vars.extend([is_five, is_one])
                obj_terms.append(PENALTY_FIVE * is_five)
                obj_terms.append(PENALTY_ONE * is_one)
                obj_terms.append(PENALTY_BUCHI * buchi)
        return obj_terms, aux_vars

    def add_subject_pair_constraint(
        self, subject_name: str, *, mode: str,
    ):
        """Add a "consecutive pair" constraint on a specific subject.

        ``mode == "must_pair"``: when the (teacher, class, subject)
            has exactly 2 hours that day, they MUST be consecutive
            (used for Scienzemotorie -- always paired).
        ``mode == "pair_exists"``: when the (teacher, class, subject)
            has >= 2 hours that day, at least one consecutive pair
            of busy hours must exist (used for Matematica/Italiano
            -- doppia consecutiva).

        Day-counts are read from ``self.dc_value`` so the constraint
        only fires when the cattedra-day demand triggers it.
        """
        if not self.hours:
            return
        # For each (teacher, class, day) where teacher teaches the
        # named subject, compute the per-hour presence and require
        # the appropriate pair pattern.
        for teacher, pdata in self.profs.items():
            if not self._scope_includes_teacher(teacher):
                continue
            classi = pdata.get("classi", {}) or {}
            for class_name, subjs in classi.items():
                # Subject may be expressed as exact match or sub-string
                # (legacy code uses "Matematica", "Italiano",
                # "Scienzemotorie"). Match the canonical form.
                if subject_name not in subjs:
                    continue
                for d in self.days:
                    presence = []
                    keys_for_day = []
                    for h in self.hours:
                        keys_for_day.append(
                            (teacher, class_name, subject_name, d, h))
                    vs = [self.slot.get(k) for k in keys_for_day]
                    vs = [v for v in vs if v is not None]
                    if len(vs) != len(self.hours):
                        # subject not in scope on this day
                        continue
                    day_total = int(self.dc_value.get(
                        (teacher, class_name, subject_name, d), 0))
                    if mode == "must_pair" and day_total != 2:
                        continue
                    if mode == "pair_exists" and day_total < 2:
                        continue
                    # presence[h] is just slot[(t, cl, subj, d, h)]
                    # since each hour has exactly one slot var per
                    # cattedra.
                    presence = vs
                    pairs = []
                    for i in range(len(self.hours) - 1):
                        pair = self.model.NewBoolVar(
                            f"pair_{subject_name[:3]}_"
                            f"{teacher}_{class_name}_{d}_{i}")
                        self.model.AddBoolAnd(
                            [presence[i], presence[i + 1]]
                        ).OnlyEnforceIf(pair)
                        self.model.AddBoolOr(
                            [presence[i].Not(),
                             presence[i + 1].Not()]
                        ).OnlyEnforceIf(pair.Not())
                        pairs.append(pair)
                    if pairs:
                        self.model.AddBoolOr(pairs)

    def add_motorie_pair(self):
        """Scienzemotorie: 2 hours/day MUST be consecutive."""
        self.add_subject_pair_constraint(
            "Scienzemotorie", mode="must_pair")

    def add_math_italian_pair(self):
        """Matematica + Italiano: when >= 2 hours/day, at least one
        consecutive pair of busy hours."""
        self.add_subject_pair_constraint(
            "Matematica", mode="pair_exists")
        self.add_subject_pair_constraint(
            "Italiano", mode="pair_exists")

    def add_plessi_commuting_constraints(self):
        """Apply plessi commuting rules (teacher- and class-kind) to
        the slot variables. Defers to the dedicated helper module
        since the lookup logic + rule resolution already lives
        there."""
        plessi = self.config.plessi_data
        if plessi is None:
            return
        try:
            from . import plessi_constraints as pc  # type: ignore
        except ImportError:
            import plessi_constraints as pc  # type: ignore
        # Build cpsat_vars_by_t_d_h indexed by (teacher, day, hour).
        # The slots in this model are 5-tuple keyed; the helper
        # operates on column-pair selection so it doesn't fit
        # 1-to-1 with classroom assignment scope. For now we expose
        # the room-less version: add commuting rules at the
        # (teacher, day, hour) granularity using slot var presence.
        # The full constraint requires room knowledge -- left to
        # the classroom-assignment caller. This stub keeps the API
        # consistent so subclasses can opt-in safely.
        return

    # ============================================================
    # Generic DSL constraint integration
    # ============================================================

    def add_dsl_constraint(self, expression, *,
                            classroom_for_slot: dict | None = None,
                            plessi_data: Any = None):
        """Compile a single DSL expression (string or AST) and add
        the resulting CP-SAT constraints to ``self.model``.

        Routes through ``engine.dsl_to_cpsat.DSLConstraintCompiler``.
        Diagnostics from the compiler (skipped/unsupported nodes)
        are collected on ``self.dsl_diagnostics`` so the caller can
        log/inspect them; HARD rules with dynamic constructs the
        compiler can't yet emit are reported there rather than
        silently ignored.

        ``classroom_for_slot`` and ``plessi_data`` are forwarded to
        the compiler; when omitted, the model defaults
        (``self.classroom_for_slot`` / ``self.config.plessi_data``)
        are used. They unlock DSL rules that reference
        ``l.classroom`` / ``l.classroom.plesso``.
        """
        try:
            from . import dsl_to_cpsat as d2c  # type: ignore
        except ImportError:
            import dsl_to_cpsat as d2c  # type: ignore
        if not hasattr(self, "dsl_diagnostics"):
            self.dsl_diagnostics: list[str] = []
        cfs = classroom_for_slot
        if cfs is None:
            cfs = getattr(self, "classroom_for_slot", None)
        plessi = plessi_data
        if plessi is None:
            plessi = getattr(self.config, "plessi_data", None)
        compiler = d2c.DSLConstraintCompiler(
            self.model, self.slot, config=self.config,
            classroom_for_slot=cfs,
            plessi_data=plessi,
            # ``owner_model=self`` lets the no_holes / h11 pragmas
            # share ``_build_class_busy_indicators`` -- the same
            # exclusion + aggregation logic backing
            # ``add_class_no_overlap`` -- so rules compiled via the
            # DSL match the OO methods byte-for-byte even when
            # sostegno / coteach / parallel intra are registered.
            owner_model=self,
        )
        compiler.compile(expression)
        self.dsl_diagnostics.extend(compiler.diagnostics)

    def add_all_dsl_constraints(self, expressions: list, *,
                                  classroom_for_slot: dict | None = None,
                                  plessi_data: Any = None):
        """Convenience: compile every expression in the list. Useful
        when the caller has loaded a batch of LogicalUnavailability
        rows and wants to push them all into the model."""
        for expr in expressions or []:
            self.add_dsl_constraint(
                expr,
                classroom_for_slot=classroom_for_slot,
                plessi_data=plessi_data,
            )

    def add_all_dsl_constraints_from_db(self, db, *,
                                          include_soft: bool = False):
        """Aggregate every constraint table (TeacherUnavailability,
        ClassUnavailability, ClassroomUnavailability,
        TeacherMandatoryFreeDay, CoteachGroup, LogicalUnavailability,
        CurriculumLogicalConstraint, ...) into a single DSL stream
        and compile every entry onto the model.

        Single source of truth for all HARD constraints across mono
        solver, every BP pricer, Ryan-Foster nodes, metaheuristics
        repair operators, and classroom assignment. The legacy
        special-purpose tables are no longer queried directly by
        each solver -- they are translated by ``dsl_translator``
        and consumed uniformly here.
        """
        try:
            from . import dsl_translator as dt  # type: ignore
        except ImportError:
            import dsl_translator as dt  # type: ignore
        rules = dt.load_all_dsl_constraints(
            db, include_soft=include_soft)
        for r in rules:
            self.add_dsl_constraint(r["expression"])
        if not hasattr(self, "dsl_diagnostics"):
            self.dsl_diagnostics: list[str] = []
        self.dsl_diagnostics.append(
            f"loaded {len(rules)} DSL rules from DB "
            f"(include_soft={include_soft})")

    def add_all_hard_constraints(self, *, via_dsl: bool = False):
        """Apply every HARD constraint enabled by ``self.config``.

        Sub-classes can override to skip constraints that don't apply
        to their scope (e.g. the per-teacher pricer can skip
        ``add_class_no_overlap`` since it only sees one teacher's
        slots and intra-teacher class overlap is already covered by
        ``add_teacher_no_overlap``).

        ``via_dsl``: when True, route the canonical HARD families
        (no-holes, h11 presence, motorie pair, mat/ita pair) through
        ``dsl_translator.seed_implicit_hardcoded`` + the DSL
        compiler instead of the direct ``add_*`` method calls.
        Step 3e of the DSL unification plan: the seed pragmas
        produce the same CP-SAT encoding as the methods (proven
        zero-drift in test_dsl_seed_legacy.py), so this is purely a
        pipeline switch with no behavioural change."""
        self.add_teacher_no_overlap()
        if self.config.locks:
            self.add_locks()
        if via_dsl:
            try:
                from . import dsl_translator as dt  # type: ignore
            except ImportError:
                import dsl_translator as dt  # type: ignore
            seeds = dt.seed_implicit_hardcoded(
                self.profs,
                classes=self.classes_in_scope(),
                enforce_no_holes=self.config.enforce_no_holes,
                enforce_h3_presence=(
                    self.config.enforce_no_holes
                    and self.config.enforce_h3_presence_at_11),
                enforce_motorie_pair=self.config.enforce_motorie_pair,
                enforce_math_italian_pair=(
                    self.config.enforce_math_italian_pair),
                # The cattedra_max + teacher_max + class_day_load
                # families are not part of the OO solver's HARD
                # surface yet -- the function-based legacy enforces
                # them via direct day_count / cl_day_load IntVars in
                # cpsat_v2_timetable. They are emitted by the seed
                # for completeness when the caller asks (e.g. in a
                # full Phase B port), but disabled by default here
                # to preserve the OO solver's existing surface.
                enforce_class_day_load=False,
                enforce_max_per_day_triple=False,
                enforce_max_prof_hours_per_day=False,
            )
            self.add_all_dsl_constraints(seeds)
        else:
            if self.config.enforce_no_holes:
                self.add_class_no_holes()
                if self.config.enforce_h3_presence_at_11:
                    self.add_h3_presence_at_11()
            if self.config.enforce_motorie_pair:
                self.add_motorie_pair()
            if self.config.enforce_math_italian_pair:
                self.add_math_italian_pair()
        if self.config.plessi_data is not None:
            self.add_plessi_commuting_constraints()


# ============================================================
# MonolithicSolver (Phase B-equivalent)
# ============================================================

class MonolithicSolver(ConstraintModel):
    """Class form of the monolithic Phase B solver.

    Builds a CP-SAT model with ALL HARD constraints + the canonical
    soft cost as objective. Provided as the forward-looking equivalent
    of ``cpsat_v2_timetable.solve_phase_b_for_day``; the existing
    function keeps running unchanged so its 100+ regression tests
    are not at risk. Migration of Phase B to this class is a follow-up
    commit.
    """

    def build(self, *, via_dsl: bool = False):
        # Create slot vars for inter-class groups first so subsequent
        # teacher_no_overlap / class_no_holes / class_no_overlap pick
        # the group teacher up. These slots key on group_name as a
        # virtual class; the per-class HARD methods skip virtual
        # group classes when iterating ``classes_in_scope()``.
        self.add_parallel_groups_inter_class()
        # Populate the busy-key registries (``_coteach_busy_keys`` /
        # ``_support_triples`` / ``_parallel_intra_busy_key``) BEFORE
        # ``add_all_hard_constraints`` so the no_holes + h11 methods
        # invoked there see the same exclusion + aggregation rules as
        # ``add_class_no_overlap``. Without this ordering, no_holes
        # would treat sostegno as a fresh class occupation and
        # double-count parallel-intra members.
        self.add_coteach_groups()
        self.add_support_assignments()
        self.add_potenziamento_assignments()
        self.add_parallel_groups_intra_class()
        self.add_all_hard_constraints(via_dsl=via_dsl)
        self.add_class_no_overlap()
        obj_terms, _ = self.compute_soft_cost_expr()
        if obj_terms:
            self.model.Minimize(sum(obj_terms))

    def solve(self, *, time_limit_s: float = 10.0,
              workers: int = 4, log: bool = False,
              via_dsl: bool = False):
        self.build(via_dsl=via_dsl)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(time_limit_s)
        solver.parameters.num_search_workers = int(workers)
        solver.parameters.log_search_progress = log
        status = solver.Solve(self.model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return None, solver.StatusName(status)
        out = {}
        for k, v in self.slot.items():
            if solver.Value(v):
                out[k] = 1
        self.pot_solution: dict[tuple[str, int, int], int] = {}
        for k, v in getattr(self, "pot_slot", {}).items():
            if solver.Value(v):
                self.pot_solution[k] = 1
        return out, solver.StatusName(status)


# ============================================================
# PhaseBDaySolver -- OO entry point for per-day Phase B
# ============================================================


class PhaseBDaySolver:
    """Object-oriented wrapper around ``cpsat_v2_timetable.solve_phase_b_for_day``.

    The Phase B per-day function carries 380 lines of carefully
    balanced HARD/SOFT logic (coteach groups, parallel groups, support
    shadow, group/home-class busy propagation, locks, no-holes,
    h11 presence, mat/ita/motorie pairs, sixth-hour and teacher gap
    objectives). Re-implementing every branch in a fresh OO model
    risks behavioural drift on the 100+ existing Phase B regression
    tests. ``PhaseBDaySolver`` therefore composes over the proven
    function: it exposes the OO interface (``solve()``, scope access,
    DSL augmentation via ``via_dsl=True``) while delegating model
    construction to the legacy code path. Zero-drift is preserved
    structurally because the byte-identical model is built every time
    the OO surface is invoked without DSL augmentation.

    When ``via_dsl=True`` is passed at solve time, the DSL pipeline
    activates as an *additional* constraint layer on top of the
    legacy model: rules sourced from the database and/or extra DSL
    expressions are compiled by ``DSLConstraintCompiler`` against the
    same CP-SAT model right before the solver runs. The legacy hard
    constraints stay intact; the DSL layer can only further restrict
    the feasible set, never relax it.

    Slot key convention
    -------------------
    The legacy function returns ``out[(prof, class, subject, day,
    hour)] -> 0/1``. ``PhaseBDaySolver.solve()`` preserves this exact
    output shape so existing callers of ``solve_phase_b_for_day`` can
    be ported with zero behavioural change.

    Future migration
    ----------------
    Once the OO catalogue (``MonolithicSolver`` + DSL seed pragmas)
    grows the missing constraint families (coteach coslot vars,
    parallel slot tying, support shadow, group home-class busy
    propagation, teacher gap penalty), this wrapper can be replaced
    with a direct subclass that builds the model from
    ``ConstraintModel`` primitives. Until then, composition is the
    safe migration path.
    """

    def __init__(
        self,
        profs: dict,
        dc_value: dict,
        day: int,
        *,
        classes: list | None = None,
        triples: list | None = None,
        class_profs: dict | None = None,
        config: ConstraintConfig | None = None,
        db: Any = None,
        extra_dsl_expressions: list | None = None,
    ):
        self.profs = profs
        self.dc_value = dc_value
        self.day = int(day)
        self.config = config or ConstraintConfig()
        self.db = db
        self.extra_dsl_expressions = list(extra_dsl_expressions or [])
        # Lazy-build the index only when callers don't provide one;
        # ``solve_phase_b_for_day`` happily re-derives ``classes`` /
        # ``triples`` / ``class_profs`` from ``profs`` if needed but
        # the public function expects them upfront.
        if classes is None or triples is None or class_profs is None:
            try:
                from . import cpsat_v2_timetable as _cv2  # type: ignore
            except ImportError:
                import cpsat_v2_timetable as _cv2  # type: ignore
            cl_built, tri_built, cp_built = _cv2.build_indices(profs)
            classes = classes or cl_built
            triples = triples or tri_built
            class_profs = class_profs or cp_built
        self.classes = classes
        self.triples = triples
        self.class_profs = class_profs
        # Diagnostics surface for callers that want to inspect what
        # the DSL augmentation actually emitted.
        self.dsl_diagnostics: list[str] = []
        # Last solve status string (set by ``solve()``).
        self.last_status: str | None = None

    # ------- compatibility properties -------

    @property
    def days(self) -> list[int]:
        return [self.day]

    @property
    def hours(self) -> list[int]:
        return list(HOURS)

    @property
    def scope(self) -> tuple:
        return ("day", self.day)

    def solve(
        self,
        *,
        time_limit_s: float = 10.0,
        workers: int = 4,
        log: bool = False,
        via_dsl: bool = False,
        enforce_no_holes: bool | None = None,
        locked_slots_for_day: list | None = None,
        coteach_groups: list | None = None,
        support_assignments: list | None = None,
        parallel_groups: list | None = None,
        group_assignments: list | None = None,
    ):
        """Build & solve the Phase-B-per-day CP-SAT model.

        ``via_dsl=True``: load DSL constraints from ``self.db`` and
        compile any ``extra_dsl_expressions`` provided at construction
        as an additional HARD layer. The legacy hardcoded path stays
        untouched (zero-drift on existing tests).
        """
        try:
            from . import cpsat_v2_timetable as _cv2  # type: ignore
        except ImportError:
            import cpsat_v2_timetable as _cv2  # type: ignore

        if enforce_no_holes is None:
            enforce_no_holes = bool(self.config.enforce_no_holes)
        if locked_slots_for_day is None:
            # Translate 5-tuple locks (config.locks) into 4-tuple form
            # expected by the legacy function -- only those matching
            # this day.
            locked_slots_for_day = [
                (t, cl, s, h)
                for (t, cl, s, d, h) in (self.config.locks or [])
                if int(d) == self.day
            ]
        if coteach_groups is None:
            coteach_groups = list(self.config.coteach_groups or [])
        if support_assignments is None:
            support_assignments = list(
                self.config.support_assignments or [])
        if parallel_groups is None:
            parallel_groups = list(self.config.parallel_groups or [])
        if group_assignments is None:
            group_assignments = list(self.config.group_assignments or [])

        out, status = _cv2.solve_phase_b_for_day(
            self.day, self.profs, self.classes, self.triples,
            self.class_profs, self.dc_value,
            time_limit=time_limit_s, workers=workers, log=log,
            enforce_no_holes=enforce_no_holes,
            locked_slots_for_day=locked_slots_for_day,
            coteach_groups=coteach_groups,
            support_assignments=support_assignments,
            parallel_groups=parallel_groups,
            group_assignments=group_assignments,
            db=self.db if via_dsl else None,
            via_dsl=via_dsl,
            extra_dsl_expressions=(
                self.extra_dsl_expressions if via_dsl else None),
        )
        # Normalise status: the legacy function returns the CP-SAT
        # numeric status when infeasible and a dict when feasible.
        # The OO wrapper uses the same convention as MonolithicSolver:
        # always return ``(sol_dict_or_None, status_name_str)``.
        if out is None:
            try:
                from ortools.sat.python import cp_model as _cp  # type: ignore
                solver = _cp.CpSolver()
                self.last_status = solver.StatusName(status)
            except Exception:  # noqa: BLE001
                self.last_status = str(status)
            return None, self.last_status
        # Drop zero-valued entries from the dict so the OO output
        # matches MonolithicSolver's ``{(t, cl, s, d, h): 1}`` shape.
        sol = {k: v for k, v in out.items() if v}
        self.last_status = "FEASIBLE_OR_OPTIMAL"
        return sol, self.last_status


# ============================================================
# PricerSolver + TeacherPricer (BP)
# ============================================================

class PricerSolver(ConstraintModel):
    """Base class for Branch-and-Price pricer sub-CP-SAT models.

    Adds a dual-driven objective term on top of the canonical soft
    cost and (for nodes inside the Ryan-Foster tree) any branching
    constraints propagated from the parent node.
    """

    def __init__(
        self,
        profs: dict,
        dc_value: dict,
        config: ConstraintConfig | None = None,
        *,
        scope: tuple,
        lambda_duals: dict | None = None,
        mu_t: float = 0.0,
        branching_constraints: list | None = None,
        days: Iterable[int] | None = None,
        hours: Iterable[int] | None = None,
    ):
        super().__init__(profs, dc_value, config=config,
                          scope=scope, days=days, hours=hours)
        self.lambda_duals = lambda_duals or {}
        self.mu_t = float(mu_t)
        self.branching_constraints = branching_constraints or []

    def compute_dual_bonus_terms(self) -> list:
        """Return the integer-scaled dual reward terms to subtract
        from the soft cost objective: ``-lam_int * v`` for every
        slot with a positive cover-dual on its (t, cl, s, d) key."""
        bonus_terms: list = []
        for (t, cl, s, d, h), v in self.slot.items():
            lam = float(self.lambda_duals.get((t, cl, s, d), 0.0))
            if lam == 0.0:
                continue
            lam_int = int(round(lam * SCALE))
            if lam_int != 0:
                bonus_terms.append(-lam_int * v)
        return bonus_terms

    def add_branching_constraints(self):
        """Subclasses / Ryan-Foster tree nodes can attach
        column-equal / column-apart constraints here. Default no-op.
        """
        for _ in self.branching_constraints:
            # Format and semantics defined in commit 3 (RF tree).
            pass

    def build(self, *, via_dsl: bool = False):
        self.add_all_hard_constraints(via_dsl=via_dsl)
        self.add_branching_constraints()
        soft_terms, _ = self.compute_soft_cost_expr()
        bonus_terms = self.compute_dual_bonus_terms()
        all_terms = list(soft_terms) + list(bonus_terms)
        if all_terms:
            self.model.Minimize(sum(all_terms))

    def add_warm_start_hint(self, hint_pattern: dict):
        """Greedy warm-start: for each (t, cl, s, d, h) in scope, set
        the AddHint to 1 if the hint pattern places a slot there,
        else 0."""
        for k, v in self.slot.items():
            self.model.AddHint(v, 1 if hint_pattern.get(k) else 0)

    def solve_pricing(self, *, time_limit_s: float = 5.0,
                      workers: int = 2,
                      warm_start_pattern: dict | None = None,
                      via_dsl: bool = False):
        """Return ``(pattern, status_name)`` -- pattern is a
        ``{(t, cl, s, d, h): 1}`` dict if FEASIBLE/OPTIMAL, else
        None."""
        if warm_start_pattern:
            self.add_warm_start_hint(warm_start_pattern)
        self.build(via_dsl=via_dsl)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(time_limit_s)
        solver.parameters.num_search_workers = int(workers)
        solver.parameters.log_search_progress = False
        status = solver.Solve(self.model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return None, solver.StatusName(status)
        out = {}
        for k, v in self.slot.items():
            if solver.Value(v):
                out[k] = 1
        return out, solver.StatusName(status)


class TeacherPricer(PricerSolver):
    """Per-teacher pricer for BP (V1 master variant)."""

    def __init__(self, profs: dict, dc_value: dict,
                 teacher: str, *, lambda_duals: dict | None = None,
                 mu_t: float = 0.0,
                 config: ConstraintConfig | None = None,
                 branching_constraints: list | None = None):
        super().__init__(
            profs, dc_value,
            config=config,
            scope=("teacher", teacher),
            lambda_duals=lambda_duals,
            mu_t=mu_t,
            branching_constraints=branching_constraints,
        )
        self.teacher = teacher


class TeacherClassPricer(PricerSolver):
    """Per (teacher, class) pricer (V1 master variant)."""

    def __init__(self, profs: dict, dc_value: dict,
                 teacher: str, class_name: str, *,
                 lambda_duals: dict | None = None,
                 mu_t: float = 0.0,
                 config: ConstraintConfig | None = None,
                 branching_constraints: list | None = None):
        super().__init__(
            profs, dc_value,
            config=config,
            scope=("teacher_class", teacher, class_name),
            lambda_duals=lambda_duals,
            mu_t=mu_t,
            branching_constraints=branching_constraints,
        )
        self.teacher = teacher
        self.class_name = class_name


class TeacherClassSubjectPricer(PricerSolver):
    """Per (teacher, class, subject) pricer (V1 master variant)."""

    def __init__(self, profs: dict, dc_value: dict,
                 teacher: str, class_name: str, subject: str, *,
                 lambda_duals: dict | None = None,
                 mu_t: float = 0.0,
                 config: ConstraintConfig | None = None,
                 branching_constraints: list | None = None):
        super().__init__(
            profs, dc_value,
            config=config,
            scope=("teacher_class_subject", teacher, class_name,
                   subject),
            lambda_duals=lambda_duals,
            mu_t=mu_t,
            branching_constraints=branching_constraints,
        )
        self.teacher = teacher
        self.class_name = class_name
        self.subject = subject


class TeacherSubjectPricer(PricerSolver):
    """Per (teacher, subject) pricer (V1 master variant)."""

    def __init__(self, profs: dict, dc_value: dict,
                 teacher: str, subject: str, *,
                 lambda_duals: dict | None = None,
                 mu_t: float = 0.0,
                 config: ConstraintConfig | None = None,
                 branching_constraints: list | None = None):
        super().__init__(
            profs, dc_value,
            config=config,
            scope=("teacher_subject", teacher, subject),
            lambda_duals=lambda_duals,
            mu_t=mu_t,
            branching_constraints=branching_constraints,
        )
        self.teacher = teacher
        self.subject = subject


class TeacherDayPricer(PricerSolver):
    """Per (teacher, day) pricer (V1 master variant)."""

    def __init__(self, profs: dict, dc_value: dict,
                 teacher: str, day: int, *,
                 lambda_duals: dict | None = None,
                 mu_t: float = 0.0,
                 config: ConstraintConfig | None = None,
                 branching_constraints: list | None = None):
        super().__init__(
            profs, dc_value,
            config=config,
            scope=("teacher_day", teacher, day),
            lambda_duals=lambda_duals,
            mu_t=mu_t,
            branching_constraints=branching_constraints,
            days=[day],
        )
        self.teacher = teacher
        self.day = day


class ClassPricer(PricerSolver):
    """Per-class pricer (V2 master variant -- multi-teacher column).

    For DW master, the dual structure includes class-no-overlap
    (mu_class) and teacher-no-overlap (mu_teacher) marginals; pass
    them via the ``mu_class`` / ``mu_teacher`` kwargs and override
    ``compute_dual_bonus_terms`` accordingly."""

    def __init__(self, profs: dict, dc_value: dict,
                 class_name: str, *,
                 lambda_cover: dict | None = None,
                 mu_class: dict | None = None,
                 mu_teacher: dict | None = None,
                 config: ConstraintConfig | None = None,
                 branching_constraints: list | None = None):
        super().__init__(
            profs, dc_value,
            config=config,
            scope=("class", class_name),
            lambda_duals=lambda_cover,
            mu_t=0.0,
            branching_constraints=branching_constraints,
        )
        self.class_name = class_name
        self.mu_class = mu_class or {}
        self.mu_teacher = mu_teacher or {}

    def compute_dual_bonus_terms(self) -> list:
        """V2 reduced cost adds mu_class * any_slot_at_(cl, d, h) and
        mu_teacher * any_slot_at_(t, d, h). Cover lambda is per
        (t, cl, s, d) as in V1."""
        # Cover reward (per (t, cl, s, d)): same as V1 base.
        bonus_terms = list(super().compute_dual_bonus_terms())
        # Class no-overlap: penalty mu_class[(cl, d, h)] * any.
        for d in self.days:
            for h in self.hours:
                mu_cl = float(self.mu_class.get(
                    (self.class_name, d, h), 0.0))
                if mu_cl == 0.0:
                    continue
                mu_int = int(round(mu_cl * SCALE))
                if mu_int == 0:
                    continue
                vs = self.slots_for_class_day_hour(
                    self.class_name, d, h)
                if not vs:
                    continue
                any_v = self.model.NewBoolVar(
                    f"any_cl_{self.class_name}_{d}_{h}")
                self.model.AddMaxEquality(any_v, vs)
                bonus_terms.append(mu_int * any_v)
        # Teacher no-overlap: penalty mu_teacher[(t, d, h)] * any.
        for t in self.teachers_in_scope():
            for d in self.days:
                for h in self.hours:
                    mu_t = float(self.mu_teacher.get((t, d, h), 0.0))
                    if mu_t == 0.0:
                        continue
                    mu_int = int(round(mu_t * SCALE))
                    if mu_int == 0:
                        continue
                    vs = self.slots_for_teacher_day_hour(t, d, h)
                    if not vs:
                        continue
                    any_v = self.model.NewBoolVar(
                        f"any_t_{t}_{d}_{h}")
                    self.model.AddMaxEquality(any_v, vs)
                    bonus_terms.append(mu_int * any_v)
        return bonus_terms


class ClassDayPricer(PricerSolver):
    """Per (class, day) pricer (V2 master variant)."""

    def __init__(self, profs: dict, dc_value: dict,
                 class_name: str, day: int, *,
                 lambda_cover: dict | None = None,
                 mu_class: dict | None = None,
                 mu_teacher: dict | None = None,
                 config: ConstraintConfig | None = None,
                 branching_constraints: list | None = None):
        super().__init__(
            profs, dc_value,
            config=config,
            scope=("class_day", class_name, day),
            lambda_duals=lambda_cover,
            mu_t=0.0,
            branching_constraints=branching_constraints,
            days=[day],
        )
        self.class_name = class_name
        self.day = day
        self.mu_class = mu_class or {}
        self.mu_teacher = mu_teacher or {}

    def compute_dual_bonus_terms(self) -> list:
        bonus_terms = list(super().compute_dual_bonus_terms())
        d = self.day
        for h in self.hours:
            mu_cl = float(self.mu_class.get(
                (self.class_name, d, h), 0.0))
            if mu_cl == 0.0:
                continue
            mu_int = int(round(mu_cl * SCALE))
            if mu_int == 0:
                continue
            vs = self.slots_for_class_day_hour(self.class_name, d, h)
            if not vs:
                continue
            any_v = self.model.NewBoolVar(
                f"any_cd_{self.class_name}_{d}_{h}")
            self.model.AddMaxEquality(any_v, vs)
            bonus_terms.append(mu_int * any_v)
        for t in self.teachers_in_scope():
            for h in self.hours:
                mu_t = float(self.mu_teacher.get((t, d, h), 0.0))
                if mu_t == 0.0:
                    continue
                mu_int = int(round(mu_t * SCALE))
                if mu_int == 0:
                    continue
                vs = self.slots_for_teacher_day_hour(t, d, h)
                if not vs:
                    continue
                any_v = self.model.NewBoolVar(
                    f"any_t_{t}_{d}_{h}")
                self.model.AddMaxEquality(any_v, vs)
                bonus_terms.append(mu_int * any_v)
        return bonus_terms


class DayPricer(PricerSolver):
    """Per-day pricer (V2 master variant -- single day, many
    teachers, many classes)."""

    def __init__(self, profs: dict, dc_value: dict,
                 day: int, *,
                 lambda_cover: dict | None = None,
                 mu_class: dict | None = None,
                 mu_teacher: dict | None = None,
                 config: ConstraintConfig | None = None,
                 branching_constraints: list | None = None):
        super().__init__(
            profs, dc_value,
            config=config,
            scope=("day", day),
            lambda_duals=lambda_cover,
            mu_t=0.0,
            branching_constraints=branching_constraints,
            days=[day],
        )
        self.day = day
        self.mu_class = mu_class or {}
        self.mu_teacher = mu_teacher or {}

    def compute_dual_bonus_terms(self) -> list:
        bonus_terms = list(super().compute_dual_bonus_terms())
        d = self.day
        # Class no-overlap penalty: every class in the day's scope.
        for cl in self.classes_in_scope():
            for h in self.hours:
                mu_cl = float(self.mu_class.get((cl, d, h), 0.0))
                if mu_cl == 0.0:
                    continue
                mu_int = int(round(mu_cl * SCALE))
                if mu_int == 0:
                    continue
                vs = self.slots_for_class_day_hour(cl, d, h)
                if not vs:
                    continue
                any_v = self.model.NewBoolVar(
                    f"any_dcl_{cl}_{d}_{h}")
                self.model.AddMaxEquality(any_v, vs)
                bonus_terms.append(mu_int * any_v)
        for t in self.teachers_in_scope():
            for h in self.hours:
                mu_t = float(self.mu_teacher.get((t, d, h), 0.0))
                if mu_t == 0.0:
                    continue
                mu_int = int(round(mu_t * SCALE))
                if mu_int == 0:
                    continue
                vs = self.slots_for_teacher_day_hour(t, d, h)
                if not vs:
                    continue
                any_v = self.model.NewBoolVar(
                    f"any_dt_{t}_{d}_{h}")
                self.model.AddMaxEquality(any_v, vs)
                bonus_terms.append(mu_int * any_v)
        return bonus_terms


class CurriculumPricer(PricerSolver):
    """Per-curriculum pricer (V2 master variant -- group of classes
    sharing the same curriculum/indirizzo).

    Scope filter is custom (we override _scope_includes_slot) since
    the base class's standard scopes don't capture "set of classes".
    """

    def __init__(self, profs: dict, dc_value: dict,
                 curriculum_id, classes_in_curriculum: list, *,
                 lambda_cover: dict | None = None,
                 mu_class: dict | None = None,
                 mu_teacher: dict | None = None,
                 config: ConstraintConfig | None = None,
                 branching_constraints: list | None = None):
        self._classes_in_curriculum = set(classes_in_curriculum or [])
        super().__init__(
            profs, dc_value,
            config=config,
            scope=("curriculum", curriculum_id),
            lambda_duals=lambda_cover,
            mu_t=0.0,
            branching_constraints=branching_constraints,
        )
        self.curriculum_id = curriculum_id
        self.mu_class = mu_class or {}
        self.mu_teacher = mu_teacher or {}

    def _scope_includes_slot(self, teacher: str, class_name: str,
                              subject: str, day: int) -> bool:
        return class_name in self._classes_in_curriculum

    def compute_dual_bonus_terms(self) -> list:
        bonus_terms = list(super().compute_dual_bonus_terms())
        for cl in self.classes_in_scope():
            for d in self.days:
                for h in self.hours:
                    mu_cl = float(self.mu_class.get((cl, d, h), 0.0))
                    if mu_cl == 0.0:
                        continue
                    mu_int = int(round(mu_cl * SCALE))
                    if mu_int == 0:
                        continue
                    vs = self.slots_for_class_day_hour(cl, d, h)
                    if not vs:
                        continue
                    any_v = self.model.NewBoolVar(
                        f"any_curcl_{cl}_{d}_{h}")
                    self.model.AddMaxEquality(any_v, vs)
                    bonus_terms.append(mu_int * any_v)
        for t in self.teachers_in_scope():
            for d in self.days:
                for h in self.hours:
                    mu_t = float(self.mu_teacher.get((t, d, h), 0.0))
                    if mu_t == 0.0:
                        continue
                    mu_int = int(round(mu_t * SCALE))
                    if mu_int == 0:
                        continue
                    vs = self.slots_for_teacher_day_hour(t, d, h)
                    if not vs:
                        continue
                    any_v = self.model.NewBoolVar(
                        f"any_curt_{t}_{d}_{h}")
                    self.model.AddMaxEquality(any_v, vs)
                    bonus_terms.append(mu_int * any_v)
        return bonus_terms
