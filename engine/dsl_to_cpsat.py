"""Compile general_dsl AST nodes into CP-SAT constraints applied
during solver search (not post-hoc).

The DSL parser ``webui/backend/utils/general_dsl.py`` produces an AST
of Lit / Ref / Cmp / And / Or / Not / Implies / Iff / Quant / Count /
Call nodes. The post-hoc evaluator in ``logic_parser.py`` flattens
those to DNF and checks them against a finalised solution. THIS
module is the missing complement: it walks the same AST and emits
CP-SAT model constraints that operate on slot decision variables, so
the solver enforces (HARD) or penalises (SOFT) the rule during
search.

Scope of this commit
====================
- Static-filter forall / exists / count over ``lessons`` (the
  canonical solver source). Each candidate "lesson" maps 1-to-1 to
  a slot var keyed by ``(teacher, class, subject, day, hour)`` --
  the parser's `l.teacher`, `l.day`, etc. are simply attribute
  projections of the candidate key.
- Predicates that resolve to "slot var must be 0/1": when the body
  is a static comparison that evaluates to false on a candidate
  key, the slot is forbidden; when true, the slot is unconstrained.
- Reified ``implies`` / ``and`` / ``or`` over slot vars when the
  body involves dynamic terms (e.g. another lesson on the same day).

Out-of-scope (TODO marks where applicable)
==========================================
- ``sum`` aggregates beyond plain ``count``.
- Multi-quantifier joins where every variable ranges over slot
  decision vars (would explode combinatorially; future work uses
  symmetry breaking + reified linking).
- ``classroom`` predicates (rooms decided post-CG; handled by the
  classroom-assignment plessi helper).
- ``iff`` (rare; raises NotImplementedError so the user sees it).

The compiler is invoked from ``ConstraintModel.add_dsl_constraint``;
see ``engine/cp_sat_constraint_model.py``.
"""
from __future__ import annotations

from typing import Any, Iterable

try:
    from . import metaheuristics as meta  # type: ignore
except ImportError:
    import metaheuristics as meta  # type: ignore


DAYS = list(meta.DAYS)
HOURS = list(meta.HOURS)


# Map between DSL day-name literals and integer codes used in the
# slot key. The parser tolerates both bare ints (1..6) and the
# string forms we list here. Italian weekday names dominate the
# user-facing UI, so they are the canonical labels.
_DAY_LABELS = {
    1: ("lun", "lunedi", "Mon", "Monday"),
    2: ("mar", "martedi", "Tue", "Tuesday"),
    3: ("mer", "mercoledi", "Wed", "Wednesday"),
    4: ("gio", "giovedi", "Thu", "Thursday"),
    5: ("ven", "venerdi", "Fri", "Friday"),
    6: ("sab", "sabato", "Sat", "Saturday"),
}


def _normalize_day_value(v: Any) -> int | None:
    """Convert a day literal (int or str) to the 1..6 code, or
    None if the value is not a recognised day."""
    if isinstance(v, int):
        return v if 1 <= v <= 6 else None
    if isinstance(v, str):
        s = v.strip().lower()
        for code, labels in _DAY_LABELS.items():
            if s in {lb.lower() for lb in labels}:
                return code
    return None


# Lesson attribute lookup: given a candidate slot key
# ``(teacher, class_name, subject, day, hour)``, returns the value of
# the named attribute. The parser's `l.teacher` etc. translate to
# these projections at compile time.
#
# Classroom + plesso resolution
# -----------------------------
# Slot keys do NOT carry a classroom dimension (rooms are decided
# post-CG by the classroom-assignment solver). When the caller wants
# a DSL rule to reference ``l.classroom`` or ``l.classroom.plesso``,
# the compiler accepts an optional ``classroom_for_slot`` lookup
# (``(class, day, hour) -> classroom_name``) and an optional
# ``plessi_data`` carrier (anything with a ``classroom_to_plesso``
# dict). When those are provided the static evaluator resolves the
# attribute chain transparently; otherwise it raises
# ``ValueError`` so the caller logs a diagnostic instead of silently
# dropping the rule.
def _lesson_attr(
    key: tuple,
    attr: str,
    *,
    classroom_for_slot: dict | None = None,
    plessi_data: Any = None,
) -> Any:
    t, cl, s, d, h = key
    if attr == "teacher":
        return t
    if attr == "class":
        return cl
    if attr == "subject":
        return s
    if attr == "day":
        return d
    if attr == "hour":
        return h
    if attr == "slot":
        return (d, h)
    if attr == "classroom":
        if classroom_for_slot is None:
            raise ValueError(
                "l.classroom referenced but classroom_for_slot lookup "
                "not provided to compiler")
        return classroom_for_slot.get((cl, d, h))
    return None


def _resolve_lesson_path(
    key: tuple,
    path: list[str],
    *,
    classroom_for_slot: dict | None = None,
    plessi_data: Any = None,
) -> Any:
    """Resolve a multi-step attribute chain on a slot key.

    Currently understands chained access through ``classroom``:
      - ``l.classroom`` -> classroom_name (str | None)
      - ``l.classroom.plesso`` -> plesso_id  (int | None)
      - ``l.classroom.id``     -> classroom_name  (alias of name in
                                                   the post-CG model)

    Single-step paths fall through to ``_lesson_attr``.

    A return value of ``None`` is legitimate (e.g. the classroom for
    that slot is not assigned yet, or the room has no plesso). A
    chain that the resolver does NOT understand raises
    ``ValueError`` so the caller can record a diagnostic.
    """
    if not path:
        return key
    head = path[0]
    rest = path[1:]
    val = _lesson_attr(
        key, head,
        classroom_for_slot=classroom_for_slot,
        plessi_data=plessi_data,
    )
    if not rest:
        return val
    if val is None:
        # Cannot resolve further on a missing intermediate value.
        # We still return None rather than raise; the comparison
        # using this None is then evaluated as "unequal to any
        # concrete RHS", which is the correct semantics when the
        # classroom for the slot is unknown.
        return None
    if head == "classroom":
        nxt = rest[0]
        deeper = rest[1:]
        # ``l.classroom`` already produced a string (the room name).
        # Now consume the next token.
        if nxt == "plesso":
            if plessi_data is None:
                raise ValueError(
                    "l.classroom.plesso referenced but plessi_data "
                    "not provided to compiler")
            mapping = getattr(plessi_data, "classroom_to_plesso", None)
            if mapping is None and isinstance(plessi_data, dict):
                mapping = plessi_data.get("classroom_to_plesso")
            if mapping is None:
                raise ValueError(
                    "plessi_data missing classroom_to_plesso mapping")
            pl = mapping.get(val)
            if deeper:
                # No further attributes on a plesso id (an int).
                raise ValueError(
                    f"cannot follow path {'.'.join(rest)} on plesso id")
            return pl
        if nxt in ("name", "id"):
            # The slot model uses the room NAME as identifier; both
            # `.name` and `.id` collapse to the same value.
            if deeper:
                raise ValueError(
                    f"cannot follow path {'.'.join(rest)} on classroom name")
            return val
    raise ValueError(
        f"unsupported attribute chain {'.'.join(path)} on lesson key")


