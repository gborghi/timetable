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
    from . import solver_config as _solvercfg  # type: ignore
except ImportError:  # direct script import (no package context)
    import solver_config as _solvercfg  # type: ignore

try:
    from . import metaheuristics as meta  # type: ignore
    from . import cpsat_v2_timetable as _cv2  # type: ignore
    from . import soft_costs  # type: ignore
except ImportError:  # direct script import (no package context)
    import metaheuristics as meta  # type: ignore
    import cpsat_v2_timetable as _cv2  # type: ignore
    import soft_costs  # type: ignore


DAYS = meta.DAYS
HOURS = meta.HOURS
# Mapping legacy_day_number -> active slot count (Tab Ore variable
# slots per day). Lives on cpsat_v2_timetable as the single source of
# truth so this module sees the same dict object after a refresh.
SLOTS_PER_DAY = _cv2.SLOTS_PER_DAY

# Integer scaling for fractional duals (kept identical to
# column_generation.py so reduced-cost arithmetic is consistent).
SCALE = 100

# SOFT penalty constants -- derived from meta.OBJECTIVE_WEIGHTS so
# the CP-SAT objective tracks meta.compute_soft term by term.
# These are used by ``compute_soft_cost_expr(mode="default")``.
PENALTY_SIXTH = meta.OBJECTIVE_WEIGHTS["sixth"] * SCALE
PENALTY_BUCHI = meta.OBJECTIVE_WEIGHTS["buchi"] * SCALE
PENALTY_FIVE = meta.OBJECTIVE_WEIGHTS["five"] * SCALE
PENALTY_ONE = meta.OBJECTIVE_WEIGHTS["one"] * SCALE
SIXTH_HOUR = 13

# Phase B per-day SOFT penalty constants -- mirror the per-day
# weights used by ``cpsat_v2_timetable.solve_phase_b_for_day`` so the
# OO solver can run a Phase B-equivalent per-day objective with the
# same optima as the legacy code. These are NOT scaled by ``SCALE``
# because the legacy weights are not scaled either; the per-day
# objective lives in its own (W_SIXTH_B, W_GAP) weight space and
# does NOT include the five/one penalties (Phase B per-day cannot
# observe weekly day-counts).
PENALTY_SIXTH_PD = 5    # legacy ``W_SIXTH_B``
PENALTY_BUCHI_PD = 10   # legacy ``W_GAP``

# Phase A SOFT penalty constants -- mirror the weights at
# ``cpsat_v2_timetable.solve_phase_a`` line ~760 so DayCountModel's
# objective tracks the legacy function's optimum.
PHASE_A_W_UNIFORM_CL = 4
PHASE_A_W_UNIFORM_PR = 3
PHASE_A_W_GLIB = 1       # multiplier on compiler.soft_cost_terms
PHASE_A_W_SIXTH = 50
PHASE_A_W_FIVE = 30
PHASE_A_W_ONE = 80
PHASE_A_MAX_PER_DAY_TRIPLE = 2
PHASE_A_MAX_PROF_HOURS_PER_DAY = 5


