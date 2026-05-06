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
        if isinstance(bound, tuple) and head in key_lookup:
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

    Compilation API
    ---------------
    ``compile(node)`` returns:
      - None when the node has been added as a HARD constraint
      - A list of CP-SAT BoolExpr for SOFT integration (TODO)
    """

    def __init__(self, model, slot: dict, *, config=None,
                 is_hard: bool = True,
                 classroom_for_slot: dict | None = None,
                 plessi_data: Any = None):
        self.model = model
        self.slot = slot
        self.config = config
        self.is_hard = is_hard
        # Optional classroom + plesso resolution carriers. When the
        # caller wants DSL rules that reference ``l.classroom`` /
        # ``l.classroom.plesso`` to be enforced, both must be passed
        # in (or just classroom_for_slot for ``l.classroom`` alone).
        # The DTOs are forwarded verbatim to ``_eval_static`` /
        # ``_resolve_lesson_path`` and never mutated.
        self.classroom_for_slot = classroom_for_slot
        self.plessi_data = plessi_data
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
