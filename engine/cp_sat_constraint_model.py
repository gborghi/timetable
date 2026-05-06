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

    def add_class_no_overlap(self):
        """At most one slot per (class, day, hour). Coteach/parallel
        groups would relax this; handled by ``add_coteaching`` /
        ``add_parallel_intra``."""
        classes = self.classes_in_scope()
        for cl in classes:
            for d in self.days:
                for h in self.hours:
                    vs = self.slots_for_class_day_hour(cl, d, h)
                    if len(vs) > 1:
                        self.model.Add(sum(vs) <= 1)

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
        per-hour OR of class slots."""
        classes = self.classes_in_scope()
        for cl in classes:
            for d in self.days:
                present_per_h = []
                for h in self.hours:
                    vs = self.slots_for_class_day_hour(cl, d, h)
                    if not vs:
                        present_per_h.append(self.model.NewConstant(0))
                        continue
                    pr = self.model.NewBoolVar(f"pr_{cl}_{d}_{h}")
                    self.model.AddMaxEquality(pr, vs)
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
        to every class in scope."""
        if 11 not in self.hours:
            return
        h11_idx = self.hours.index(11)
        classes = self.classes_in_scope()
        for cl in classes:
            for d in self.days:
                vs = self.slots_for_class_day_hour(
                    cl, d, self.hours[h11_idx])
                if not vs:
                    continue
                # ``any_present`` over the day forces the h=11 slot to
                # be busy when the class has any lessons.
                day_vars = [v for (_t, ccl, _s, dd, _h), v
                             in self.slot.items()
                             if ccl == cl and dd == d]
                if not day_vars:
                    continue
                any_d = self.model.NewBoolVar(f"ap11_{cl}_{d}")
                self.model.AddMaxEquality(any_d, day_vars)
                pr11 = self.model.NewBoolVar(f"pr11_{cl}_{d}")
                self.model.AddMaxEquality(pr11, vs)
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

    def add_all_hard_constraints(self):
        """Apply every HARD constraint enabled by ``self.config``.

        Sub-classes can override to skip constraints that don't apply
        to their scope (e.g. the per-teacher pricer can skip
        ``add_class_no_overlap`` since it only sees one teacher's
        slots and intra-teacher class overlap is already covered by
        ``add_teacher_no_overlap``)."""
        self.add_teacher_no_overlap()
        if self.config.locks:
            self.add_locks()
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

    def build(self):
        self.add_all_hard_constraints()
        self.add_class_no_overlap()
        obj_terms, _ = self.compute_soft_cost_expr()
        if obj_terms:
            self.model.Minimize(sum(obj_terms))

    def solve(self, *, time_limit_s: float = 10.0,
              workers: int = 4, log: bool = False):
        self.build()
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
        return out, solver.StatusName(status)


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

    def build(self):
        self.add_all_hard_constraints()
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
                      warm_start_pattern: dict | None = None):
        """Return ``(pattern, status_name)`` -- pattern is a
        ``{(t, cl, s, d, h): 1}`` dict if FEASIBLE/OPTIMAL, else
        None."""
        if warm_start_pattern:
            self.add_warm_start_hint(warm_start_pattern)
        self.build()
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