@dataclass
class ConstraintConfig:
    """Bundle of HARD/SOFT toggles + payload data the model uses."""
    enforce_no_holes: bool = True
    enforce_h3_presence_at_11: bool = True
    enforce_motorie_pair: bool = True
    enforce_math_italian_pair: bool = True
    # Per-class HARD-invariant overrides (finding 08b):
    # {class_name -> {flag_key -> bool}}. None = every class enforced (the
    # historical global behaviour). Honoured by both the seed path and the
    # legacy add_* methods below via ``cpsat_v2_timetable.class_enforces``.
    class_flags: Any = None
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
        dc_value: dict | None,
        config: ConstraintConfig | None = None,
        *,
        scope: tuple | None = None,
        days: Iterable[int] | None = None,
        hours: Iterable[int] | None = None,
        classroom_for_slot: dict | None = None,
    ):
        self.profs = profs
        # ``dc_value=None`` is the sentinel for "weekly mode": the model
        # has no per-day Phase A counts, slot vars are populated from
        # ``profs[t]["classi"][cl][s]["ore"]`` with a WEEKLY equality
        # ``sum_{d,h} slot == ore`` instead of a per-day equality. The
        # ``self.dc_value`` attribute is normalized to ``{}`` so existing
        # ``.get()`` callers keep working.
        self.weekly_mode = (dc_value is None)
        self.dc_value = {} if dc_value is None else dc_value
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
        # Optional per-(t,cl,s,d) day_count IntVars created in weekly
        # mode and tied to ``sum_h slot == day_count`` so callers can
        # ``AddHint`` Phase A solutions without forcing them as HARD
        # equalities. Empty dict in non-weekly mode.
        self.day_count_for_hint: dict[tuple, Any] = {}
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

        Two modes:

        * Per-day (``self.weekly_mode == False``, the default): for each
          ``(t, cl, s, d)`` with ``dc_value[(...)] > 0`` create the
          per-hour slot vars and enforce the cattedra-day equality
          ``sum_h slot == dc_value``. Triples whose dc_value is 0 (or
          missing) get NO slot vars -- the day-count input dictates the
          model surface, mirroring the legacy Phase B per-day path.

        * Weekly (``self.weekly_mode == True``): for each ``(t, cl, s)``
          with ``profs[t]["classi"][cl][s]["ore"] > 0`` create slot
          vars for ALL ``(d, h)`` in scope and enforce the WEEKLY
          equality ``sum_{d,h} slot == ore``. The per-(t,cl,s,d)
          ``day_count`` is left free for CP-SAT to choose; an IntVar
          tied to ``sum_h slot`` is exposed on
          ``self.day_count_for_hint`` so callers can ``AddHint`` a
          Phase A solution without forcing it as a HARD equality.
        """
        if self.weekly_mode:
            self._build_slot_variables_weekly()
            return
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

    def _build_slot_variables_weekly(self):
        """Weekly-mode variant of ``_build_slot_variables``: build slot
        BoolVars for every ``(t, cl, s, d, h)`` in scope and enforce the
        weekly equality ``sum_{d,h} slot == ore`` per cattedra. Also
        register a per-(t,cl,s,d) IntVar in ``self.day_count_for_hint``
        tied via ``sum_h slot == day_count`` so the OO solver caller
        can ``AddHint`` a Phase A solution without locking it in HARD.
        """
        cap_per_day = len(self.hours)
        for teacher, pdata in self.profs.items():
            if not self._scope_includes_teacher(teacher):
                continue
            classi = pdata.get("classi", {}) or {}
            for class_name, subjs in classi.items():
                for subject, sdata in subjs.items():
                    if isinstance(sdata, dict):
                        ore = int(sdata.get("ore", 0))
                    else:
                        ore = 0
                    if ore <= 0:
                        continue
                    triples_key = (teacher, class_name, subject)
                    week_vars = []
                    for d in self.days:
                        if not self._scope_includes_slot(
                                teacher, class_name, subject, d):
                            continue
                        day_vars = []
                        for h in self.hours:
                            v = self.model.NewBoolVar(
                                f"slot_{teacher}_{class_name}_"
                                f"{subject}_{d}_{h}")
                            self.slot[(teacher, class_name, subject,
                                        d, h)] = v
                            week_vars.append(v)
                            day_vars.append(v)
                        if day_vars:
                            dc = self.model.NewIntVar(
                                0, min(cap_per_day, ore),
                                f"dch_{teacher}_{class_name}_"
                                f"{subject}_{d}")
                            self.day_count_for_hint[
                                (teacher, class_name, subject, d)] = dc
                            self.model.Add(sum(day_vars) == dc)
                            # Keep ``self.triples`` populated for
                            # downstream methods that iterate over it
                            # (e.g. add_subject_pair_constraint reads
                            # nothing from it but other helpers may).
                            self.triples.setdefault(
                                triples_key, [])
                    if week_vars:
                        self.model.Add(sum(week_vars) == ore)

    # ----- helpers -----

    def teachers_in_scope(self) -> list:
        return sorted({k[0] for k in self.slot})

    def classes_in_scope(self) -> list:
        return sorted({k[1] for k in self.slot})

    def _class_enforces(self, cl: str, key: str, default: bool = True) -> bool:
        """Per-class HARD-invariant gate (finding 08b), shared with every
        other solver via ``cpsat_v2_timetable.class_enforces``."""
        try:
            from . import cpsat_v2_timetable as _cv2  # type: ignore
        except ImportError:
            import cpsat_v2_timetable as _cv2  # type: ignore
        return _cv2.class_enforces(
            getattr(self.config, "class_flags", None), cl, key, default)

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

    def add_variable_slots_per_day(self):
        """Tab Ore -- force slot vars to 0 for hour indices that
        exceed the active slot count of their day.

        ``self.hours`` is the UNIFORM hour array of length
        ``max_slots_per_day``. When a particular day in
        ``self.days`` has fewer active slots than that maximum
        (e.g. SAT only opens 4 afternoon hours while lun..ven open 6),
        the slot vars at the surplus hour indices must be zeroed so
        the solver cannot place a lesson there.

        No-op when every day has the maximum slot count (the legacy
        default), which keeps the existing 619-test surface
        bit-identical.
        """
        max_slots = len(self.hours)
        for d in self.days:
            n_slots = SLOTS_PER_DAY.get(int(d), max_slots)
            if n_slots >= max_slots:
                continue
            for h_idx in range(n_slots, max_slots):
                h = self.hours[h_idx]
                for (t, cl, s, dd, hh), v in self.slot.items():
                    if dd == d and hh == h:
                        self.model.Add(v == 0)

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
            # Per-class gates (finding 08b): `no_holes` (contiguity) and
            # `entry_at_8` (start at the first hour) default True.
            _nh = self._class_enforces(cl, "no_holes")
            _e8 = self._class_enforces(cl, "entry_at_8")
            if not (_nh or _e8):
                continue
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
                if _e8:
                    self.model.Add(present_per_h[0] >= ap)
                if _nh:
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
            # Per-class gate (finding 08b): h=11 presence == "uscita non
            # prima delle 12", i.e. the exit_after_12 toggle.
            if not self._class_enforces(cl, "exit_after_12"):
                continue
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

    def compute_soft_cost_expr(self, *, mode: str = "default",
                                  exclude: set | None = None,
                                  ) -> tuple[list, list]:
        """Return ``(obj_terms, aux_vars)`` -- a list of CP-SAT
        objective contributions and the auxiliary BoolVars/IntVars
        introduced.

        ``exclude`` (optional) drops named schedule-side objective
        components so the joint solver can let the user exclude a
        variable from the optimization without touching the HARD
        surface. Recognised names: ``"sixth"`` (6a ora), ``"buchi"``
        (teacher gaps), ``"day_load"`` (weekly five/one day
        distribution). An empty/absent set is the legacy path and stays
        byte-identical to it.

        ``mode`` selects the soft-cost formula:

        * ``"default"`` (Phase A canonical): emits ALL four
          components (sixth, buchi, five, one) per (teacher, day)
          with weights ``meta.OBJECTIVE_WEIGHTS * SCALE`` (i.e.
          ``50``, ``10``, ``30``, ``80`` × 100). Sixth is per-slot
          at ``h = SIXTH_HOUR``. Mirrors ``meta.compute_soft`` so a
          MonolithicSolver result has the same objective ordering as
          the weekly per-week formula.
        * ``"phase_b_per_day"``: mirrors the per-day formulation in
          ``cpsat_v2_timetable.solve_phase_b_for_day`` -- sixth
          penalty is per CLASS-busy indicator at ``h = SIXTH_HOUR``
          with weight ``PENALTY_SIXTH_PD = 5`` (legacy ``W_SIXTH_B``);
          buchi is per (teacher, day) with weight
          ``PENALTY_BUCHI_PD = 10`` (legacy ``W_GAP``); five/one
          penalties are SKIPPED (Phase B per-day cannot observe
          weekly day-counts -- the legacy emits these in Phase A on
          ``day_count`` IntVars). The class-busy indicator is built
          via ``_build_class_busy_indicators`` so it inherits the
          same exclusion + aggregation rules as
          ``add_class_no_overlap`` -- a coteach pair counts as ONE
          class-busy at h=13, sostegno is ignored, parallel-intra
          members count as ONE.

        ``self.fixed_load`` (set by sub-classes when greedy-base
        slots are out of CP-SAT scope) contributes a constant to the
        per-(teacher, day) hour count.

        Raises ``ValueError`` for unknown modes.
        """
        if mode not in ("default", "phase_b_per_day"):
            raise ValueError(
                f"compute_soft_cost_expr: unknown mode={mode!r}; "
                "expected 'default' or 'phase_b_per_day'")
        exclude = set(exclude or ())
        obj_terms: list = []
        aux_vars: list = []
        if not self.hours:
            return obj_terms, aux_vars
        # ----- Sixth-hour penalty -----
        if "sixth" in exclude:
            pass  # user excluded the 6a-ora term from the objective
        elif mode == "default":
            # Per-slot at SIXTH_HOUR -- matches _cost_of_pattern's
            # per-slot accounting in meta.compute_soft. Delegated to
            # ``soft_costs.sixth_slot_pairs`` (single source of truth);
            # the pairs are adapted to ``w*v`` products here.
            pairs, _ = soft_costs.sixth_slot_pairs(
                self.model, self.slot,
                weight=PENALTY_SIXTH, sixth_hour=SIXTH_HOUR)
            obj_terms.extend(w * v for w, v in pairs)
        else:  # phase_b_per_day
            # Per-class-busy at SIXTH_HOUR -- matches the legacy
            # ``sixth_terms = [present_per_class[cl][h13_idx] for cl
            # in cls_in_day]`` formulation. Delegated to
            # ``soft_costs.sixth_class_busy_terms``; the per-class
            # exclusion + aggregation rules live in the callback
            # ``_build_class_busy_indicators`` (name_suffix="sixth").
            if SIXTH_HOUR in self.hours:
                sx_terms, sx_aux = soft_costs.sixth_class_busy_terms(
                    self.model,
                    lambda cl, d, h: self._build_class_busy_indicators(
                        cl, d, h, name_suffix="sixth"),
                    self._classes_with_busy_aggregation(),
                    self.days,
                    weight=PENALTY_SIXTH_PD, sixth_hour=SIXTH_HOUR)
                obj_terms.extend(sx_terms)
                aux_vars.extend(sx_aux)
        # ----- Per-(teacher, day) buchi (and five/one in default) -----
        # Delegated to ``soft_costs.buchi_and_daydist_terms`` (single
        # source of truth). Teacher scope = ``teachers_in_scope()``
        # (slot-derived); slot access inside the encoder is the exact
        # inline equivalent of ``slots_for_teacher_day_hour``; the
        # greedy-base ``self.fixed_load`` is threaded through; five/one
        # are gated to mode='default'.
        want_buchi = "buchi" not in exclude
        want_dayload = (mode == "default") and ("day_load" not in exclude)
        buchi_w = PENALTY_BUCHI if mode == "default" else PENALTY_BUCHI_PD
        if want_buchi and (want_dayload == (mode == "default")):
            # Nothing excluded from this block -> exact legacy call
            # (byte-identical objective ordering).
            bt, ba = soft_costs.buchi_and_daydist_terms(
                self.model, self.slot, self.teachers_in_scope(), self.days,
                self.hours,
                buchi_weight=buchi_w,
                five_weight=PENALTY_FIVE, one_weight=PENALTY_ONE,
                include_five_one=(mode == "default"),
                fixed_load=self.fixed_load)
            obj_terms.extend(bt)
            aux_vars.extend(ba)
        else:
            # Selective: emit only the requested sub-terms via the
            # separable pair encoders (same shared _buchi_daydist_vars).
            if want_buchi:
                bp, ba = soft_costs.buchi_pairs(
                    self.model, self.slot, self.teachers_in_scope(),
                    self.days, self.hours, weight=buchi_w,
                    fixed_load=self.fixed_load)
                obj_terms.extend(w * v for w, v in bp)
                aux_vars.extend(ba)
            if want_dayload:
                fp, fa = soft_costs.five_one_pairs(
                    self.model, self.slot, self.teachers_in_scope(),
                    self.days, self.hours,
                    five_weight=PENALTY_FIVE, one_weight=PENALTY_ONE,
                    fixed_load=self.fixed_load)
                obj_terms.extend(w * v for w, v in fp)
                aux_vars.extend(fa)
        return obj_terms, aux_vars

    def add_subject_pair_constraint(
        self, subject_name: str, *, mode: str, flag_key: str | None = None,
    ):
        """Add a "consecutive pair" constraint on a specific subject.

        ``mode == "must_pair"``: when the (teacher, class, subject)
            has exactly 2 hours that day, they MUST be consecutive
            (used for Scienzemotorie -- always paired).
        ``mode == "pair_exists"``: when the (teacher, class, subject)
            has >= 2 hours that day, at least one consecutive pair
            of busy hours must exist (used for Matematica/Italiano
            -- doppia consecutiva).

        In per-day mode the day-count is read statically from
        ``self.dc_value`` so the constraint only fires when the
        cattedra-day demand triggers it. In weekly mode (where the
        day-count is itself a CP-SAT decision) the trigger is reified
        through ``sum_h slot``: the pair constraint is added under
        ``OnlyEnforceIf(is_two)`` for ``must_pair`` and
        ``OnlyEnforceIf(is_ge_two)`` for ``pair_exists``, so it kicks
        in exactly when the chosen day distribution would activate it
        in per-day mode. Equivalent semantics, no static gating.
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
            want = _cv2.subject_key(subject_name)
            for class_name, subjs in classi.items():
                # Per-class gate (finding 08b): skip the class whose card
                # turned this pair invariant off (motorie / mat / ita).
                if flag_key and not self._class_enforces(class_name, flag_key):
                    continue
                # The caller passes a literal ("Matematica",
                # "Italiano", "Scienzemotorie") but the school names
                # its subjects freely, so match on the canonical key
                # and then use the school's own spelling to build the
                # slot keys. An exact `in` test here made the rule
                # vanish silently for e.g. "Scienze motorie".
                subj = next((s for s in subjs
                             if _cv2.subject_key(s) == want), None)
                if subj is None:
                    continue
                for d in self.days:
                    keys_for_day = [
                        (teacher, class_name, subj, d, h)
                        for h in self.hours
                    ]
                    vs = [self.slot.get(k) for k in keys_for_day]
                    vs = [v for v in vs if v is not None]
                    if len(vs) != len(self.hours):
                        # subject not in scope on this day
                        continue
                    if self.weekly_mode:
                        # Reified gate: the day-count is a CP-SAT
                        # decision, so we cannot statically skip
                        # day-pairs. Build is_two / is_ge_two from
                        # ``sum(vs)`` and gate the pair constraint
                        # on it.
                        day_sum = sum(vs)
                        pairs = []
                        for i in range(len(self.hours) - 1):
                            pair = self.model.NewBoolVar(
                                f"pair_{subject_name[:3]}_"
                                f"{teacher}_{class_name}_{d}_{i}")
                            self.model.AddBoolAnd(
                                [vs[i], vs[i + 1]]
                            ).OnlyEnforceIf(pair)
                            self.model.AddBoolOr(
                                [vs[i].Not(), vs[i + 1].Not()]
                            ).OnlyEnforceIf(pair.Not())
                            pairs.append(pair)
                        if not pairs:
                            continue
                        any_pair = self.model.NewBoolVar(
                            f"anyp_{subject_name[:3]}_"
                            f"{teacher}_{class_name}_{d}")
                        self.model.AddMaxEquality(any_pair, pairs)
                        if mode == "must_pair":
                            is_two = self.model.NewBoolVar(
                                f"isTwo_{subject_name[:3]}_"
                                f"{teacher}_{class_name}_{d}")
                            self.model.Add(
                                day_sum == 2).OnlyEnforceIf(is_two)
                            self.model.Add(
                                day_sum != 2).OnlyEnforceIf(
                                    is_two.Not())
                            self.model.AddImplication(is_two, any_pair)
                        elif mode == "pair_exists":
                            is_ge_two = self.model.NewBoolVar(
                                f"isGE2_{subject_name[:3]}_"
                                f"{teacher}_{class_name}_{d}")
                            # is_ge_two <-> day_sum >= 2
                            self.model.Add(
                                day_sum >= 2).OnlyEnforceIf(is_ge_two)
                            self.model.Add(
                                day_sum <= 1).OnlyEnforceIf(
                                    is_ge_two.Not())
                            self.model.AddImplication(
                                is_ge_two, any_pair)
                        else:
                            raise ValueError(
                                f"add_subject_pair_constraint: "
                                f"unknown mode={mode!r}; expected "
                                "'must_pair' or 'pair_exists'")
                        continue
                    day_total = int(self.dc_value.get(
                        (teacher, class_name, subj, d), 0))
                    if mode == "must_pair" and day_total != 2:
                        continue
                    if mode == "pair_exists" and day_total < 2:
                        continue
                    # presence[h] is just slot[(t, cl, subj, d, h)]
                    # since each hour has exactly one slot var per
                    # cattedra.
                    pairs = []
                    for i in range(len(self.hours) - 1):
                        pair = self.model.NewBoolVar(
                            f"pair_{subject_name[:3]}_"
                            f"{teacher}_{class_name}_{d}_{i}")
                        self.model.AddBoolAnd(
                            [vs[i], vs[i + 1]]
                        ).OnlyEnforceIf(pair)
                        self.model.AddBoolOr(
                            [vs[i].Not(), vs[i + 1].Not()]
                        ).OnlyEnforceIf(pair.Not())
                        pairs.append(pair)
                    if pairs:
                        self.model.AddBoolOr(pairs)

    def add_motorie_pair(self):
        """Scienzemotorie: 2 hours/day MUST be consecutive."""
        self.add_subject_pair_constraint(
            "Scienzemotorie", mode="must_pair", flag_key="motorie_pairs")

    def add_math_italian_pair(self):
        """Matematica + Italiano: when >= 2 hours/day, at least one
        consecutive pair of busy hours."""
        self.add_subject_pair_constraint(
            "Matematica", mode="pair_exists", flag_key="dual_math")
        self.add_subject_pair_constraint(
            "Italiano", mode="pair_exists", flag_key="dual_italian")

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
                            plessi_data: Any = None,
                            level: str = "both",
                            is_hard: bool = True,
                            soft_weight: int = 0):
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

        ``level`` selects the pragma level filter passed to the
        compiler. ``"both"`` (default) keeps the historical behaviour
        where every recognised pragma is compiled. ``"phase_b"``
        drops the Phase A-only pragmas (their level is
        ``"phase_a"``); ``"phase_a"`` drops the Phase B-only ones.

        ``is_hard`` (default True) controls whether violations force
        infeasibility (HARD) or contribute ``soft_weight`` per
        violation to ``self.dsl_soft_cost_terms`` (SOFT). The owning
        solver subclass (``MonolithicSolver`` etc.) sums those terms
        into its objective so a SOFT general_dsl rule influences the
        search by cost rather than by feasibility.
        """
        try:
            from . import dsl_to_cpsat as d2c  # type: ignore
        except ImportError:
            import dsl_to_cpsat as d2c  # type: ignore
        if not hasattr(self, "dsl_diagnostics"):
            self.dsl_diagnostics: list[str] = []
        if not hasattr(self, "dsl_soft_cost_terms"):
            self.dsl_soft_cost_terms: list = []
        cfs = classroom_for_slot
        if cfs is None:
            cfs = getattr(self, "classroom_for_slot", None)
        plessi = plessi_data
        if plessi is None:
            plessi = getattr(self.config, "plessi_data", None)
        compiler = d2c.DSLConstraintCompiler(
            self.model, self.slot, config=self.config,
            is_hard=is_hard,
            soft_weight=int(soft_weight),
            classroom_for_slot=cfs,
            plessi_data=plessi,
            # ``owner_model=self`` lets the no_holes / h11 pragmas
            # share ``_build_class_busy_indicators`` -- the same
            # exclusion + aggregation logic backing
            # ``add_class_no_overlap`` -- so rules compiled via the
            # DSL match the OO methods byte-for-byte even when
            # sostegno / coteach / parallel intra are registered.
            owner_model=self,
            level=level,
        )
        compiler.compile(expression)
        self.dsl_diagnostics.extend(compiler.diagnostics)
        self.dsl_soft_cost_terms.extend(compiler.soft_cost_terms)

    def add_all_dsl_constraints(self, expressions: list, *,
                                  classroom_for_slot: dict | None = None,
                                  plessi_data: Any = None,
                                  level: str = "both"):
        """Convenience: compile every expression in the list. Useful
        when the caller has loaded a batch of LogicalUnavailability
        rows and wants to push them all into the model. ``level``
        forwards to the compiler's pragma level filter."""
        for expr in expressions or []:
            self.add_dsl_constraint(
                expr,
                classroom_for_slot=classroom_for_slot,
                plessi_data=plessi_data,
                level=level,
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

        When ``include_soft=True`` SOFT general_dsl rules are also
        compiled with ``is_hard=False, soft_weight=r["weight"]`` so
        they contribute to ``self.dsl_soft_cost_terms`` and -- via the
        subclass that owns the objective -- to the soft cost.
        """
        try:
            from . import dsl_translator as dt  # type: ignore
        except ImportError:
            import dsl_translator as dt  # type: ignore
        rules = dt.load_all_dsl_constraints(
            db, include_soft=include_soft)
        for r in rules:
            self.add_dsl_constraint(
                r["expression"],
                is_hard=bool(r.get("is_hard", True)),
                soft_weight=int(r.get("weight", 0) or 0),
            )
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
        # Tab Ore: zero out slot vars on hour indices exceeding the
        # day's active slot count. Cheap no-op when every day has the
        # uniform max slot count.
        self.add_variable_slots_per_day()
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
                class_flags=self.config.class_flags,
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

    def add_phase_a_hint(self, dc_value: dict) -> int:
        """Push a Phase A solution into the model as a SOFT hint via
        ``model.AddHint`` on the ``self.day_count_for_hint`` IntVars
        (which are tied to ``sum_h slot``). The solver is free to
        ignore the hint, but a good Phase A solution often warm-starts
        the search. Only available in weekly mode (``self.weekly_mode
        == True``); a no-op otherwise. Returns the number of
        ``(t,c,s,d)`` keys that were hinted.
        """
        if not self.weekly_mode:
            return 0
        if not dc_value:
            return 0
        n = 0
        for k, n_val in dc_value.items():
            if not isinstance(k, tuple) or len(k) != 4:
                # Skip unrelated keys (e.g. legacy ``("__coday__",
                # group_id, day)`` markers) -- they are not part of
                # the day_count_for_hint surface.
                continue
            dc_var = self.day_count_for_hint.get(k)
            if dc_var is None:
                continue
            try:
                self.model.AddHint(dc_var, int(n_val))
                n += 1
            except Exception:  # noqa: BLE001
                # AddHint rejects out-of-domain values silently in
                # newer or-tools, but raises in some versions; the
                # hint is best-effort, never blocking.
                pass
        return n


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
        # Universal CCNL HARD rules. Emitted as DSL pragmas so the OO
        # solver enforces them even when the caller doesn't preload
        # the DSL constraint stream from a DB session (e.g. the
        # benchmark harness in tests/benchmarks/run_full_sweep.py
        # which calls MonolithicSolver(profs, ...) without a DB).
        # Production callers that load per-teacher overrides via
        # ``load_all_dsl_constraints`` simply add a stricter
        # constraint on top -- CP-SAT honors the strictest of the two.
        for t in sorted(self.profs):
            qt = '"' + str(t).replace('\\', '\\\\').replace('"', '\\"') + '"'
            # ``teacher_at_least_n_free_days``: every teacher has at
            # least N weekdays with zero lessons. The per-teacher
            # floor is read from ``profs[t]["min_free_days"]`` when
            # present (populated by ``engine_io.profs_dict_from_db``
            # for DB-driven callers and by the bench loaders for
            # SQLite stress profiles); falls back to the CCNL default
            # of 1 otherwise. n=0 is treated as "no constraint" and
            # skipped.
            n_floor = int(
                self.profs.get(t, {}).get("min_free_days", 1) or 0)
            if n_floor > 0:
                self.add_dsl_constraint(
                    f'teacher_at_least_n_free_days({qt}, {n_floor})',
                    level="phase_b")
            # ``teacher_max_per_day``: cap daily teacher load at 5
            # hours so the legacy HC ("no 6-consecutive-hour bands")
            # rule is enforced. Mirrors MAX_PROF_HOURS_PER_DAY=5 in
            # cpsat_v2_timetable.
            self.add_dsl_constraint(
                f'teacher_max_per_day({qt}, '
                f'{PHASE_A_MAX_PROF_HOURS_PER_DAY})',
                level="phase_b")
        obj_terms, _ = self.compute_soft_cost_expr()
        # Append SOFT general_dsl penalties (filled by
        # ``add_dsl_constraint`` calls with ``is_hard=False``). Each
        # entry is ``(weight, BoolVar | IntVar)``; the weight is the
        # per-violation penalty the user picked in the UI.
        for w, var in getattr(self, "dsl_soft_cost_terms", []):
            obj_terms.append(int(w) * var)
        if obj_terms:
            self.model.Minimize(sum(obj_terms))

    def solve(self, *, time_limit_s: float = 10.0,
              workers: int = 4, log: bool = False,
              via_dsl: bool = False, forbidden_solutions=None):
        self.build(via_dsl=via_dsl)
        # DSL no-good refinement: forbid each previously-rejected exact
        # assignment over the FRESHLY-built slot vars. ``build()`` is not
        # idempotent (it re-creates ``self.slot``), so the no-goods are
        # re-applied here, on each solve, against the current vars.
        # Default ``None`` -> zero cuts -> byte-identical to the plain path.
        if forbidden_solutions:
            try:
                from . import dsl_cp_gate as _gate  # type: ignore
            except ImportError:
                import dsl_cp_gate as _gate  # type: ignore
            for fsol in forbidden_solutions:
                _gate.add_nogood(self.model, self.slot, fsol)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(time_limit_s)
        solver.parameters.num_search_workers = int(workers)
        solver.parameters.log_search_progress = log
        _solvercfg.configure_solver(solver)
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

    def solve_dsl_compliant(self, hard_exprs, profs, *,
                            max_iters: int = 8, time_limit_s: float = 10.0,
                            workers: int = 8, log: bool = False,
                            via_dsl: bool = False):
        """Solve, completely honoring any checkable HARD DSL.

        Runs the verify + no-good refinement loop from ``dsl_cp_gate``:
        each iteration rebuilds the model (``solve()`` calls ``build()``)
        with all accumulated forbidden assignments re-applied as no-goods,
        solves, and verifies the HARD DSL on the result via the post-hoc
        evaluator. Natively-compiled rules pass on iteration 0 (no extra
        solve); only genuinely un-compiled violations trigger a refine.

        Returns ``(sol, status, unsatisfied)`` where ``unsatisfied`` is the
        list of still-violated expression strings (empty = fully compliant).
        """
        try:
            from . import dsl_cp_gate as _gate  # type: ignore
        except ImportError:
            import dsl_cp_gate as _gate  # type: ignore

        def _solve_once(forbidden):
            return self.solve(time_limit_s=time_limit_s, workers=workers,
                              log=log, via_dsl=via_dsl,
                              forbidden_solutions=forbidden)

        return _gate.solve_with_dsl_refinement(
            _solve_once, profs, hard_exprs, max_iters=max_iters)


# ============================================================
# DayCountModel -- Phase A equivalent (day_count IntVars only)
# ============================================================


class DayCountModel(ConstraintModel):
    """Phase A equivalent of MonolithicSolver: builds per-(p, c, s, d)
    ``day_count`` IntVars instead of per-(p, c, s, d, h) slot
    BoolVars. The constraint catalogue is supplied through the DSL
    compiler at level ``"phase_a"`` -- the five Phase A canonical
    pragmas (``class_day_load_in_day_count``, ``hall_bound_prof_day``,
    ``free_day_choice_3way``, ``subject_day_count_pair``,
    ``subject_day_count_in``) cover the HARD surface of the legacy
    function ``cpsat_v2_timetable.solve_phase_a`` plus the SOFT
    free-day choice.

    Lifecycle
    ---------
    1. ``__init__`` reads ``profs`` and (optionally) ``ore_per_triple``,
       overrides ``_build_slot_variables`` to populate ``self.day_count``
       with the IntVars and the weekly ``sum_d == ore`` equality.
       ``self.slot`` is left empty (Phase A has no hour dimension).
    2. ``add_dsl_constraint(expr)`` routes through the compiler at
       level ``"phase_a"``; Phase B pragmas are skipped with a
       diagnostic. Soft-cost contributions from Phase A pragmas
       (e.g. ``free_day_choice_3way``) are accumulated on
       ``self.dsl_soft_cost_terms``.
    3. ``compute_soft_cost_expr(mode="phase_a")`` assembles the
       Phase A objective (uniform_class, uniform_prof, sixth-hour,
       five, one, plus weighted DSL soft terms).
    4. ``solve()`` builds the objective, runs the solver, returns
       ``(dc_value_dict, status_name)``.

    Slot key convention
    -------------------
    ``self.day_count[(teacher, class_name, subject, day)] -> IntVar``
    in ``[0, min(MAX_PER_DAY_TRIPLE, ore)]``.

    Cattedra ``ore`` are read from ``profs[teacher]["classi"][cl]
    [subj]["ore"]``; pass an explicit ``ore_per_triple`` dict to
    override (useful when the caller knows the curriculum directly).
    """

    def __init__(
        self,
        profs: dict,
        config: ConstraintConfig | None = None,
        *,
        ore_per_triple: dict | None = None,
        scope: tuple | None = None,
        days: Iterable[int] | None = None,
    ):
        self._ore_per_triple = ore_per_triple
        # ``dc_value`` is intentionally left empty: Phase A SCHEDULES
        # day_count, it is not a fixed input. Provide an empty dict to
        # keep the parent's ``_scope_includes_slot`` path happy.
        super().__init__(profs, dc_value={}, config=config,
                          scope=scope, days=days, hours=[])

    def _build_slot_variables(self):
        """Override: build day_count IntVars instead of slot BoolVars.

        For every triple ``(teacher, class, subject)`` that resolves
        within scope and has positive ``ore``, create six (one per
        day) IntVars in ``[0, min(MAX_PER_DAY_TRIPLE, ore)]`` and
        enforce ``sum_d == ore``.

        ``self.slot`` stays an empty dict so any inherited Phase B
        method that looks up slot vars yields a sensible no-op.
        """
        self.slot = {}
        self.day_count: dict[tuple, Any] = {}
        self.weekly_ore: dict[tuple, int] = {}
        for teacher, pdata in self.profs.items():
            if not self._scope_includes_teacher(teacher):
                continue
            classi = pdata.get("classi", {}) or {}
            for class_name, subjs in classi.items():
                for subject, sdata in subjs.items():
                    triples_key = (teacher, class_name, subject)
                    if self._ore_per_triple is not None:
                        ore = int(self._ore_per_triple.get(
                            triples_key, sdata.get("ore", 0)))
                    else:
                        ore = int(sdata.get("ore", 0)) if isinstance(
                            sdata, dict) else 0
                    if ore <= 0:
                        continue
                    self.weekly_ore[triples_key] = ore
                    cap = min(PHASE_A_MAX_PER_DAY_TRIPLE, ore)
                    for d in self.days:
                        if not self._scope_includes_slot(
                                teacher, class_name, subject, d):
                            continue
                        v = self.model.NewIntVar(
                            0, cap,
                            f"dc_{teacher}_{class_name}_"
                            f"{subject}_{d}")
                        self.day_count[
                            (teacher, class_name, subject, d)] = v
                    day_vars = [
                        self.day_count[
                            (teacher, class_name, subject, d)]
                        for d in self.days
                        if (teacher, class_name, subject, d)
                        in self.day_count]
                    if day_vars:
                        self.model.Add(sum(day_vars) == ore)

    # ----- DSL integration -----

    def add_dsl_constraint(self, expression, *,
                            classroom_for_slot: dict | None = None,
                            plessi_data: Any = None):
        """Override: route the expression through the compiler at
        level ``"phase_a"`` so only Phase A pragmas land. Soft-cost
        contributions are accumulated on
        ``self.dsl_soft_cost_terms`` for the objective.
        """
        try:
            from . import dsl_to_cpsat as d2c  # type: ignore
        except ImportError:
            import dsl_to_cpsat as d2c  # type: ignore
        if not hasattr(self, "dsl_diagnostics"):
            self.dsl_diagnostics = []
        if not hasattr(self, "dsl_soft_cost_terms"):
            self.dsl_soft_cost_terms: list = []
        compiler = d2c.DSLConstraintCompiler(
            self.model, self.slot, config=self.config,
            classroom_for_slot=classroom_for_slot,
            plessi_data=plessi_data,
            owner_model=self,
            day_count=self.day_count,
            level="phase_a",
        )
        compiler.compile(expression)
        self.dsl_diagnostics.extend(compiler.diagnostics)
        self.dsl_soft_cost_terms.extend(compiler.soft_cost_terms)

    # ----- objective -----

    def compute_soft_cost_expr(self, *, mode: str = "phase_a"
                                  ) -> tuple[list, list]:
        """Phase A objective: uniformity penalties (per-cattedra and
        per-prof spread), the sixth-hour count on cl_day_load==6,
        the prof_day_load five/one indicators, plus DSL-side soft
        contributions (e.g. free_day_choice_3way weights).

        Mirrors ``cpsat_v2_timetable.solve_phase_a`` lines 757..767.
        """
        if mode != "phase_a":
            raise ValueError(
                f"DayCountModel.compute_soft_cost_expr: unknown "
                f"mode={mode!r}; expected 'phase_a'")
        obj_terms: list = []
        aux_vars: list = []
        # ----- 1. uniform_class_pen ------------------------------
        # sum_(t,cl,s,d) |day_count*6 - ore|
        abs_terms: list = []
        for triples_key, ore in self.weekly_ore.items():
            for d in self.days:
                dv = self.day_count.get(triples_key + (d,))
                if dv is None:
                    continue
                diff = self.model.NewIntVar(
                    -12, 12,
                    f"_pa_dif_{triples_key[0]}_{triples_key[1]}_"
                    f"{triples_key[2]}_{d}")
                self.model.Add(diff == dv * 6 - ore)
                ad = self.model.NewIntVar(
                    0, 12,
                    f"_pa_adif_{triples_key[0]}_{triples_key[1]}_"
                    f"{triples_key[2]}_{d}")
                self.model.AddAbsEquality(ad, diff)
                abs_terms.append(ad)
                aux_vars.extend([diff, ad])
        if abs_terms:
            obj_terms.append(PHASE_A_W_UNIFORM_CL * sum(abs_terms))
        # ----- 2. uniform_prof_pen + 3. five/one  -----------------
        triples_by_prof: dict[str, list] = {}
        for (t, cl, s) in self.weekly_ore:
            triples_by_prof.setdefault(t, []).append((cl, s))
        ore_by_prof = {
            t: sum(self.weekly_ore[(t, cl, s)] for (cl, s) in lst)
            for t, lst in triples_by_prof.items()
        }
        prof_day_load: dict[tuple, Any] = {}
        abs_prof_terms: list = []
        five_inds: list = []
        one_inds: list = []
        for p, lst in triples_by_prof.items():
            for d in self.days:
                ld = self.model.NewIntVar(
                    0, PHASE_A_MAX_PROF_HOURS_PER_DAY,
                    f"_pa_pld_{p}_{d}")
                self.model.Add(
                    ld == sum(self.day_count[(p, cl, s, d)]
                              for (cl, s) in lst
                              if (p, cl, s, d) in self.day_count)
                )
                prof_day_load[(p, d)] = ld
                aux_vars.append(ld)
                # uniform_prof_pen contribution
                ore_tot = ore_by_prof[p]
                diff = self.model.NewIntVar(
                    -30, 30, f"_pa_pdif_{p}_{d}")
                self.model.Add(diff == ld * 6 - ore_tot)
                ad = self.model.NewIntVar(
                    0, 30, f"_pa_padif_{p}_{d}")
                self.model.AddAbsEquality(ad, diff)
                abs_prof_terms.append(ad)
                aux_vars.extend([diff, ad])
                # five/one indicators
                is5 = self.model.NewBoolVar(f"_pa_is5_{p}_{d}")
                self.model.Add(ld == 5).OnlyEnforceIf(is5)
                self.model.Add(ld != 5).OnlyEnforceIf(is5.Not())
                is1 = self.model.NewBoolVar(f"_pa_is1_{p}_{d}")
                self.model.Add(ld == 1).OnlyEnforceIf(is1)
                self.model.Add(ld != 1).OnlyEnforceIf(is1.Not())
                five_inds.append(is5)
                one_inds.append(is1)
                aux_vars.extend([is5, is1])
        if abs_prof_terms:
            obj_terms.append(PHASE_A_W_UNIFORM_PR * sum(abs_prof_terms))
        if five_inds:
            obj_terms.append(PHASE_A_W_FIVE * sum(five_inds))
        if one_inds:
            obj_terms.append(PHASE_A_W_ONE * sum(one_inds))
        # ----- 4. n_sixth_hour ------------------------------------
        # cl_day_load[c, d] == 6 -> contributes 1.
        sixth_inds: list = []
        for cl in sorted({k[1] for k in self.day_count}):
            for d in self.days:
                terms = [v for (_pp, ccl, _s, dd), v
                          in self.day_count.items()
                          if ccl == cl and dd == d]
                if not terms:
                    continue
                cdl = self.model.NewIntVar(
                    0, 100, f"_pa_cdl_{cl}_{d}")
                self.model.Add(cdl == sum(terms))
                is6 = self.model.NewBoolVar(f"_pa_is6_{cl}_{d}")
                self.model.Add(cdl == 6).OnlyEnforceIf(is6)
                self.model.Add(cdl != 6).OnlyEnforceIf(is6.Not())
                sixth_inds.append(is6)
                aux_vars.extend([cdl, is6])
        if sixth_inds:
            obj_terms.append(PHASE_A_W_SIXTH * sum(sixth_inds))
        # ----- 5. DSL soft cost terms (free_day_choice_3way) ------
        for w, v in getattr(self, "dsl_soft_cost_terms", []):
            obj_terms.append(int(w) * PHASE_A_W_GLIB * v)
        return obj_terms, aux_vars

    # ----- solve -----

    def build(self):
        obj_terms, _ = self.compute_soft_cost_expr(mode="phase_a")
        if obj_terms:
            self.model.Minimize(sum(obj_terms))

    def solve(self, *, time_limit_s: float = 10.0,
              workers: int = 4, log: bool = False):
        """Build the Phase A objective and run the solver. Returns
        ``({(teacher, class, subject, day): int}, status_name)``."""
        self.build()
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(time_limit_s)
        solver.parameters.num_search_workers = int(workers)
        solver.parameters.log_search_progress = log
        _solvercfg.configure_solver(solver)
        status = solver.Solve(self.model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return None, solver.StatusName(status)
        out: dict = {}
        for k, v in self.day_count.items():
            val = int(solver.Value(v))
            if val > 0:
                out[k] = val
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
        special_room_ctx: Any = None,
        total_room_capacity: int | None = None,
    ):
        self.profs = profs
        self.dc_value = dc_value
        self.day = int(day)
        self.config = config or ConstraintConfig()
        self.db = db
        # finding 34: capacita' aule speciali (palestra/lab). Il repair di
        # giornata (metaheuristics._cp_repair) gira nel post-processing dove
        # `db` NON e' passato (la sessione e' chiusa): senza questo ctx
        # esplicito il CP di ricucitura ignorerebbe la capienza palestra e
        # potrebbe reintrodurre l'overflow. Se None e db c'e', lo si
        # ricostruisce; altrimenti si usa quello passato dal chiamante.
        self.special_room_ctx = special_room_ctx
        # Per-slot general room capacity (option A): total room count cap
        # applied per (day, hour). None/0 -> off (byte-identical). Opt-in,
        # forwarded to solve_phase_b_for_day exactly like special_room_ctx.
        self.total_room_capacity = total_room_capacity
        if self.special_room_ctx is None and db is not None:
            try:
                from . import cpsat_v2_timetable as _cv2  # type: ignore
            except ImportError:
                import cpsat_v2_timetable as _cv2  # type: ignore
            try:
                self.special_room_ctx = _cv2.build_special_room_ctx(db)
            except Exception:
                pass
        # 08b: when a db is given but no explicit config, load the per-class
        # HARD-invariant overrides so a day-repair (metaheuristics._cp_repair)
        # honours the class-card toggles instead of re-enforcing everything.
        if config is None and db is not None and self.config.class_flags is None:
            try:
                from . import cpsat_v2_timetable as _cv2  # type: ignore
            except ImportError:
                import cpsat_v2_timetable as _cv2  # type: ignore
            try:
                self.config.class_flags = _cv2.build_class_flags(db)
            except Exception:
                pass
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
            # finding 34: always pass the special-room capacity ctx, even
            # when via_dsl=False (no db), so the day-repair respects the
            # palestra/lab capienza in the post-processing path too.
            special_room_ctx=self.special_room_ctx,
            total_room_capacity=self.total_room_capacity,
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
        _solvercfg.configure_solver(solver)
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
