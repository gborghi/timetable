"""General-purpose constraint DSL.

A hand-rolled recursive-descent parser + tree-walk evaluator that lets
the user express HARD/SOFT constraints over the timetable model in a
high-level logical syntax. Compiles to a Python predicate over an
"active solution" snapshot (rows: Lessons + Assignments + entities)
and is invoked post-hoc by the optimizer:

  - HARD violations  -> reported by Feasibility Check / Cerca conflitti
                        and contribute "infeasible" status to the
                        post-Phase-B HARD verifier.
  - SOFT  violations -> add `weight` to the global soft-penalty score.

Grammar (informal BNF):

    expr        := iff_expr
    iff_expr    := implies_expr ( '<=>' implies_expr )*
    implies_expr:= or_expr ( '=>' or_expr )*
    or_expr     := and_expr ( ('OR'|'or') and_expr )*
    and_expr    := not_expr ( ('AND'|'and') not_expr )*
    not_expr    := ('NOT'|'not') not_expr | atom
    atom        := quant | call | comparison | '(' expr ')' | bool_lit
    quant       := ('forall'|'exists') var_list 'in' source
                   ['where' expr] ':' expr
                | 'count' var 'in' source ['where' expr] op num
                | 'sum'   '(' expr ')' 'in' source ... op num
    comparison  := value op value
    op          := '==' | '!=' | '<' | '<=' | '>' | '>='
                 | 'in' | 'not_in'
    value       := identifier ('.' identifier)* | number | string
                 | function_call
    function_call := identifier '(' [arg_list] ')'
    arg_list    := arg ( ',' arg )*
    arg         := identifier '=' value | value

Sources (collections to iterate):
    lessons | assignments | teachers | classes | classrooms |
    subjects | curricula | groups | days | hours | slots

Built-in functions:
    same_day(s1, s2), consecutive(s1, s2), hour(slot), day(slot),
    teacher(lesson), class(lesson), subject(lesson), classroom(lesson)

The evaluator runs against an in-memory snapshot built by
`build_world(db)` so it doesn't hit the DB during evaluation.

Limits (intentionally enforced):
- max iteration size: 50_000 rows per source
- max tree depth: 32
- atoms checked per call: <= 1_000_000  (raises ValidationError)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

# =====================================================================
# Tokenizer
# =====================================================================

_TOKEN_RE = re.compile(
    r"""
    \s+                                     |
    (?P<comment>\#[^\n]*)                   |
    (?P<lparen>\()                          |
    (?P<rparen>\))                          |
    (?P<lbrack>\[)                          |
    (?P<rbrack>\])                          |
    (?P<comma>,)                            |
    (?P<colon>:)                            |
    (?P<dot>\.)                             |
    (?P<arrow>=>)                           |
    (?P<iff>\<=\>)                          |
    (?P<op>(<=|>=|!=|==|<|>))               |
    (?P<eq>=)                               |
    (?P<dq>"(?:[^"\\]|\\.)*")               |
    (?P<sq>'(?:[^'\\]|\\.)*')               |
    # word: any run of [A-Za-z0-9_] that contains at least ONE
    # non-digit char. So '1A', '3B_scientifico', 'lun8' tokenize as
    # a single IDENT, while pure-digit tokens fall through to `num`
    # below. This matches the convention used by query_parser.py.
    (?P<word>[A-Za-z0-9_]*[A-Za-z_][A-Za-z0-9_]*) |
    (?P<num>-?\d+(?:\.\d+)?)
    """,
    re.VERBOSE,
)


_KEYWORDS = {
    "and": "LOG_AND", "AND": "LOG_AND",
    "or":  "LOG_OR",  "OR":  "LOG_OR",
    "not": "LOG_NOT", "NOT": "LOG_NOT",
    "forall": "QUANT", "exists": "QUANT", "count": "COUNT", "sum": "SUM",
    "in": "IN", "not_in": "NOT_IN",
    "where": "WHERE", "let": "LET",
    "true": "BOOL", "false": "BOOL", "True": "BOOL", "False": "BOOL",
}


class DSLError(ValueError):
    pass


def tokenize(text: str) -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m:
            raise DSLError(
                f"Token sconosciuto a colonna {pos+1}: "
                f"'{text[pos:pos+20]}'"
            )
        pos = m.end()
        for k, v in m.groupdict().items():
            if v is None:
                continue
            if k in ("comment",):
                break
            if k == "dq":
                out.append(("STRING", v[1:-1])); break
            if k == "sq":
                out.append(("STRING", v[1:-1])); break
            if k == "num":
                out.append(("NUM", float(v) if "." in v else int(v))); break
            if k == "word":
                kw = _KEYWORDS.get(v)
                if kw == "BOOL":
                    out.append(("BOOL", v.lower() == "true")); break
                if kw:
                    out.append((kw, v.lower())); break
                out.append(("IDENT", v)); break
            if k == "op":
                out.append(("OP", v)); break
            if k == "eq":
                # Treat single '=' as an alias for '==' to be friendlier.
                out.append(("OP", "==")); break
            if k == "lparen":
                out.append(("LP", "(")); break
            if k == "rparen":
                out.append(("RP", ")")); break
            if k == "lbrack":
                out.append(("LB", "[")); break
            if k == "rbrack":
                out.append(("RB", "]")); break
            if k == "comma":
                out.append(("COMMA", ",")); break
            if k == "colon":
                out.append(("COLON", ":")); break
            if k == "dot":
                out.append(("DOT", ".")); break
            if k == "arrow":
                out.append(("IMPLIES", "=>")); break
            if k == "iff":
                out.append(("IFF", "<=>")); break
    return out


# =====================================================================
# AST nodes
# =====================================================================


@dataclass
class Node:
    """Base AST node."""
    kind: str = ""


@dataclass
class Lit(Node):
    value: Any = None
    kind: str = field(default="LIT", init=False)


@dataclass
class Ref(Node):
    """Variable or attribute access: foo or foo.bar.baz."""
    path: list[str] = field(default_factory=list)
    kind: str = field(default="REF", init=False)


@dataclass
class Cmp(Node):
    op: str = ""
    left: Node | None = None
    right: Node | list[Node] | None = None
    kind: str = field(default="CMP", init=False)


@dataclass
class And(Node):
    args: list[Node] = field(default_factory=list)
    kind: str = field(default="AND", init=False)


@dataclass
class Or(Node):
    args: list[Node] = field(default_factory=list)
    kind: str = field(default="OR", init=False)


@dataclass
class Not(Node):
    arg: Node | None = None
    kind: str = field(default="NOT", init=False)


@dataclass
class Implies(Node):
    left: Node | None = None
    right: Node | None = None
    kind: str = field(default="IMPLIES", init=False)


@dataclass
class Iff(Node):
    left: Node | None = None
    right: Node | None = None
    kind: str = field(default="IFF", init=False)


@dataclass
class Quant(Node):
    """forall / exists. Body is the inner expression."""
    quant: str = ""           # 'forall' | 'exists'
    var: str = ""
    source: str = ""
    where: Node | None = None
    body: Node | None = None
    kind: str = field(default="QUANT", init=False)


@dataclass
class Count(Node):
    """count v in source [where filter] op N."""
    var: str = ""
    source: str = ""
    where: Node | None = None
    op: str = ""
    rhs: Any = None
    kind: str = field(default="COUNT", init=False)


@dataclass
class Call(Node):
    """Function call: f(x, y) or f(x=y, z=w)."""
    name: str = ""
    args: list[tuple[str | None, Node]] = field(default_factory=list)
    kind: str = field(default="CALL", init=False)


# =====================================================================
# Parser
# =====================================================================


_VALID_SOURCES = {
    "lessons", "assignments", "teachers", "classes", "classrooms",
    "subjects", "curricula", "groups", "days", "hours", "slots",
}


class Parser:
    def __init__(self, tokens: list[tuple[str, Any]]):
        self.tokens = tokens
        self.i = 0

    def _peek(self):
        return self.tokens[self.i] if self.i < len(self.tokens) else (None, None)

    def _eat(self, kind: str | None = None, value: Any = None):
        tok = self._peek()
        if tok == (None, None):
            raise DSLError("Fine inattesa dell'espressione")
        if kind is not None and tok[0] != kind:
            raise DSLError(
                f"Atteso {kind}, trovato {tok[0]} (={tok[1]!r})"
            )
        if value is not None and tok[1] != value:
            raise DSLError(
                f"Atteso {value!r}, trovato {tok[1]!r}"
            )
        self.i += 1
        return tok

    def parse(self):
        if not self.tokens:
            raise DSLError("Espressione vuota")
        node = self._parse_iff()
        if self.i != len(self.tokens):
            raise DSLError(
                f"Token in piu' dopo l'espressione: {self.tokens[self.i:]}"
            )
        return node

    def _parse_iff(self):
        left = self._parse_implies()
        while self._peek()[0] == "IFF":
            self._eat()
            right = self._parse_implies()
            left = Iff(left=left, right=right)
        return left

    def _parse_implies(self):
        left = self._parse_or()
        while self._peek()[0] == "IMPLIES":
            self._eat()
            right = self._parse_or()
            left = Implies(left=left, right=right)
        return left

    def _parse_or(self):
        left = self._parse_and()
        out = [left]
        while self._peek()[0] == "LOG_OR":
            self._eat()
            out.append(self._parse_and())
        return Or(args=out) if len(out) > 1 else left

    def _parse_and(self):
        left = self._parse_not()
        out = [left]
        while self._peek()[0] == "LOG_AND":
            self._eat()
            out.append(self._parse_not())
        return And(args=out) if len(out) > 1 else left

    def _parse_not(self):
        if self._peek()[0] == "LOG_NOT":
            self._eat()
            return Not(arg=self._parse_not())
        return self._parse_atom()

    def _parse_atom(self):
        tok = self._peek()
        if tok[0] == "QUANT":
            return self._parse_quant()
        if tok[0] == "COUNT":
            return self._parse_count()
        if tok[0] == "LP":
            self._eat()
            inner = self._parse_iff()
            self._eat("RP")
            return inner
        if tok[0] == "BOOL":
            self._eat()
            return Lit(value=bool(tok[1]))
        # comparison or value-only
        return self._parse_comparison_or_call()

    def _parse_quant(self):
        qtok = self._eat("QUANT")
        var = self._eat("IDENT")[1]
        self._eat("IN")
        src = self._eat("IDENT")[1]
        if src not in _VALID_SOURCES:
            raise DSLError(
                f"sorgente sconosciuta '{src}'. "
                f"Validi: {sorted(_VALID_SOURCES)}"
            )
        where = None
        if self._peek()[0] == "WHERE":
            self._eat()
            where = self._parse_or()  # filter doesn't include the body
        self._eat("COLON")
        body = self._parse_iff()
        return Quant(quant=qtok[1], var=var, source=src,
                     where=where, body=body)

    def _parse_count(self):
        self._eat("COUNT")
        var = self._eat("IDENT")[1]
        self._eat("IN")
        src = self._eat("IDENT")[1]
        if src not in _VALID_SOURCES:
            raise DSLError(f"sorgente sconosciuta '{src}'")
        where = None
        if self._peek()[0] == "WHERE":
            self._eat()
            where = self._parse_or()
        # Now expect op + value (e.g. <= 2). The colon is optional for
        # count, but we accept it for symmetry with forall/exists.
        if self._peek()[0] == "COLON":
            self._eat()
            # Allow "count v in src: l <= N" form
            atom = self._parse_comparison_or_call()
            if isinstance(atom, Cmp):
                return Count(var=var, source=src, where=where,
                              op=atom.op, rhs=atom.right)
            raise DSLError("count espressione: atteso confronto dopo ':'")
        # Direct form: count l in lessons where ... <= 2
        op_tok = self._peek()
        if op_tok[0] != "OP":
            raise DSLError("count: atteso operatore di confronto (==, <=, >=, ...)")
        self._eat()
        rhs = self._parse_value()
        return Count(var=var, source=src, where=where,
                      op=op_tok[1], rhs=rhs)

    def _parse_comparison_or_call(self):
        left = self._parse_value()
        tok = self._peek()
        if tok[0] == "OP":
            self._eat()
            right = self._parse_value()
            return Cmp(op=tok[1], left=left, right=right)
        if tok[0] == "IN" or tok[0] == "NOT_IN":
            self._eat()
            op_name = "in" if tok[0] == "IN" else "not_in"
            # Two forms supported:
            #   value in [a, b, c]     -- explicit list literal
            #   value in <path>        -- iterate a collection
            #                             (e.g. "matematica" in l.classroom.tags)
            if self._peek()[0] == "LB":
                self._eat("LB")
                vals = [self._parse_value()]
                while self._peek()[0] == "COMMA":
                    self._eat()
                    vals.append(self._parse_value())
                self._eat("RB")
                return Cmp(op=op_name, left=left, right=vals)
            # Single-value form: the right side is a path that must
            # evaluate to a list at runtime.
            right = self._parse_value()
            return Cmp(op=op_name + "_path", left=left, right=right)
        return left   # bare value (e.g. a function call returning bool)

    def _parse_value(self):
        tok = self._peek()
        if tok[0] == "STRING":
            self._eat()
            return Lit(value=str(tok[1]))
        if tok[0] == "NUM":
            self._eat()
            return Lit(value=tok[1])
        if tok[0] == "BOOL":
            self._eat()
            return Lit(value=bool(tok[1]))
        if tok[0] == "IDENT":
            ident = self._eat()[1]
            # function call?
            if self._peek()[0] == "LP":
                self._eat()
                args: list[tuple[str | None, Node]] = []
                if self._peek()[0] != "RP":
                    args.append(self._parse_call_arg())
                    while self._peek()[0] == "COMMA":
                        self._eat()
                        args.append(self._parse_call_arg())
                self._eat("RP")
                return Call(name=ident, args=args)
            # dotted ref: foo.bar.baz
            path = [ident]
            while self._peek()[0] == "DOT":
                self._eat()
                path.append(self._eat("IDENT")[1])
            return Ref(path=path)
        raise DSLError(f"valore atteso, trovato {tok}")

    def _parse_call_arg(self):
        # name=value OR positional value
        tok = self._peek()
        if tok[0] == "IDENT" and self.i + 1 < len(self.tokens) \
                and self.tokens[self.i + 1] == ("OP", "=="):
            # ident == value  -> treat as keyword arg "ident = value"
            name = self._eat("IDENT")[1]
            self._eat("OP")
            val = self._parse_value()
            return (name, val)
        return (None, self._parse_value())


def parse(text: str) -> Node:
    return Parser(tokenize(text or "")).parse()


# =====================================================================
# Validation
# =====================================================================


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    n_atoms: int = 0


_KNOWN_ENTITY_FIELDS: dict[str, set[str]] = {
    "lesson":    {"teacher", "class", "subject", "day", "hour",
                  "classroom", "slot", "group"},
    "assignment": {"teacher", "class", "subject", "hours", "locked"},
    "teacher":   {"name", "group", "max_hours", "free_day",
                  "graduatoria_score", "completion_hours",
                  "exemption_hours"},
    "class":     {"name", "year", "section", "curriculum",
                  "n_students"},
    "classroom": {"name", "kind", "type", "capacity"},
    "subject":   {"name"},
    "curriculum": {"name", "code", "score"},
    "group":     {"name", "kind"},
    "slot":      {"day", "hour"},
    "day":       {"name", "index"},
    "hour":      {"index"},
}


def validate(tree: Node, max_atoms: int = 1_000_000
             ) -> ValidationResult:
    """Light static analysis: source names, attribute names, depth."""
    errors: list[str] = []
    warnings: list[str] = []
    atoms = [0]
    depth = [0]

    def visit(n: Node, env: dict[str, str]):
        if depth[0] > 32:
            errors.append(
                "espressione troppo profonda (>32 livelli annidati)"
            )
            return
        depth[0] += 1
        atoms[0] += 1
        if atoms[0] > max_atoms:
            errors.append(
                f"oltre {max_atoms} atomi: probabile esplosione "
                f"combinatoria"
            )
            depth[0] -= 1
            return
        if isinstance(n, (Lit,)):
            pass
        elif isinstance(n, Ref):
            head = n.path[0]
            if head in env:
                # Variable bound by quantifier; check attribute exists
                # on its sourced entity.
                src = env[head]
                ent_kind = _source_to_entity(src)
                if len(n.path) > 1 and ent_kind:
                    attr = n.path[1]
                    fields = _KNOWN_ENTITY_FIELDS.get(ent_kind, set())
                    if attr not in fields:
                        warnings.append(
                            f"attributo sconosciuto '{attr}' su "
                            f"entita' '{ent_kind}'. Disponibili: "
                            f"{sorted(fields)}"
                        )
            elif head in _KNOWN_ENTITY_FIELDS:
                pass  # bare entity reference (e.g. lesson.teacher)
            elif head in _VALID_SOURCES:
                pass
            else:
                # could be a string literal in disguise (Borghi, 1A...).
                # Tolerate: treat as string-comparison RHS.
                pass
        elif isinstance(n, Cmp):
            visit(n.left, env)
            if isinstance(n.right, list):
                for r in n.right:
                    visit(r, env)
            else:
                visit(n.right, env)
        elif isinstance(n, And) or isinstance(n, Or):
            for a in n.args:
                visit(a, env)
        elif isinstance(n, Not):
            visit(n.arg, env)
        elif isinstance(n, (Implies, Iff)):
            visit(n.left, env); visit(n.right, env)
        elif isinstance(n, Quant):
            new_env = {**env, n.var: n.source}
            if n.where is not None:
                visit(n.where, new_env)
            if n.body is not None:
                visit(n.body, new_env)
        elif isinstance(n, Count):
            new_env = {**env, n.var: n.source}
            if n.where is not None:
                visit(n.where, new_env)
            if isinstance(n.rhs, Node):
                visit(n.rhs, env)
        elif isinstance(n, Call):
            for _, a in n.args:
                visit(a, env)
        depth[0] -= 1

    visit(tree, {})
    return ValidationResult(
        ok=(len(errors) == 0),
        errors=errors, warnings=warnings,
        n_atoms=atoms[0],
    )


def _source_to_entity(src: str) -> str | None:
    return {
        "lessons": "lesson", "assignments": "assignment",
        "teachers": "teacher", "classes": "class",
        "classrooms": "classroom", "subjects": "subject",
        "curricula": "curriculum", "groups": "group",
        "slots": "slot", "days": "day", "hours": "hour",
    }.get(src)


# =====================================================================
# Evaluator (post-hoc, on a "world" snapshot)
# =====================================================================


def build_world(db) -> dict[str, list]:
    """Materialize the relevant DB state into a dict of lists for the
    evaluator. Called once per evaluation pass; cheap (few k rows).

    Each item is a `dict` with the entity's attributes. Nested
    references (e.g. `lesson.class.curriculum`) are pre-resolved so
    the evaluator stays a simple dotted-path lookup.
    """
    from .. import models, engine_io
    out: dict[str, list] = {}
    teachers_by_id = {t.id: t for t in db.query(models.Teacher).all()}
    classes_by_id = {c.id: c for c in db.query(models.SchoolClass).all()}
    curricula_by_id = {c.id: c for c in db.query(models.Curriculum).all()}
    rooms_by_id = {r.id: r for r in db.query(models.Classroom).all()}

    # Pre-collect each teacher's subjects so the DSL can write
    #   t.subject == "Fisica"
    # which we treat as "Fisica is in t.subjects" (see _apply_op).
    from .. import models as _m
    teacher_subjects: dict[int, list[str]] = {}
    for ts in db.query(_m.TeacherSubject).all():
        teacher_subjects.setdefault(ts.teacher_id, []).append(ts.subject)
    out["teachers"] = [
        {"name": t.name, "group": t.group, "max_hours": t.max_hours,
         "free_day": t.free_day,
         "graduatoria_score": t.graduatoria_score,
         "completion_hours": t.completion_hours,
         "exemption_hours": t.exemption_hours,
         # Both `subject` (singular, list-typed for the
         # `==`-as-contains shorthand) and `subjects` (plural, the
         # canonical list) resolve to the same data.
         "subject": teacher_subjects.get(t.id, []),
         "subjects": teacher_subjects.get(t.id, [])}
        for t in teachers_by_id.values()
    ]
    out["classes"] = [
        {"name": c.name, "year": c.year, "section": c.section,
         "curriculum": (
             curricula_by_id.get(c.curriculum_id).name
             if c.curriculum_id and curricula_by_id.get(c.curriculum_id)
             else (c.curriculum or "")
         ),
         "n_students": c.n_students}
        for c in classes_by_id.values()
    ]
    out["classrooms"] = [
        {"name": r.name, "kind": r.kind, "type": r.kind,
         "capacity": r.capacity}
        for r in rooms_by_id.values()
    ]
    out["subjects"] = [
        {"name": s.name} for s in db.query(models.Subject).all()
    ]
    out["curricula"] = [
        {"name": c.name, "code": c.code, "score": c.score}
        for c in curricula_by_id.values()
    ]
    out["groups"] = [
        {"name": g.name, "kind": g.kind}
        for g in db.query(models.StudyGroup).all()
    ]
    out["days"] = [{"index": d, "name": _day_name(d)}
                   for d in range(1, 7)]
    out["hours"] = [{"index": h} for h in range(8, 14)]
    out["slots"] = [{"day": d, "hour": h}
                    for d in range(1, 7) for h in range(8, 14)]

    out["assignments"] = []
    for a in db.query(models.Assignment).all():
        t = teachers_by_id.get(a.teacher_id)
        c = classes_by_id.get(a.class_id)
        out["assignments"].append({
            "teacher": t.name if t else None,
            "class": c.name if c else None,
            "subject": a.subject,
            "hours": a.hours,
            "locked": bool(a.locked),
        })
    out["lessons"] = []
    active = engine_io.get_active_solution(db)
    if active is not None:
        # class -> curriculum lookup for fast `lesson.class.curriculum`
        cls_to_curr: dict[str, str] = {}
        for c in classes_by_id.values():
            cls_to_curr[c.name] = (
                curricula_by_id.get(c.curriculum_id).name
                if c.curriculum_id and curricula_by_id.get(c.curriculum_id)
                else (c.curriculum or "")
            )
        # Pre-resolve classroom name -> kind/type/tags so
        # `l.classroom.type == "lab_fisica"` and
        # `"matematica" in l.classroom.tags` work without nested obj.
        room_type_by_name: dict[str, str] = {
            r.name: (r.kind or "") for r in rooms_by_id.values()
        }
        room_tags_by_name: dict[str, list[str]] = {}
        for r in rooms_by_id.values():
            room_tags_by_name[r.name] = sorted({
                a.tag.name for a in (r.tag_assignments or [])
                if a.tag is not None
            })
        for l in db.query(models.Lesson).filter(
            models.Lesson.solution_id == active.id
        ).all():
            cr_name = l.classroom_name or ""
            cr_type = room_type_by_name.get(cr_name, "")
            cr_tags = room_tags_by_name.get(cr_name, [])
            out["lessons"].append({
                "teacher": l.teacher_name,
                "class": l.class_name,
                "class_curriculum": cls_to_curr.get(l.class_name, ""),
                "subject": l.subject,
                "day": l.day,
                "hour": l.hour,
                "classroom": cr_name,
                "classroom_type": cr_type,    # alias for l.classroom.type
                "classroom_kind": cr_type,    # alias for l.classroom.kind
                "classroom_tags": cr_tags,    # alias for l.classroom.tags
                "slot": (l.day, l.hour),
            })
    # Also populate the classrooms world dict with tags so DSLs that
    # iterate `forall r in classrooms: ...` can read r.tags.
    cr_to_tags: dict[str, list[str]] = {}
    for r in rooms_by_id.values():
        cr_to_tags[r.name] = sorted({
            a.tag.name for a in (r.tag_assignments or [])
            if a.tag is not None
        })
    for r in out["classrooms"]:
        r["tags"] = cr_to_tags.get(r["name"], [])
    return out


_DAY_NAMES = {1: "lun", 2: "mar", 3: "mer", 4: "gio",
              5: "ven", 6: "sab"}


def _day_name(d: int) -> str:
    return _DAY_NAMES.get(d, "?")


def _resolve_path(env: dict, path: list[str]) -> Any:
    """env has variable bindings (var -> dict) and entity resolvers.
    Path examples: ['l', 'teacher'] -> env['l']['teacher'].
                   ['l', 'class', 'curriculum'] -> chained -- we
                   pre-resolved this as 'class_curriculum' on the
                   lesson dict so we just return that.
                   ['l', 'classroom', 'type'] -> 'classroom_type'.
    """
    if not path:
        return None
    head = path[0]
    if head not in env:
        # Bare identifier: treat as string literal (e.g. "Borghi")
        return head if len(path) == 1 else "::missing::"
    cur = env[head]
    i = 1
    while i < len(path):
        attr = path[i]
        if isinstance(cur, dict):
            # Two-step chain shortcuts (pre-resolved into the dict):
            #   .class.curriculum -> class_curriculum
            #   .classroom.type   -> classroom_type
            #   .classroom.kind   -> classroom_kind
            if (i + 1 < len(path)
                    and (f"{attr}_{path[i+1]}" in cur)):
                cur = cur[f"{attr}_{path[i+1]}"]
                i += 2
                continue
            if attr in cur:
                cur = cur[attr]
                i += 1
                continue
            return None
        else:
            return None
    return cur


def _eval(node: Node, env: dict, world: dict) -> Any:
    if isinstance(node, Lit):
        return node.value
    if isinstance(node, Ref):
        return _resolve_path(env, node.path)
    if isinstance(node, And):
        return all(_eval(a, env, world) for a in node.args)
    if isinstance(node, Or):
        return any(_eval(a, env, world) for a in node.args)
    if isinstance(node, Not):
        return not _eval(node.arg, env, world)
    if isinstance(node, Implies):
        l = _eval(node.left, env, world)
        return (not l) or bool(_eval(node.right, env, world))
    if isinstance(node, Iff):
        return bool(_eval(node.left, env, world)) \
                == bool(_eval(node.right, env, world))
    if isinstance(node, Cmp):
        return _eval_cmp(node, env, world)
    if isinstance(node, Quant):
        items = world.get(node.source, [])
        if node.quant == "forall":
            for it in items:
                new_env = {**env, node.var: it}
                if node.where is not None:
                    if not _eval(node.where, new_env, world):
                        continue
                if not _eval(node.body, new_env, world):
                    return False
            return True
        if node.quant == "exists":
            for it in items:
                new_env = {**env, node.var: it}
                if node.where is not None:
                    if not _eval(node.where, new_env, world):
                        continue
                if _eval(node.body, new_env, world):
                    return True
            return False
    if isinstance(node, Count):
        items = world.get(node.source, [])
        n = 0
        for it in items:
            new_env = {**env, node.var: it}
            if node.where is None or _eval(node.where, new_env, world):
                n += 1
        rhs = node.rhs
        if isinstance(rhs, Node):
            rhs = _eval(rhs, env, world)
        return _apply_op(n, node.op, rhs)
    if isinstance(node, Call):
        return _eval_call(node, env, world)
    return None


def _eval_cmp(node: Cmp, env, world):
    L = _eval(node.left, env, world)
    if node.op in ("in", "not_in"):
        rhs = [_eval(r, env, world) for r in node.right]
        ok = L in rhs
        return ok if node.op == "in" else (not ok)
    if node.op in ("in_path", "not_in_path"):
        # Right side is a path that should resolve to a collection
        # at runtime. Membership check on whatever it evaluates to.
        coll = _eval(node.right, env, world)
        if not isinstance(coll, (list, tuple, set)):
            # Treat scalar / None as a singleton or empty set
            coll = [coll] if coll is not None else []
        ok = L in coll
        return ok if node.op == "in_path" else (not ok)
    R = _eval(node.right, env, world)
    return _apply_op(L, node.op, R)


def _apply_op(a, op, b):
    # When one side is an entity dict (with a `name` key) and the
    # other side is a scalar, compare by name. This lets the user
    # write `l.teacher == t` where t is bound by `forall t in
    # teachers` (a teacher dict) and l.teacher is the canonical
    # teacher name string.
    def _name_of(x):
        if isinstance(x, dict) and "name" in x:
            return x["name"]
        return x
    a = _name_of(a)
    b = _name_of(b)
    # Coerce types softly so "1A" == 1A works (both treated as strings).
    if op in ("==", "!="):
        if a is None and b is None:
            return op == "=="
        # Multi-valued shorthand: when one side is a list/tuple/set,
        # `list == scalar` means "scalar in list". Useful for
        # `t.subject == "Fisica"` where t.subject is the list of
        # subjects the teacher teaches. Mirror semantics for !=.
        if isinstance(a, (list, tuple, set)) and not isinstance(b, (list, tuple, set)):
            ok = b in a
            return ok if op == "==" else (not ok)
        if isinstance(b, (list, tuple, set)) and not isinstance(a, (list, tuple, set)):
            ok = a in b
            return ok if op == "==" else (not ok)
        try:
            if isinstance(a, (int, float)) and isinstance(b, str):
                b = type(a)(b)
            elif isinstance(b, (int, float)) and isinstance(a, str):
                a = type(b)(a)
        except Exception:
            a = str(a); b = str(b)
        return (a == b) if op == "==" else (a != b)
    try:
        if op == "<":  return a < b
        if op == ">":  return a > b
        if op == "<=": return a <= b
        if op == ">=": return a >= b
    except TypeError:
        a = str(a); b = str(b)
        if op == "<":  return a < b
        if op == ">":  return a > b
        if op == "<=": return a <= b
        if op == ">=": return a >= b
    return False


def _eval_call(node: Call, env, world):
    name = node.name.lower()
    pos = [_eval(v, env, world) for k, v in node.args if k is None]
    kw = {k: _eval(v, env, world) for k, v in node.args if k is not None}
    if name == "lesson":
        # exists a lesson matching all kw filters?
        for l in world.get("lessons", []):
            if all(l.get(k) == v for k, v in kw.items()):
                return True
        return False
    if name == "same_day":
        a, b = pos[0], pos[1]
        return _attr(a, "day") == _attr(b, "day")
    if name == "consecutive":
        a, b = pos[0], pos[1]
        return (_attr(a, "day") == _attr(b, "day")
                and abs(int(_attr(a, "hour")) - int(_attr(b, "hour"))) == 1)
    if name == "hour":
        return _attr(pos[0], "hour")
    if name == "day":
        return _attr(pos[0], "day")
    if name == "teacher":
        return _attr(pos[0], "teacher")
    if name == "class":
        return _attr(pos[0], "class")
    if name == "subject":
        return _attr(pos[0], "subject")
    if name == "classroom":
        return _attr(pos[0], "classroom")
    raise DSLError(f"funzione sconosciuta: {name!r}")


def _attr(obj, attr):
    if isinstance(obj, dict):
        return obj.get(attr)
    if isinstance(obj, tuple) and attr in ("day", "hour"):
        return obj[0] if attr == "day" else obj[1]
    return None


def evaluate(tree: Node, world: dict) -> bool:
    """Run the full expression on a world snapshot. Returns True/False
    (the truth value of the top-level boolean expression)."""
    return bool(_eval(tree, {}, world))


def evaluate_safe(tree: Node, world: dict) -> tuple[bool, str | None]:
    try:
        return (evaluate(tree, world), None)
    except Exception as e:
        return (True, str(e))   # default to "satisfied" on eval error