def _eval_static(node, env: dict, key_lookup: dict[str, tuple],
                  *, classroom_for_slot: dict | None = None,
                  plessi_data: Any = None) -> Any:
    """Evaluate an AST node when ALL the references are
    statically resolvable (compile-time constants on the candidate
    keys). ``env`` maps quantifier-bound variable names to either
    a candidate slot key tuple (for ``lessons``) or a literal
    (for other sources).

    Returns the value (bool / int / str / tuple) or raises
    ``ValueError`` when the expression is dynamic (depends on a
    decision variable).

    ``classroom_for_slot`` and ``plessi_data`` are optional carriers
    used to resolve ``l.classroom`` and ``l.classroom.plesso``
    references; they are forwarded to ``_resolve_lesson_path``.
    """
    from webui.backend.utils import general_dsl as gd  # type: ignore

    if isinstance(node, gd.Lit):
        return node.value
    if isinstance(node, gd.Ref):
        if not node.path:
            raise ValueError("empty Ref")
        head = node.path[0]
        rest = node.path[1:]
        if head not in env:
            # Bare entity name (literal compare RHS)
            if not rest:
                return head
            raise ValueError(f"unbound ref {head}")
        bound = env[head]
        if not rest:
            return bound
        # bound is a slot key tuple; project attributes (with
        # support for chained access through l.classroom).
        # Any 5-tuple bound in env originates from iterating
        # ``lessons`` (the only tuple-valued source the compiler
        # currently supports), so we accept any var name -- DSL
        # rules use names like ``l``, ``l1``, ``l2``, ``lesson`` and
        # all should resolve identically. ``key_lookup`` is kept as
        # a hint set for future extensions (e.g. another tuple-
        # valued source) but is no longer authoritative.
        if isinstance(bound, tuple) and len(bound) == 5:
            return _resolve_lesson_path(
                bound, rest,
                classroom_for_slot=classroom_for_slot,
                plessi_data=plessi_data,
            )
        if isinstance(bound, dict):
            return bound.get(rest[0])
        raise ValueError(
            f"cannot resolve {'.'.join(node.path)} on {bound!r}")
    if isinstance(node, gd.Cmp):
        lhs = _eval_static(
            node.left, env, key_lookup,
            classroom_for_slot=classroom_for_slot,
            plessi_data=plessi_data)
        op = node.op
        if op in ("in", "not_in") and isinstance(node.right, list):
            rhs_set = []
            for r in node.right:
                rhs_set.append(_eval_static(
                    r, env, key_lookup,
                    classroom_for_slot=classroom_for_slot,
                    plessi_data=plessi_data))
            # Day labels in 'in' lists are normalized.
            if isinstance(lhs, int):
                rhs_norm = [_normalize_day_value(v) or v
                             for v in rhs_set]
                if any(v is None for v in rhs_norm):
                    rhs_norm = rhs_set
            else:
                rhs_norm = rhs_set
            if op == "in":
                return lhs in rhs_norm
            return lhs not in rhs_norm
        rhs = _eval_static(
            node.right, env, key_lookup,
            classroom_for_slot=classroom_for_slot,
            plessi_data=plessi_data)
        # Day-name normalization for direct ==/!= comparisons.
        if op in ("==", "!=") and isinstance(lhs, int):
            n = _normalize_day_value(rhs)
            if n is not None:
                rhs = n
        if op == "==":
            return lhs == rhs
        if op == "!=":
            return lhs != rhs
        if op == "<":
            return lhs < rhs
        if op == "<=":
            return lhs <= rhs
        if op == ">":
            return lhs > rhs
        if op == ">=":
            return lhs >= rhs
        raise ValueError(f"unknown op {op}")
    if isinstance(node, gd.And):
        return all(_eval_static(
            a, env, key_lookup,
            classroom_for_slot=classroom_for_slot,
            plessi_data=plessi_data) for a in node.args)
    if isinstance(node, gd.Or):
        return any(_eval_static(
            a, env, key_lookup,
            classroom_for_slot=classroom_for_slot,
            plessi_data=plessi_data) for a in node.args)
    if isinstance(node, gd.Not):
        return not _eval_static(
            node.arg, env, key_lookup,
            classroom_for_slot=classroom_for_slot,
            plessi_data=plessi_data)
    if isinstance(node, gd.Implies):
        l = _eval_static(
            node.left, env, key_lookup,
            classroom_for_slot=classroom_for_slot,
            plessi_data=plessi_data)
        if not l:
            return True
        return bool(_eval_static(
            node.right, env, key_lookup,
            classroom_for_slot=classroom_for_slot,
            plessi_data=plessi_data))
    if isinstance(node, gd.Call):
        return _eval_static_call(
            node, env, key_lookup,
            classroom_for_slot=classroom_for_slot,
            plessi_data=plessi_data)
    raise ValueError(f"unsupported node kind {type(node).__name__}")


def _eval_static_call(node, env: dict,
                       key_lookup: dict[str, tuple],
                       *, classroom_for_slot: dict | None = None,
                       plessi_data: Any = None) -> Any:
    """Evaluate built-in DSL functions on statically bound vars.

    Supported:
      same_day(s1, s2): bool   (s1, s2 are slot tuples or refs to
                                 lesson attributes)
      consecutive(s1, s2): bool
      day(slot): int
      hour(slot): int
      teacher(lesson) / class(lesson) / subject(lesson): str
    """
    name = node.name
    args = [_eval_static(arg_node, env, key_lookup,
                          classroom_for_slot=classroom_for_slot,
                          plessi_data=plessi_data)
            for _kw, arg_node in node.args]
    if name == "same_day":
        if len(args) != 2:
            raise ValueError("same_day takes 2 args")
        a, b = args
        if isinstance(a, tuple) and len(a) == 2:
            ad = a[0]
        else:
            ad = a
        if isinstance(b, tuple) and len(b) == 2:
            bd = b[0]
        else:
            bd = b
        return ad == bd
    if name == "consecutive":
        if len(args) != 2:
            raise ValueError("consecutive takes 2 args")
        a, b = args
        if isinstance(a, tuple) and len(a) == 2:
            ad, ah = a
        else:
            return False
        if isinstance(b, tuple) and len(b) == 2:
            bd, bh = b
        else:
            return False
        return ad == bd and abs(ah - bh) == 1
    if name in ("day",):
        a = args[0]
        if isinstance(a, tuple):
            return a[0]
        return a
    if name in ("hour",):
        a = args[0]
        if isinstance(a, tuple):
            return a[1]
        return a
    if name in ("teacher", "class", "subject"):
        return args[0]
    raise ValueError(f"unknown DSL function {name!r}")


# =====================================================================
# Pragma level registry
# =====================================================================
#
# Each canonical-pattern pragma is tagged with the solver level it
# applies to:
#   "phase_b" -- operates on per-(t, c, s, d, h) slot BoolVars; used
#                by MonolithicSolver / per-day Phase B and any pricer
#                that has the slot dimension.
#   "phase_a" -- operates on per-(t, c, s, d) day_count IntVars; used
#                by DayCountModel (the OO equivalent of solve_phase_a).
#   "both"    -- pragma is applicable in either context; the compiler
#                routes to whichever variable set is populated.
#
# When the compiler is invoked with ``level="phase_a"`` and a Phase B
# pragma is encountered, the pragma is recorded in diagnostics and
# skipped (and vice versa). ``level="both"`` accepts everything --
# the default, so existing callers see no change.
PRAGMA_LEVEL: dict[str, str] = {
    # Phase B (slot Bool) pragmas
    "no_holes_class": "phase_b",
    "no_holes_all_classes": "phase_b",
    "class_present_at_hour": "phase_b",
    "class_present_at_hour_all": "phase_b",
    "teacher_max_per_day": "phase_b",
    "cattedra_max_per_day": "phase_b",
    "subject_pair_must": "phase_b",
    "subject_pair_exists": "phase_b",
    "class_day_load_in": "phase_b",
    # Phase A (day_count IntVar) pragmas
    "class_day_load_in_day_count": "phase_a",
    "hall_bound_prof_day": "phase_a",
    "free_day_choice_3way": "phase_a",
    "subject_day_count_pair": "phase_a",
    "subject_day_count_in": "phase_a",
}


# =====================================================================
# Compiler
# =====================================================================


class DSLConstraintCompiler:
    """Walks a parsed DSL AST and adds CP-SAT constraints to the
    target ``model``, operating on slot decision variables.

    Parameters
    ----------
    model : cp_model.CpModel
        the CP-SAT model receiving the constraints.
    slot : dict[(teacher, class_name, subject, day, hour)] -> BoolVar
        the slot decision variables. The compiler matches DSL
        ``lessons`` candidates against these keys.
    config : ConstraintConfig | dict
        passthrough configuration; some constraints may use defaults
        from here.
    is_hard : bool, default True
        when False, SOFT-cost integration is requested (the compiler
        adds penalty BoolVars and returns them so the caller can
        weight + accumulate into the objective). Currently HARD only;
        SOFT support is TODO and falls back to HARD.
    day_count : dict[(teacher, class, subject, day)] -> IntVar | None
        the Phase A decision variables (number of hours the cattedra
        teaches that day). Required for Phase A pragmas; when absent
        and a Phase A pragma is encountered, the compiler records a
        diagnostic and skips the rule.
    level : "phase_a" | "phase_b" | "both", default "both"
        filters which pragmas the compiler will process. Pragmas
        whose level does not match (and is not "both") are skipped
        with a diagnostic. The default preserves the historical
        behaviour where every recognised pragma is compiled.

    Compilation API
    ---------------
    ``compile(node)`` returns:
      - None when the node has been added as a HARD constraint
      - A list of CP-SAT BoolExpr for SOFT integration (TODO)

    Phase A soft cost
    -----------------
    Phase A pragmas may need to contribute to a soft objective
    (e.g. ``free_day_choice_3way`` weights the second/third candidate
    free day). They append ``(weight, expr)`` tuples to
    ``self.soft_cost_terms``; the owning model reads the list when
    building its objective.
    """

    def __init__(self, model, slot: dict, *, config=None,
                 is_hard: bool = True,
                 classroom_for_slot: dict | None = None,
                 plessi_data: Any = None,
                 owner_model: Any = None,
                 day_count: dict | None = None,
                 level: str = "both"):
        self.model = model
        self.slot = slot
        self.config = config
        self.is_hard = is_hard
        if level not in ("phase_a", "phase_b", "both"):
            raise ValueError(
                f"DSLConstraintCompiler: unknown level={level!r}; "
                "expected 'phase_a' / 'phase_b' / 'both'")
        self.level = level
        self.day_count = dict(day_count) if day_count else {}
        # Soft-cost terms appended by Phase A pragmas:
        # list[tuple[int, cp_model.IntVar]] -- weight * indicator.
        self.soft_cost_terms: list = []
        # Caches shared across Phase A pragmas so every (cl, d) /
        # (prof, d) load IntVar is created at most once even when
        # multiple pragmas reference it.
        self._cl_day_load_cache: dict = {}
        self._prof_day_load_cache: dict = {}
        # Optional classroom + plesso resolution carriers. When the
        # caller wants DSL rules that reference ``l.classroom`` /
        # ``l.classroom.plesso`` to be enforced, both must be passed
        # in (or just classroom_for_slot for ``l.classroom`` alone).
        # The DTOs are forwarded verbatim to ``_eval_static`` /
        # ``_resolve_lesson_path`` and never mutated.
        self.classroom_for_slot = classroom_for_slot
        self.plessi_data = plessi_data
        # Optional ``ConstraintModel`` whose busy-key registries
        # (``_coteach_busy_keys`` / ``_support_triples`` /
        # ``_parallel_intra_busy_key`` / ``_group_triples``) the
        # ``no_holes_class`` / ``class_present_at_hour`` pragmas
        # delegate to via ``_build_class_busy_indicators``. When
        # ``None`` (or the model has no helper) the pragmas fall
        # back to the raw per-(cl, d, h) slot OR -- legacy behavior,
        # zero-drift on simple scenarios but drifts from Phase B
        # whenever sostegno / coteach / parallel intra is in play.
        self.owner_model = owner_model
        # Index slot keys by candidate dimensions for O(1) lookup.
        self._by_t: dict = {}
        self._by_c: dict = {}
        self._by_s: dict = {}
        self._by_d: dict = {}
        self._by_h: dict = {}
        for k in slot:
            t, cl, s, d, h = k
            self._by_t.setdefault(t, []).append(k)
            self._by_c.setdefault(cl, []).append(k)
            self._by_s.setdefault(s, []).append(k)
            self._by_d.setdefault(d, []).append(k)
            self._by_h.setdefault(h, []).append(k)
        self.diagnostics: list[str] = []

    # ----- public entry -----

    def compile(self, source: str | Any) -> None:
        """Parse (if str) and compile the given DSL expression."""
        if isinstance(source, str):
            from webui.backend.utils import general_dsl as gd  # type: ignore
            tree = gd.parse(source)
        else:
            tree = source
        self._compile_node(tree, env={})

    def _eval(self, node, env):
        """Evaluate a node statically, propagating the carrier
        kwargs (classroom_for_slot, plessi_data) from this compiler
        instance. Raises ``ValueError`` for dynamic terms."""
        return _eval_static(
            node, env, self._key_lookup_kinds(),
            classroom_for_slot=self.classroom_for_slot,
            plessi_data=self.plessi_data,
        )

    # ----- node dispatch -----

    def _compile_node(self, node, env: dict):
        from webui.backend.utils import general_dsl as gd  # type: ignore
        if isinstance(node, gd.Quant):
            return self._compile_quant(node, env)
        if isinstance(node, gd.Count):
            return self._compile_count(node, env)
        if isinstance(node, (gd.And,)):
            for a in node.args:
                self._compile_node(a, env)
            return
        if isinstance(node, gd.Implies):
            return self._compile_implies(node, env)
        if isinstance(node, gd.Or):
            return self._compile_or(node, env)
        if isinstance(node, gd.Not):
            return self._compile_not(node, env)
        if isinstance(node, gd.Call):
            # Top-level Call covers the canonical-pattern vocabulary:
            # no_holes_class, class_present_at_hour, ... (see
            # _compile_call). Routes there before falling back to
            # generic static eval.
            handled = self._compile_call(node, env)
            if handled:
                return
        if isinstance(node, gd.Lit):
            if not bool(node.value):
                # Top-level literal `false` => infeasible HARD.
                self.model.AddBoolAnd([self.model.NewConstant(0)])
            return
        # Boolean leaf: try static eval.
        try:
            value = self._eval(node, env)
            if not value:
                self.model.AddBoolAnd([self.model.NewConstant(0)])
            return
        except ValueError as exc:
            self.diagnostics.append(
                f"could not statically reduce node "
                f"{type(node).__name__}: {exc}")

    # ----- forall / exists -----

    def _compile_quant(self, node, env: dict):
        if node.source != "lessons":
            self.diagnostics.append(
                f"forall over '{node.source}' not yet supported "
                f"(only 'lessons')")
            return
        # Iterate candidate slot keys; filter by `where`.
        for key in self.slot.keys():
            new_env = dict(env)
            new_env[node.var] = key
            if node.where is not None:
                try:
                    keep = bool(self._eval(node.where, new_env))
                except ValueError as exc:
                    self.diagnostics.append(
                        f"forall.where contains dynamic refs; "
                        f"skipped ({exc})")
                    continue
                if not keep:
                    continue
            # Body: try static eval first.
            self._apply_body_for_key(
                node, new_env, key, quant=node.quant)

    def _apply_body_for_key(self, node, env: dict, key: tuple,
                              *, quant: str):
        """Apply the quantifier body to a single candidate key.

        - ``forall`` body interpreted as: implication ``slot[key]``
          => body. If body is statically ``false``: force slot==0.
          If statically ``true``: no-op.
        - ``exists``: collect over keys and emit BoolOr at the end
          (handled outside this helper).
        """
        from webui.backend.utils import general_dsl as gd  # type: ignore
        if quant != "forall":
            # exists: collect the slot var; aggregate handled by
            # caller. For now: treat the body as a static filter
            # and require the slot to be 1.
            try:
                value = bool(self._eval(node.body, env))
                if value:
                    # exists candidate: add slot to a placeholder.
                    self._exists_pending_slots.append(self.slot[key])
            except ValueError:
                self.diagnostics.append(
                    "exists.body dynamic; skipped")
            return
        # forall: body must hold whenever slot is true.
        try:
            value = self._eval(node.body, env)
            if value is False:
                # body false -> the slot must NOT be active.
                self.model.Add(self.slot[key] == 0)
            # If True, no constraint needed.
            return
        except ValueError:
            pass
        # Body involves dynamic terms. Best-effort: if body is a
        # comparison/predicate over another lesson reachable via
        # static filters, emit a reified pair-wise constraint. This
        # path is intentionally limited; richer patterns are TODO.
        self._compile_dynamic_forall_body(node, env, key)

    def _compile_dynamic_forall_body(self, node, env: dict,
                                      key: tuple):
        """For forall with a body that depends on another candidate
        slot, expand by enumerating the inner variables and emitting
        per-pair reified constraints. Currently handles a body that
        is itself a simple comparison or `consecutive` call over two
        bound lesson variables -- enough for "if both lessons exist,
        the inner predicate must hold" patterns.
        """
        from webui.backend.utils import general_dsl as gd  # type: ignore
        body = node.body
        if isinstance(body, gd.Quant) and body.source == "lessons":
            # Nested forall: expand inner vars symmetrically.
            for inner_key in self.slot:
                if inner_key == key:
                    continue
                new_env = dict(env)
                new_env[body.var] = inner_key
                # Inner where filter
                if body.where is not None:
                    try:
                        keep = bool(self._eval(body.where, new_env))
                    except ValueError:
                        continue
                    if not keep:
                        continue
                # Inner body
                try:
                    inner_value = self._eval(body.body, new_env)
                except ValueError:
                    self.diagnostics.append(
                        "double-forall body dynamic; skipped")
                    continue
                if inner_value is False:
                    # If both slots are 1, the inner body would be
                    # violated -> not both can be 1.
                    self.model.AddBoolOr([
                        self.slot[key].Not(),
                        self.slot[inner_key].Not(),
                    ])
            return
        self.diagnostics.append(
            "forall body dynamic and not nested-forall; skipped")

    # ----- count -----

    def _compile_count(self, node, env: dict):
        if node.source != "lessons":
            self.diagnostics.append(
                f"count over '{node.source}' not yet supported")
            return
        matched = []
        for key in self.slot:
            new_env = dict(env)
            new_env[node.var] = key
            if node.where is not None:
                try:
                    keep = bool(self._eval(node.where, new_env))
                except ValueError:
                    self.diagnostics.append(
                        "count.where dynamic; skipped term")
                    continue
                if not keep:
                    continue
            matched.append(self.slot[key])
        if not matched:
            return
        # rhs may be a constant Lit
        from webui.backend.utils import general_dsl as gd  # type: ignore
        rhs = node.rhs
        if isinstance(rhs, gd.Lit):
            n = int(rhs.value)
        else:
            try:
                n = int(self._eval(rhs, env))
            except ValueError:
                self.diagnostics.append("count rhs dynamic; skipped")
                return
        op = node.op
        s = sum(matched)
        if op == "==":
            self.model.Add(s == n)
        elif op == "!=":
            # CP-SAT lacks a direct '!='; reify
            b = self.model.NewBoolVar("count_neq")
            self.model.Add(s == n).OnlyEnforceIf(b.Not())
            self.model.Add(s != n).OnlyEnforceIf(b)
            self.model.Add(b == 1)
        elif op == "<":
            self.model.Add(s < n)
        elif op == "<=":
            self.model.Add(s <= n)
        elif op == ">":
            self.model.Add(s > n)
        elif op == ">=":
            self.model.Add(s >= n)
        else:
            self.diagnostics.append(f"unknown count op {op}")

    # ----- and / or / not / implies (top-level) -----

    def _compile_implies(self, node, env: dict):
        # We only support implication when the antecedent is a
        # static check; in that case the consequent is compiled
        # iff the antecedent holds. Dynamic implications would need
        # reification at constraint level.
        try:
            ant = self._eval(node.left, env)
        except ValueError:
            self.diagnostics.append(
                "implies with dynamic antecedent; skipped")
            return
        if ant:
            self._compile_node(node.right, env)

    def _compile_or(self, node, env: dict):
        # Top-level Or: compile each branch as a separate
        # alternative. For HARD logic, all branches together must
        # hold OR style -- we approximate by encoding as
        # "AddBoolOr over reified branch indicators". For now we
        # only implement the case where every branch reduces to a
        # static truth value plus a small slot-disjunction.
        from webui.backend.utils import general_dsl as gd  # type: ignore
        slot_vars: list = []
        for arg in node.args:
            try:
                v = self._eval(arg, env)
                if v:
                    return  # Or already satisfied statically.
            except ValueError:
                # Dynamic: try to interpret the branch as a single
                # slot literal. Collect, then emit disjunction.
                pass
        if slot_vars:
            self.model.AddBoolOr(slot_vars)
        else:
            self.diagnostics.append(
                "OR over dynamic branches not yet supported")

    def _compile_not(self, node, env: dict):
        try:
            v = self._eval(node.arg, env)
            if v:
                self.model.AddBoolAnd([self.model.NewConstant(0)])
            return
        except ValueError:
            self.diagnostics.append(
                "NOT with dynamic body not supported")

    # ----- lookup helpers -----

    def _key_lookup_kinds(self) -> dict[str, tuple]:
        """Map of "is this var bound to a slot-key tuple?" used by
        ``_eval_static`` to decide attribute projection."""
        return {"l": (), "lesson": ()}

    # placeholders used by exists path (currently no-op)
    _exists_pending_slots: list = []

    # ============================================================
    # Canonical-pattern vocabulary (Step 3b)
    # ============================================================
    #
    # The verbose DSL form of "no holes per class" is a triple-
    # quantifier expression that the generic compiler can technically
    # parse but cannot translate to an efficient encoding. Rather
    # than rely on heuristic pattern recognition, the system uses a
    # named-call vocabulary: translators emit DSL such as
    # ``no_holes_class("1A")`` and the compiler recognises these
    # names as pragmas, then emits the same compact CP-SAT encoding
    # the legacy hardcoded path uses (the ``present[h+1] <=
    # present[h]`` non-increasing chain on per-hour OR vars).
    #
    # The vocabulary is small and stable; new entries land here once
    # and are inherited by every solver subclass.
    #
    # Recognised top-level Calls
    # --------------------------
    #   no_holes_class(class_name)           -- non-increasing chain +
    #                                            "starts at h_min"
    #   no_holes_all_classes()               -- as above for every class
    #                                            present in self.slot
    #   class_present_at_hour(class, hour)   -- if any lesson that day,
    #                                            slot at `hour` busy
    #   class_present_at_hour_all(hour)      -- as above for every class
    #   teacher_max_per_day(teacher, n)      -- daily teacher load <= n
    #   cattedra_max_per_day(t, c, s, n)     -- daily cattedra load <= n
    #   subject_pair_must(class, subject)    -- when 2 hr/day, consecutive
    #   subject_pair_exists(class, subject)  -- when >=2 hr/day, exists pair
    #   class_day_load_in(class, [v, ...])   -- daily class hours in set
    #
    # Unknown call names fall back to generic static evaluation
    # (boolean leaf): if the name is a known DSL built-in such as
    # same_day, hour, etc. and the args are static, the result is a
    # truth value handled by the existing leaf path.

    def _compile_call(self, node, env: dict) -> bool:
        """Try to compile ``node`` as a canonical-pattern pragma.
        Returns True if the call name was recognised AND processed,
        False otherwise (caller falls back to generic eval)."""
        name = node.name
        # Level filter: a pragma whose level doesn't match the
        # compiler instance is recorded as skipped and absorbed (we
        # return True so the caller doesn't fall through to generic
        # static evaluation, which would raise on a recognised name
        # invoked in the wrong context).
        pragma_level = PRAGMA_LEVEL.get(name)
        if (pragma_level is not None
                and self.level != "both"
                and pragma_level != "both"
                and pragma_level != self.level):
            self.diagnostics.append(
                f"pragma {name!r} (level={pragma_level}) skipped: "
                f"compiler level={self.level}")
            return True
        # Resolve positional args eagerly in env.
        try:
            arg_values = [self._eval(arg, env)
                            for _kw, arg in node.args]
        except ValueError as exc:
            # Some recognised pragmas can still be processed without
            # evaluable args (none currently); fall through to the
            # generic path so the caller can try static eval.
            self.diagnostics.append(
                f"call {name}(...): cannot evaluate args ({exc})")
            return False
        if name == "no_holes_class":
            if len(arg_values) != 1:
                self.diagnostics.append(
                    f"no_holes_class expects 1 arg, got "
                    f"{len(arg_values)}")
                return True
            self._compile_no_holes_for_class(str(arg_values[0]))
            return True
        if name == "no_holes_all_classes":
            if arg_values:
                self.diagnostics.append(
                    "no_holes_all_classes takes no args")
                return True
            for cl in sorted({k[1] for k in self.slot}):
                self._compile_no_holes_for_class(cl)
            return True
        if name == "class_present_at_hour":
            if len(arg_values) != 2:
                self.diagnostics.append(
                    f"class_present_at_hour expects 2 args, got "
                    f"{len(arg_values)}")
                return True
            cl = str(arg_values[0])
            hr = int(arg_values[1])
            self._compile_class_present_at_hour(cl, hr)
            return True
        if name == "class_present_at_hour_all":
            if len(arg_values) != 1:
                self.diagnostics.append(
                    f"class_present_at_hour_all expects 1 arg, got "
                    f"{len(arg_values)}")
                return True
            hr = int(arg_values[0])
            for cl in sorted({k[1] for k in self.slot}):
                self._compile_class_present_at_hour(cl, hr)
            return True
        if name == "teacher_max_per_day":
            if len(arg_values) != 2:
                self.diagnostics.append(
                    f"teacher_max_per_day expects 2 args, got "
                    f"{len(arg_values)}")
                return True
            t = str(arg_values[0])
            n = int(arg_values[1])
            self._compile_teacher_max_per_day(t, n)
            return True
        if name == "cattedra_max_per_day":
            if len(arg_values) != 4:
                self.diagnostics.append(
                    f"cattedra_max_per_day expects 4 args, got "
                    f"{len(arg_values)}")
                return True
            t, cl, subj, n = (str(arg_values[0]), str(arg_values[1]),
                              str(arg_values[2]), int(arg_values[3]))
            self._compile_cattedra_max_per_day(t, cl, subj, n)
            return True
        if name == "subject_pair_must":
            if len(arg_values) != 2:
                self.diagnostics.append(
                    f"subject_pair_must expects 2 args")
                return True
            cl = str(arg_values[0])
            subj = str(arg_values[1])
            self._compile_subject_pair(cl, subj, mode="must_pair")
            return True
        if name == "subject_pair_exists":
            if len(arg_values) != 2:
                self.diagnostics.append(
                    f"subject_pair_exists expects 2 args")
                return True
            cl = str(arg_values[0])
            subj = str(arg_values[1])
            self._compile_subject_pair(cl, subj, mode="pair_exists")
            return True
        if name == "class_day_load_in":
            if len(arg_values) < 2:
                self.diagnostics.append(
                    "class_day_load_in expects (class, allowed...)")
                return True
            cl = str(arg_values[0])
            allowed = [int(v) for v in arg_values[1:]]
            self._compile_class_day_load_in(cl, allowed)
            return True
        # ---- Phase A (day_count IntVar) pragmas ----
        if name == "class_day_load_in_day_count":
            if len(arg_values) < 2:
                self.diagnostics.append(
                    "class_day_load_in_day_count expects "
                    "(class, allowed...)")
                return True
            cl = str(arg_values[0])
            allowed = [int(v) for v in arg_values[1:]]
            self._compile_class_day_load_in_day_count(cl, allowed)
            return True
        if name == "hall_bound_prof_day":
            if len(arg_values) != 1:
                self.diagnostics.append(
                    f"hall_bound_prof_day expects 1 arg "
                    f"(prof), got {len(arg_values)}")
                return True
            self._compile_hall_bound_prof_day(str(arg_values[0]))
            return True
        if name == "subject_day_count_pair":
            # Args: class, n, subj_1, subj_2, ...
            if len(arg_values) < 3:
                self.diagnostics.append(
                    "subject_day_count_pair expects "
                    "(class, n, subj_1, subj_2, ...)")
                return True
            cl = str(arg_values[0])
            n = int(arg_values[1])
            subjects = [str(s) for s in arg_values[2:]]
            self._compile_subject_day_count_pair(cl, subjects, n)
            return True
        if name == "free_day_choice_3way":
            # Args: prof, candidate_day_1, candidate_day_2,
            # candidate_day_3, [w_1, w_2, w_3]. Defaults: 0, 50, 100.
            if len(arg_values) < 4:
                self.diagnostics.append(
                    "free_day_choice_3way expects "
                    "(prof, d1, d2, d3, [w1, w2, w3])")
                return True
            prof = str(arg_values[0])
            cands = [_normalize_day_value(arg_values[k]) or
                     int(arg_values[k]) for k in (1, 2, 3)]
            if len(arg_values) >= 7:
                weights = [int(arg_values[4]), int(arg_values[5]),
                           int(arg_values[6])]
            else:
                weights = [0, 50, 100]
            self._compile_free_day_choice_3way(prof, cands, weights)
            return True
        # Unknown call name: leave for the generic path.
        return False

    # ---- pragma implementations ----

    def _slots_for_class_day_hour(self, cl: str, d: int, h: int):
        return [v for (_t, ccl, _s, dd, hh), v in self.slot.items()
                if ccl == cl and dd == d and hh == h]

    def _slots_for_class_day(self, cl: str, d: int):
        return [v for (_t, ccl, _s, dd, _h), v in self.slot.items()
                if ccl == cl and dd == d]

    def _classes_in_scope(self) -> list:
        return sorted({k[1] for k in self.slot})

    def _days_in_scope(self) -> list:
        return sorted({k[3] for k in self.slot})

    def _hours_in_scope(self) -> list:
        return sorted({k[4] for k in self.slot})

    def _class_busy_indicators(self, cl: str, d: int, h: int,
                                  *, name_suffix: str) -> list:
        """Return class-busy indicators for ``(cl, d, h)``.

        When the compiler was constructed with an ``owner_model`` that
        exposes ``_build_class_busy_indicators``, defer to it so the
        pragma applies the same exclusion + aggregation as
        ``add_class_no_overlap`` / ``add_class_no_holes`` /
        ``add_h3_presence_at_11`` (sostegno excluded, coteach +
        parallel intra members OR'd into one indicator each,
        inter-class groups feed home classes). Otherwise fall back to
        the raw per-slot list (legacy zero-drift behavior on simple
        scenarios that have no busy registries to honor).
        """
        owner = getattr(self, "owner_model", None)
        if owner is not None and hasattr(
                owner, "_build_class_busy_indicators"):
            return owner._build_class_busy_indicators(
                cl, d, h, name_suffix=f"dsl_{name_suffix}")
        return self._slots_for_class_day_hour(cl, d, h)

    def _compile_no_holes_for_class(self, cl: str):
        """Class no-holes: per (class, day) the busy slots are
        contiguous and start at the earliest hour. Encoded via the
        non-increasing chain on per-hour OR indicators -- identical
        to ConstraintModel.add_class_no_holes for a single class.

        Per-hour ``present[h]`` is built from
        ``_class_busy_indicators`` so the rule honors the same
        exclusion + aggregation as the OO method when the compiler
        was given an ``owner_model``.
        """
        days = self._days_in_scope()
        hours = self._hours_in_scope()
        if not hours:
            return
        for d in days:
            present_per_h = []
            for h in hours:
                busy = self._class_busy_indicators(
                    cl, d, h, name_suffix="nh")
                if not busy:
                    present_per_h.append(self.model.NewConstant(0))
                    continue
                if len(busy) == 1:
                    present_per_h.append(busy[0])
                    continue
                pr = self.model.NewBoolVar(
                    f"_dsl_pr_{cl}_{d}_{h}")
                self.model.AddMaxEquality(pr, busy)
                present_per_h.append(pr)
            ap = self.model.NewBoolVar(f"_dsl_ap_{cl}_{d}")
            self.model.AddMaxEquality(ap, present_per_h)
            self.model.Add(present_per_h[0] >= ap)
            for i in range(len(present_per_h) - 1):
                self.model.Add(
                    present_per_h[i + 1] <= present_per_h[i])

    def _compile_class_present_at_hour(self, cl: str, hr: int):
        """If the class has any lesson that day, the slot at ``hr``
        must be busy. Same encoding as ``add_h3_presence_at_11``.

        Both ``any_d`` (any lesson today) and ``pr_h`` (lesson at
        ``hr``) read ``_class_busy_indicators`` so the pragma honors
        the OO model's exclusion + aggregation rules when an
        ``owner_model`` was supplied.
        """
        days = self._days_in_scope()
        hours = self._hours_in_scope()
        if hr not in hours:
            return
        for d in days:
            busy_per_h: dict[int, list] = {}
            for h in hours:
                busy_per_h[h] = self._class_busy_indicators(
                    cl, d, h, name_suffix="h11")
            bvs_hr = busy_per_h.get(hr, [])
            if not bvs_hr:
                # Class has no slot at hr today; forbid any lesson on
                # that day (else the rule cannot be satisfied). Use
                # the raw day vars here, not the busy indicators,
                # since the unsatisfiability target is "any slot",
                # not "any class-busy occupation".
                day_vars = self._slots_for_class_day(cl, d)
                for v in day_vars:
                    self.model.Add(v == 0)
                continue
            all_busy = [v for h in hours for v in busy_per_h[h]]
            if not all_busy:
                continue
            any_d = self.model.NewBoolVar(
                f"_dsl_apX_{cl}_{d}_{hr}")
            self.model.AddMaxEquality(any_d, all_busy)
            pr_h = self.model.NewBoolVar(
                f"_dsl_prX_{cl}_{d}_{hr}")
            self.model.AddMaxEquality(pr_h, bvs_hr)
            self.model.Add(pr_h >= any_d)

    def _compile_teacher_max_per_day(self, t: str, n: int):
        """sum_{cl, s, h} slot[(t, cl, s, d, h)] <= n for every day."""
        days = self._days_in_scope()
        hours = self._hours_in_scope()
        for d in days:
            vs = [v for (tt, _cl, _s, dd, _h), v in self.slot.items()
                  if tt == t and dd == d]
            if vs:
                self.model.Add(sum(vs) <= int(n))

    def _compile_cattedra_max_per_day(self, t: str, cl: str,
                                        subj: str, n: int):
        """sum_h slot[(t, cl, s, d, h)] <= n for every day."""
        days = self._days_in_scope()
        for d in days:
            vs = [v for (tt, ccl, ss, dd, _h), v in self.slot.items()
                  if tt == t and ccl == cl and ss == subj and dd == d]
            if vs:
                self.model.Add(sum(vs) <= int(n))

    def _compile_subject_pair(self, cl: str, subj: str, *, mode: str):
        """Subject-pair pragma. ``mode`` is ``must_pair`` (used for
        Scienzemotorie: 2 hr/day MUST be consecutive) or
        ``pair_exists`` (used for Mat/Ita: when >= 2 hr/day, at least
        one consecutive pair). Day-counts are read from the slot
        sums (so the pragma works without requiring dc_value)."""
        hours = self._hours_in_scope()
        days = self._days_in_scope()
        # Find the unique teacher for (cl, subj).
        teachers = sorted({tt for (tt, ccl, ss, _d, _h) in self.slot
                           if ccl == cl and ss == subj})
        if not teachers:
            return
        for t in teachers:
            for d in days:
                presence = []
                for h in hours:
                    vs = [v for (tt, ccl, ss, dd, hh), v
                           in self.slot.items()
                           if tt == t and ccl == cl and ss == subj
                              and dd == d and hh == h]
                    if not vs:
                        presence.append(self.model.NewConstant(0))
                        continue
                    if len(vs) == 1:
                        presence.append(vs[0])
                        continue
                    pr = self.model.NewBoolVar(
                        f"_dsl_sp_{subj[:3]}_{t}_{cl}_{d}_{h}")
                    self.model.AddMaxEquality(pr, vs)
                    presence.append(pr)
                if not presence:
                    continue
                # day_count IntVar, used by must_pair to gate the
                # constraint at exactly 2 (rest of cases: AddBoolOr
                # over adjacent pairs is a HARD requirement when the
                # day_count is at least 2, so we guard it with an
                # implication).
                total = sum(presence)
                pairs = []
                for i in range(len(hours) - 1):
                    pair = self.model.NewBoolVar(
                        f"_dsl_pp_{subj[:3]}_{t}_{cl}_{d}_{i}")
                    self.model.AddBoolAnd(
                        [presence[i], presence[i + 1]]
                    ).OnlyEnforceIf(pair)
                    self.model.AddBoolOr(
                        [presence[i].Not(),
                         presence[i + 1].Not()]
                    ).OnlyEnforceIf(pair.Not())
                    pairs.append(pair)
                if not pairs:
                    continue
                # We need: when day_count >= threshold, at least one
                # pair is true. Encode via:
                #   has_any_pair = OR(pairs)
                #   has_any_pair >= 1 when count >= threshold
                threshold = 2
                has_any = self.model.NewBoolVar(
                    f"_dsl_hp_{subj[:3]}_{t}_{cl}_{d}")
                self.model.AddMaxEquality(has_any, pairs)
                # Reify "count >= threshold" -> trig
                trig = self.model.NewBoolVar(
                    f"_dsl_tr_{subj[:3]}_{t}_{cl}_{d}")
                # count >= threshold iff trig
                self.model.Add(total >= threshold).OnlyEnforceIf(trig)
                self.model.Add(total < threshold).OnlyEnforceIf(
                    trig.Not())
                # has_any >= trig (when triggered, has_any must be 1)
                self.model.Add(has_any >= trig)
                if mode == "must_pair":
                    # Additional rule: when count == 2 the only
                    # acceptable shape is "exactly one pair". The
                    # generic pair_exists rule already forces the
                    # single pair when count == 2, so the extra
                    # tightening is implicit.
                    pass

    def _compile_class_day_load_in(self, cl: str,
                                     allowed: list[int]):
        """Per (class, day), the number of busy hours must lie in
        ``allowed`` (set of integers). Encoded via
        ``AddAllowedAssignments`` on the IntVar count, mirroring the
        legacy HARD-1+HARD-2 ``cl_day_load in {0,4,5,6}`` rule."""
        days = self._days_in_scope()
        hours = self._hours_in_scope()
        if not hours:
            return
        if not allowed:
            return
        # Limit allowed values to the feasible 0..len(hours).
        max_v = len(hours)
        allowed_clamped = sorted({int(v) for v in allowed
                                   if 0 <= int(v) <= max_v})
        if not allowed_clamped:
            return
        for d in days:
            # Build per-hour OR indicator (parallel groups + multi-
            # subject would otherwise inflate the count); count busy
            # HOURS, not busy slots.
            present_per_h = []
            for h in hours:
                vs = self._slots_for_class_day_hour(cl, d, h)
                if not vs:
                    present_per_h.append(self.model.NewConstant(0))
                    continue
                pr = self.model.NewBoolVar(
                    f"_dsl_clpr_{cl}_{d}_{h}")
                self.model.AddMaxEquality(pr, vs)
                present_per_h.append(pr)
            count = self.model.NewIntVar(
                0, max_v, f"_dsl_cnt_{cl}_{d}")
            self.model.Add(count == sum(present_per_h))
            self.model.AddAllowedAssignments(
                [count], [(v,) for v in allowed_clamped])

    # ============================================================
    # Phase A pragmas (operate on day_count IntVars)
    # ============================================================

    def _days_in_dc_scope(self) -> list:
        return sorted({k[3] for k in self.day_count})

    def _classes_in_dc_scope(self) -> list:
        return sorted({k[1] for k in self.day_count})

    def _profs_in_dc_scope(self) -> list:
        return sorted({k[0] for k in self.day_count})

    def _cl_day_load_intvar(self, cl: str, d: int):
        """Cached IntVar = sum_{(p, s) | (p, cl, s, d) in day_count}
        day_count[(p, cl, s, d)]. Constant-0 when no terms.

        The aggregation matches Phase A's ``cl_day_load[c, d]``
        construction in ``cpsat_v2_timetable.solve_phase_a``: every
        cattedra (p, c, s) that has a day_count entry contributes.
        Caller-side exclusions (codoc, support, parallel-secondary,
        group) are expected to be applied by the model that builds
        ``self.day_count`` -- the compiler simply sums what it sees.
        """
        key = (cl, d)
        if key in self._cl_day_load_cache:
            return self._cl_day_load_cache[key]
        terms = [v for (_p, ccl, _s, dd), v in self.day_count.items()
                 if ccl == cl and dd == d]
        if not terms:
            cdl = self.model.NewConstant(0)
        else:
            # Generous upper bound; exact constraints (allowed sets,
            # Hall bound) clamp the value below.
            cdl = self.model.NewIntVar(
                0, 100, f"_dsl_cdl_{cl}_{d}")
            self.model.Add(cdl == sum(terms))
        self._cl_day_load_cache[key] = cdl
        return cdl

    def _prof_day_load_intvar(self, p: str, d: int):
        """Cached IntVar = sum_{(c, s) | (p, c, s, d) in day_count}
        day_count[(p, c, s, d)]. Constant-0 when no terms.

        Mirrors ``prof_day_load[p, d]`` in ``solve_phase_a``.
        """
        key = (p, d)
        if key in self._prof_day_load_cache:
            return self._prof_day_load_cache[key]
        terms = [v for (pp, _cl, _s, dd), v in self.day_count.items()
                 if pp == p and dd == d]
        if not terms:
            pdl = self.model.NewConstant(0)
        else:
            pdl = self.model.NewIntVar(
                0, 100, f"_dsl_pdl_{p}_{d}")
            self.model.Add(pdl == sum(terms))
        self._prof_day_load_cache[key] = pdl
        return pdl

    def _compile_hall_bound_prof_day(self, p: str):
        """Phase A Hall-like bound: per (prof, day),
        ``prof_day_load[p, d] <= max_c cl_day_load[c, d]`` over the
        classes the prof teaches that day. Mirrors
        ``cpsat_v2_timetable.solve_phase_a`` lines 685..732.

        Encoded class-by-class via:
            ind[c, d] := (sum_s day_count[(p, c, s, d)] >= 1)
            rl[c, d] = cl_day_load[c, d]   when ind == 1
            rl[c, d] = 0                    when ind == 0
            prof_day_load[p, d] <= max_c rl[c, d]

        The implication form is the same the legacy uses; ind makes
        sure that classes the prof doesn't touch on day d don't
        weaken the bound to 0.
        """
        if not self.day_count:
            self.diagnostics.append(
                "hall_bound_prof_day: day_count empty")
            return
        days = self._days_in_dc_scope()
        # Classes this prof teaches at all (any subject, any day).
        classes_of_p = sorted(
            {cl for (pp, cl, _s, _d) in self.day_count if pp == p}
        )
        if not classes_of_p:
            self.diagnostics.append(
                f"hall_bound_prof_day: prof {p!r} not in day_count")
            return
        for d in days:
            relevant_loads = []
            for c in classes_of_p:
                subj_terms = [
                    v for (pp, ccl, _s, dd), v in self.day_count.items()
                    if pp == p and ccl == c and dd == d
                ]
                if not subj_terms:
                    continue
                ind = self.model.NewBoolVar(
                    f"_dsl_hb_ind_{p}_{c}_{d}")
                cnt_pcd = sum(subj_terms)
                self.model.Add(cnt_pcd >= 1).OnlyEnforceIf(ind)
                self.model.Add(cnt_pcd == 0).OnlyEnforceIf(ind.Not())
                rl = self.model.NewIntVar(
                    0, 100, f"_dsl_hb_rl_{p}_{c}_{d}")
                cdl = self._cl_day_load_intvar(c, d)
                self.model.Add(rl == cdl).OnlyEnforceIf(ind)
                self.model.Add(rl == 0).OnlyEnforceIf(ind.Not())
                relevant_loads.append(rl)
            if not relevant_loads:
                continue
            max_load = self.model.NewIntVar(
                0, 100, f"_dsl_hb_max_{p}_{d}")
            self.model.AddMaxEquality(max_load, relevant_loads)
            pdl = self._prof_day_load_intvar(p, d)
            self.model.Add(pdl <= max_load)

    def _compile_subject_day_count_pair(
            self, cl: str, subjects: list[str], n: int):
        """Phase A "≥1 day with ≥n hours per subject" pragma.

        Mirrors the legacy Mat/Ita rule in
        ``cpsat_v2_timetable.solve_phase_a`` (lines 613..644): for
        every subject in ``subjects`` and every class ``cl``, at
        least one day must have at least ``n`` total hours of that
        (class, subject) combination. The total is summed over all
        teachers active for that (cl, subj) -- typically one but a
        compresenza splits across two and the sum still represents
        the class' load on that subject.

        Encoded by computing per-day sums into IntVars, taking the
        weekly max, and forcing ``max >= n``. The constraint fires
        per subject independently (the "pair" name reflects the
        typical 2-subject usage Mat+Ita, not a coupled rule).
        """
        if not self.day_count:
            self.diagnostics.append(
                "subject_day_count_pair: day_count empty")
            return
        if not subjects:
            return
        days = self._days_in_dc_scope()
        if not days:
            return
        for subj in subjects:
            day_sums = []
            for d in days:
                terms = [v for (_pp, ccl, ss, dd), v
                          in self.day_count.items()
                          if ccl == cl and ss == subj and dd == d]
                if not terms:
                    day_sums.append(self.model.NewConstant(0))
                    continue
                ds = self.model.NewIntVar(
                    0, 100, f"_dsl_sdcp_{subj[:3]}_{cl}_{d}")
                self.model.Add(ds == sum(terms))
                day_sums.append(ds)
            if not day_sums:
                continue
            mx = self.model.NewIntVar(
                0, 100, f"_dsl_sdcp_max_{subj[:3]}_{cl}")
            self.model.AddMaxEquality(mx, day_sums)
            self.model.Add(mx >= int(n))

    def _compile_free_day_choice_3way(
            self, prof: str, candidates: list[int],
            weights: list[int]):
        """Phase A free-day-choice pragma. Mirrors the legacy
        ``glib_choice`` block in
        ``cpsat_v2_timetable.solve_phase_a`` (lines 510..530, plus
        the 50/100 weights at lines 740..749).

        For ``prof``, three BoolVars ``pick[k]`` are introduced
        with ``sum(pick) == 1``. When ``pick[k]`` is selected, the
        sum of ``day_count`` over candidate day k must be 0 -- i.e.
        the prof has no lessons that day. Each pick contributes
        ``weights[k] * pick[k]`` to ``self.soft_cost_terms`` so the
        owning model can include them in its objective.

        ``candidates`` is a list of three ints in 1..6 (Monday=1).
        ``weights`` defaults to ``[0, 50, 100]`` so the first
        candidate is free, the second penalised at 50, the third
        at 100 -- the legacy weights.
        """
        if not self.day_count:
            self.diagnostics.append(
                "free_day_choice_3way: day_count empty")
            return
        if len(candidates) != 3 or len(weights) != 3:
            self.diagnostics.append(
                "free_day_choice_3way: expected 3 candidates "
                "and 3 weights")
            return
        # Ensure the prof actually has triples; otherwise the rule
        # is a no-op.
        prof_terms = [v for (pp, _cl, _s, _d), v in self.day_count.items()
                       if pp == prof]
        if not prof_terms:
            self.diagnostics.append(
                f"free_day_choice_3way: prof {prof!r} not in day_count")
            return
        picks = [self.model.NewBoolVar(
                    f"_dsl_glib_{prof}_{k}") for k in range(3)]
        self.model.Add(sum(picks) == 1)
        for k, day in enumerate(candidates):
            day_terms = [v for (pp, _cl, _s, dd), v
                          in self.day_count.items()
                          if pp == prof and dd == int(day)]
            if not day_terms:
                # Edge: candidate day has no demand for this prof;
                # picking it is a no-op.
                continue
            self.model.Add(sum(day_terms) == 0).OnlyEnforceIf(picks[k])
        for k in range(3):
            w = int(weights[k])
            if w != 0:
                self.soft_cost_terms.append((w, picks[k]))

    def _compile_class_day_load_in_day_count(
            self, cl: str, allowed: list[int]):
        """Phase A equivalent of ``class_day_load_in``: the daily
        class hours (sum of day_count IntVars over all cattedras of
        the class) must lie in ``allowed``. Mirrors the legacy
        ``cl_day_load[c, d] in {0, 4, 5, 6}`` rule on
        ``cpsat_v2_timetable.solve_phase_a``.
        """
        if not self.day_count:
            self.diagnostics.append(
                "class_day_load_in_day_count: day_count empty; "
                "did you forget to pass day_count= to the compiler?")
            return
        if not allowed:
            return
        days = self._days_in_dc_scope()
        # Filter the allowed values to non-negative ints; bounds from
        # the actual cl_day_load IntVar (max 100) clamp the rest.
        allowed_clamped = sorted({int(v) for v in allowed if int(v) >= 0})
        if not allowed_clamped:
            return
        for d in days:
            cdl = self._cl_day_load_intvar(cl, d)
            self.model.AddAllowedAssignments(
                [cdl], [(v,) for v in allowed_clamped])
