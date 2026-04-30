"""Tiny DSL for Phase-A assignment objective expressions.

Grammar (BNF, approximate):

    program       := direction expr
    direction     := 'minimize' | 'maximize'

    expr          := term (('+' | '-') term)*
    term          := factor (('*' | '/') factor)*
    factor        := NUMBER
                   | call
                   | IDENT                           # named variable
                   | '-' factor
                   | '(' expr ')'
    call          := IDENT '(' [arg (',' arg)*] ')'
    arg           := expr

Recognised identifiers (validated at compile time):

  Aggregates (implicitly summed over all teachers when they take a
  per-teacher expression):
    - sum(<predicate-or-expr>)
    - count(<predicate-or-expr>)        # alias of sum on a boolean
  Per-teacher numeric variables (auto-summed by sum/count, or
  combined arithmetically with constants):
    - teacher_hours[t]        actual_hours[t]
    - teacher_max_hours[t]
    - teacher_unused[t]       max_hours - actual_hours
    - teacher_n_classes[t]    distinct classes for t
    - teacher_n_curricula[t]  distinct curriculum-tops for t
    - teacher_weight[t]       sum of curriculum_score across t's
                              assigned classes
  Per-teacher boolean predicates (call form):
    - over_max_hours          (always false in current model -> 0)
    - under_min_hours(N)      teacher_hours[t] < N
    - over_min_hours(N)       teacher_hours[t] >= N
    - cross_curricula         teacher_n_curricula[t] > 1
    - single_curriculum       teacher_n_curricula[t] == 1
    - empty_teacher           teacher_hours[t] == 0
  Scalar (already-aggregated) variables:
    - total_unused_capacity   = sum_t teacher_unused[t]
    - total_n_classes         = sum_t teacher_n_classes[t]
    - total_n_curricula       = sum_t teacher_n_curricula[t]
    - total_weight            = sum_t teacher_weight[t]

CP-SAT compile rules:
- Linear combinations of model IntVars/BoolVars are produced as a
  single ortools `LinearExpr`. A scalar constant is broadcast.
- Any non-linear construct (e.g. `stddev`, `mean`, `var`,
  multiplication of two variables) is rejected at validation with a
  clear error pointing at the offending node.

The module is self-contained: no external parser library, easy to
test in isolation (see webui/backend/tests/test_objective_dsl.py).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable


# ============================================================
# Tokenizer
# ============================================================

_TOKEN_RE = re.compile(
    r"""
    \s+                              # whitespace
    | (?P<NUMBER>-?\d+(?:\.\d+)?)
    | (?P<IDENT>[A-Za-z_][A-Za-z0-9_]*)
    | (?P<LPAREN>\()
    | (?P<RPAREN>\))
    | (?P<COMMA>,)
    | (?P<PLUS>\+)
    | (?P<MINUS>-)
    | (?P<STAR>\*)
    | (?P<SLASH>/)
    """,
    re.VERBOSE,
)

KEYWORDS = {"minimize", "maximize"}


@dataclass
class Token:
    type: str
    value: str
    pos: int


def tokenize(src: str) -> list[Token]:
    out: list[Token] = []
    i = 0
    while i < len(src):
        m = _TOKEN_RE.match(src, i)
        if not m:
            raise SyntaxError(f"Carattere inatteso a posizione {i}: "
                              f"{src[i]!r}")
        i = m.end()
        if m.lastgroup is None:
            continue
        out.append(Token(type=m.lastgroup, value=m.group(),
                         pos=m.start()))
    out.append(Token(type="EOF", value="", pos=len(src)))
    return out


# ============================================================
# AST nodes (dicts to keep it simple)
# ============================================================

def n_program(direction: str, expr: dict) -> dict:
    return {"node": "program", "direction": direction, "expr": expr}


def n_num(v: float) -> dict:
    return {"node": "num", "value": v}


def n_ident(name: str, pos: int) -> dict:
    return {"node": "ident", "name": name, "pos": pos}


def n_call(name: str, args: list[dict], pos: int) -> dict:
    return {"node": "call", "name": name, "args": args, "pos": pos}


def n_binop(op: str, lhs: dict, rhs: dict) -> dict:
    return {"node": "binop", "op": op, "lhs": lhs, "rhs": rhs}


def n_unop(op: str, operand: dict) -> dict:
    return {"node": "unop", "op": op, "operand": operand}


# ============================================================
# Parser
# ============================================================


class Parser:
    def __init__(self, toks: list[Token]):
        self.toks = toks
        self.i = 0

    @property
    def cur(self) -> Token:
        return self.toks[self.i]

    def eat(self, ttype: str | None = None) -> Token:
        t = self.cur
        if ttype is not None and t.type != ttype:
            raise SyntaxError(
                f"Atteso {ttype} ma trovato {t.type} ({t.value!r}) "
                f"a posizione {t.pos}"
            )
        self.i += 1
        return t

    def parse_program(self) -> dict:
        # direction expr
        if self.cur.type != "IDENT" or self.cur.value not in KEYWORDS:
            raise SyntaxError(
                f"L'espressione deve iniziare con 'minimize' o "
                f"'maximize'. Trovato {self.cur.value!r} a "
                f"posizione {self.cur.pos}."
            )
        direction = self.eat("IDENT").value
        expr = self.parse_expr()
        if self.cur.type != "EOF":
            raise SyntaxError(
                f"Token extra dopo l'espressione: "
                f"{self.cur.value!r} a posizione {self.cur.pos}"
            )
        return n_program(direction, expr)

    def parse_expr(self) -> dict:
        node = self.parse_term()
        while self.cur.type in ("PLUS", "MINUS"):
            op = self.eat().value
            rhs = self.parse_term()
            node = n_binop(op, node, rhs)
        return node

    def parse_term(self) -> dict:
        node = self.parse_factor()
        while self.cur.type in ("STAR", "SLASH"):
            op = self.eat().value
            rhs = self.parse_factor()
            node = n_binop(op, node, rhs)
        return node

    def parse_factor(self) -> dict:
        t = self.cur
        if t.type == "NUMBER":
            self.eat()
            return n_num(float(t.value))
        if t.type == "MINUS":
            self.eat()
            return n_unop("-", self.parse_factor())
        if t.type == "LPAREN":
            self.eat()
            inner = self.parse_expr()
            self.eat("RPAREN")
            return inner
        if t.type == "IDENT":
            self.eat()
            if t.value in KEYWORDS:
                raise SyntaxError(
                    f"Parola riservata usata come variabile: "
                    f"{t.value!r}"
                )
            if self.cur.type == "LPAREN":
                self.eat("LPAREN")
                args: list[dict] = []
                if self.cur.type != "RPAREN":
                    args.append(self.parse_expr())
                    while self.cur.type == "COMMA":
                        self.eat("COMMA")
                        args.append(self.parse_expr())
                self.eat("RPAREN")
                return n_call(t.value, args, t.pos)
            return n_ident(t.value, t.pos)
        raise SyntaxError(
            f"Token inatteso {t.type} ({t.value!r}) a posizione "
            f"{t.pos}"
        )


def parse(src: str) -> dict:
    return Parser(tokenize(src)).parse_program()


# ============================================================
# Vocabulary (the validator's source of truth)
# ============================================================

# Per-teacher numeric "variables": when used inside sum() they expand
# to sum_t var[t]; when used standalone they need an [t] index, which
# our DSL doesn't support today (kept for future extension). For MVP
# we accept them ONLY inside `sum(...)` / `count(...)`.
PER_TEACHER_VARS = {
    "teacher_hours",
    "teacher_max_hours",
    "teacher_unused",
    "teacher_n_classes",
    "teacher_n_curricula",
    "teacher_weight",
}

# Per-teacher boolean predicates (called like functions). Some take
# args; the validator checks arity.
PREDICATES: dict[str, int] = {
    "over_max_hours": 0,
    "under_min_hours": 1,
    "over_min_hours": 1,
    "cross_curricula": 0,
    "single_curriculum": 0,
    "empty_teacher": 0,
}

# Already-aggregated scalar variables. Can be used at the top level.
SCALAR_VARS = {
    "total_unused_capacity",
    "total_n_classes",
    "total_n_curricula",
    "total_weight",
    "n_under_18",      # backward compat
    "n_under_10",      # backward compat
}

AGGREGATES = {"sum", "count"}

# Non-linear functions we explicitly reject (clear error, not silent).
NON_LINEAR_FNS = {"stddev", "var", "mean", "abs"}


# ============================================================
# Validator
# ============================================================


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    direction: str | None = None


def validate(src: str) -> ValidationResult:
    """Parse + structurally validate. Does NOT compile (no model
    needed). Used by `POST /api/optimize/phase-a/validate-expression`
    so the frontend can syntax-check live."""
    res = ValidationResult(ok=False)
    try:
        ast = parse(src)
    except SyntaxError as e:
        res.errors.append(str(e))
        return res
    res.direction = ast["direction"]
    _check(ast["expr"], inside_aggregate=False, errs=res.errors)
    res.ok = len(res.errors) == 0
    return res


def _check(node: dict, inside_aggregate: bool, errs: list[str]) -> None:
    nt = node["node"]
    if nt == "num":
        return
    if nt == "ident":
        name = node["name"]
        if name in SCALAR_VARS:
            return
        if name in PER_TEACHER_VARS:
            if not inside_aggregate:
                errs.append(
                    f"'{name}' e' una variabile per-docente: usala "
                    f"dentro sum(...) o count(...) a posizione "
                    f"{node['pos']}."
                )
            return
        if name in PREDICATES:
            errs.append(
                f"'{name}' e' un predicato: chiamalo con () a "
                f"posizione {node['pos']}."
            )
            return
        errs.append(
            f"Identificatore sconosciuto '{name}' a posizione "
            f"{node['pos']}."
        )
        return
    if nt == "call":
        name = node["name"]
        args = node["args"]
        if name in NON_LINEAR_FNS:
            errs.append(
                f"Funzione non lineare '{name}' non supportata. "
                f"Usa una linearizzazione (es. sum di scarti "
                f"assoluti tramite variabili ausiliarie). Posizione "
                f"{node['pos']}."
            )
            return
        if name in AGGREGATES:
            if len(args) != 1:
                errs.append(
                    f"'{name}' richiede 1 argomento, trovati "
                    f"{len(args)} a posizione {node['pos']}."
                )
            else:
                _check(args[0], inside_aggregate=True, errs=errs)
            return
        if name in PREDICATES:
            arity = PREDICATES[name]
            if len(args) != arity:
                errs.append(
                    f"'{name}' richiede {arity} argomenti, trovati "
                    f"{len(args)} a posizione {node['pos']}."
                )
            for a in args:
                _check(a, inside_aggregate=False, errs=errs)
            if not inside_aggregate:
                errs.append(
                    f"Predicato '{name}' usato fuori da un "
                    f"aggregato (sum/count). Avvolgilo: "
                    f"sum({name}(...))."
                )
            return
        errs.append(
            f"Funzione sconosciuta '{name}' a posizione {node['pos']}."
        )
        return
    if nt == "unop":
        _check(node["operand"], inside_aggregate=inside_aggregate, errs=errs)
        return
    if nt == "binop":
        op = node["op"]
        lhs, rhs = node["lhs"], node["rhs"]
        _check(lhs, inside_aggregate=inside_aggregate, errs=errs)
        _check(rhs, inside_aggregate=inside_aggregate, errs=errs)
        if op in ("*", "/"):
            # Reject variable * variable (non-linear). One side must
            # be a constant (or a unary minus on a constant). We
            # detect this by inspecting whether either side is purely
            # constant.
            l_const = _is_constant_subtree(lhs)
            r_const = _is_constant_subtree(rhs)
            if not (l_const or r_const):
                errs.append(
                    "Moltiplicazione/divisione fra due espressioni "
                    "non costanti non supportata (sarebbe non lineare). "
                    "Usa un coefficiente costante su un lato."
                )
            if op == "/" and not r_const:
                errs.append(
                    "La divisione richiede un divisore costante."
                )
        return
    errs.append(f"Nodo AST sconosciuto: {nt}")


def _is_constant_subtree(node: dict) -> bool:
    nt = node["node"]
    if nt == "num":
        return True
    if nt == "unop":
        return _is_constant_subtree(node["operand"])
    if nt == "binop":
        return (_is_constant_subtree(node["lhs"])
                and _is_constant_subtree(node["rhs"]))
    return False


# ============================================================
# Compile context + compiler
# ============================================================


@dataclass
class CompileContext:
    """Bag of per-teacher and scalar CP-SAT vars/expressions exposed
    by the model builder. The compiler reads from here. For aggregates
    we need the per-teacher arrays (lists indexed by teacher index)."""
    model: Any                         # cp_model.CpModel
    n_teachers: int
    # Per-teacher arrays (each list len == n_teachers, indexed by ti):
    teacher_hours: list                  # IntVar
    teacher_max_hours: list              # plain int per teacher
    teacher_unused: list                 # IntVar
    teacher_n_classes: list              # IntVar
    teacher_n_curricula: list            # IntVar
    teacher_weight: list                 # IntVar
    # Scalars (CP-SAT IntVar or plain int):
    total_unused_capacity: Any
    total_n_classes: Any
    total_n_curricula: Any
    total_weight: Any
    n_under_18: Any
    n_under_10: Any
    # Helpers built lazily for predicates: cache of {name -> list[BoolVar]}
    _pred_cache: dict[str, list] = field(default_factory=dict)


def compile_to_objective(src: str, ctx: CompileContext):
    """Parse + validate + lower to an ortools LinearExpr.

    Returns (linear_expr, direction) where direction in {'minimize',
    'maximize'}. Caller then does `ctx.model.Minimize(linear_expr)` or
    `Maximize(...)`."""
    val = validate(src)
    if not val.ok:
        raise ValueError("Espressione non valida: " + "; ".join(val.errors))
    ast = parse(src)
    expr = _lower(ast["expr"], ctx, inside_aggregate=False)
    return expr, ast["direction"]


def _lower(node: dict, ctx: CompileContext, inside_aggregate: bool):
    nt = node["node"]
    if nt == "num":
        return node["value"]
    if nt == "ident":
        name = node["name"]
        if name == "total_unused_capacity":
            return ctx.total_unused_capacity
        if name == "total_n_classes":
            return ctx.total_n_classes
        if name == "total_n_curricula":
            return ctx.total_n_curricula
        if name == "total_weight":
            return ctx.total_weight
        if name == "n_under_18":
            return ctx.n_under_18
        if name == "n_under_10":
            return ctx.n_under_10
        # Per-teacher var inside an aggregate handled in `call` lower;
        # if we got here standalone the validator should have caught it.
        raise ValueError(f"Variabile '{name}' non risolvibile fuori "
                         f"da un aggregato.")
    if nt == "unop":
        operand = _lower(node["operand"], ctx, inside_aggregate)
        return -operand
    if nt == "binop":
        lhs = _lower(node["lhs"], ctx, inside_aggregate)
        rhs = _lower(node["rhs"], ctx, inside_aggregate)
        op = node["op"]
        if op == "+":
            return lhs + rhs
        if op == "-":
            return lhs - rhs
        if op == "*":
            return lhs * rhs       # one side constant by validator
        if op == "/":
            return lhs / rhs       # rhs constant by validator
        raise ValueError(f"Operatore inatteso {op}")
    if nt == "call":
        name = node["name"]
        args = node["args"]
        if name in AGGREGATES:
            # sum or count of a per-teacher quantity. We expand the arg
            # over the n_teachers dimension by re-lowering inside an
            # iteration with `_per_teacher_terms`.
            return _aggregate_sum(args[0], ctx)
        if name in PREDICATES:
            # Outside aggregate -> validator error already; inside the
            # aggregate's argument we dispatch from `_per_teacher_terms`.
            raise ValueError(
                f"Predicato '{name}' chiamato fuori da un aggregato."
            )
        raise ValueError(f"Chiamata non riconosciuta: {name}")
    raise ValueError(f"Nodo AST sconosciuto: {nt}")


def _aggregate_sum(arg_node: dict, ctx: CompileContext):
    """Expand `sum(<arg>)`: arg is an expression over per-teacher
    quantities. Build the list of per-teacher terms then sum them up.
    Constants inside the arg multiply through."""
    terms = _per_teacher_terms(arg_node, ctx)
    if not terms:
        return 0
    return sum(terms)


def _per_teacher_terms(node: dict, ctx: CompileContext) -> list:
    """Return one CP-SAT term per teacher for the given subtree."""
    nt = node["node"]
    if nt == "num":
        v = node["value"]
        return [v] * ctx.n_teachers
    if nt == "ident":
        name = node["name"]
        if name in PER_TEACHER_VARS:
            return _per_teacher_array(name, ctx)
        if name in SCALAR_VARS:
            # A scalar inside sum(...) produces n_teachers copies.
            scalar = _lower(node, ctx, inside_aggregate=True)
            return [scalar] * ctx.n_teachers
        raise ValueError(
            f"Variabile per-docente non riconosciuta: '{name}'"
        )
    if nt == "call":
        name = node["name"]
        if name in PREDICATES:
            return _predicate_per_teacher(name, node["args"], ctx)
        if name in AGGREGATES:
            # nested sum(sum(...)) — collapse to a scalar broadcast
            scalar = _aggregate_sum(node["args"][0], ctx)
            return [scalar] * ctx.n_teachers
        raise ValueError(f"Chiamata non riconosciuta: {name}")
    if nt == "unop":
        return [-x for x in _per_teacher_terms(node["operand"], ctx)]
    if nt == "binop":
        op = node["op"]
        lhs = _per_teacher_terms(node["lhs"], ctx)
        rhs = _per_teacher_terms(node["rhs"], ctx)
        if op == "+":
            return [a + b for a, b in zip(lhs, rhs)]
        if op == "-":
            return [a - b for a, b in zip(lhs, rhs)]
        if op == "*":
            return [a * b for a, b in zip(lhs, rhs)]
        if op == "/":
            return [a / b for a, b in zip(lhs, rhs)]
    raise ValueError(f"Nodo non lowerable: {nt}")


def _per_teacher_array(name: str, ctx: CompileContext) -> list:
    return {
        "teacher_hours": ctx.teacher_hours,
        "teacher_max_hours": ctx.teacher_max_hours,
        "teacher_unused": ctx.teacher_unused,
        "teacher_n_classes": ctx.teacher_n_classes,
        "teacher_n_curricula": ctx.teacher_n_curricula,
        "teacher_weight": ctx.teacher_weight,
    }[name]


def _predicate_per_teacher(name: str, args: list[dict],
                           ctx: CompileContext) -> list:
    """Return a list of BoolVar (one per teacher) for the named
    predicate. Cache keyed by name + arg-constants."""
    arg_const = tuple(
        _eval_const_expr(a) for a in args
    ) if args else ()
    key = name + repr(arg_const)
    if key in ctx._pred_cache:
        return ctx._pred_cache[key]
    bvars: list = []
    for ti in range(ctx.n_teachers):
        b = ctx.model.NewBoolVar(f"pred_{key.replace(' ', '_')}_{ti}")
        if name == "over_max_hours":
            ctx.model.Add(
                ctx.teacher_hours[ti] > ctx.teacher_max_hours[ti]
            ).OnlyEnforceIf(b)
            ctx.model.Add(
                ctx.teacher_hours[ti] <= ctx.teacher_max_hours[ti]
            ).OnlyEnforceIf(b.Not())
        elif name == "under_min_hours":
            n = int(arg_const[0])
            ctx.model.Add(ctx.teacher_hours[ti] < n).OnlyEnforceIf(b)
            ctx.model.Add(ctx.teacher_hours[ti] >= n).OnlyEnforceIf(b.Not())
        elif name == "over_min_hours":
            n = int(arg_const[0])
            ctx.model.Add(ctx.teacher_hours[ti] >= n).OnlyEnforceIf(b)
            ctx.model.Add(ctx.teacher_hours[ti] < n).OnlyEnforceIf(b.Not())
        elif name == "cross_curricula":
            ctx.model.Add(ctx.teacher_n_curricula[ti] > 1).OnlyEnforceIf(b)
            ctx.model.Add(ctx.teacher_n_curricula[ti] <= 1).OnlyEnforceIf(b.Not())
        elif name == "single_curriculum":
            ctx.model.Add(ctx.teacher_n_curricula[ti] == 1).OnlyEnforceIf(b)
            ctx.model.Add(ctx.teacher_n_curricula[ti] != 1).OnlyEnforceIf(b.Not())
        elif name == "empty_teacher":
            ctx.model.Add(ctx.teacher_hours[ti] == 0).OnlyEnforceIf(b)
            ctx.model.Add(ctx.teacher_hours[ti] != 0).OnlyEnforceIf(b.Not())
        else:
            raise ValueError(f"Predicato non implementato: {name}")
        bvars.append(b)
    ctx._pred_cache[key] = bvars
    return bvars


def _eval_const_expr(node: dict) -> float:
    """Evaluate a subtree that is purely constant (validator checked)."""
    nt = node["node"]
    if nt == "num":
        return node["value"]
    if nt == "unop":
        return -_eval_const_expr(node["operand"])
    if nt == "binop":
        l = _eval_const_expr(node["lhs"])
        r = _eval_const_expr(node["rhs"])
        return {"+": l + r, "-": l - r, "*": l * r, "/": l / r}[node["op"]]
    raise ValueError(f"Argomento non costante: {nt}")


# ============================================================
# Preset library (DSL strings used by Phase A)
# ============================================================

# Each preset is (key, label, summary, dsl_expr).
PRESETS: list[tuple[str, str, str, str]] = [
    (
        "balance_curricula",
        "Bilanciamento per indirizzo (default)",
        "Distribuisce equamente il peso degli indirizzi fra i "
        "docenti: nessuno solo classi pesanti, nessuno solo "
        "leggere. Equivale al default storico.",
        "minimize 50 * total_unused_capacity "
        "+ 100 * total_n_classes "
        "- 5 * total_n_curricula "
        "+ 5000 * n_under_18 "
        "+ 50000 * n_under_10",
    ),
    (
        "concentrate_curriculum",
        "Concentrazione per indirizzo",
        "Ogni docente prevalentemente su un solo indirizzo: "
        "facilita la successiva decomposizione spettrale (cluster "
        "piu' puliti, meno docenti-ponte). Rigidizza pero' "
        "l'allocazione per emergenze.",
        "minimize 50 * total_unused_capacity "
        "+ 100 * total_n_classes "
        "+ 200 * sum(cross_curricula()) "
        "+ 5000 * n_under_18",
    ),
    (
        "balance_year",
        "Bilanciamento per anno",
        "Distribuisce equamente classi del biennio vs triennio "
        "(usa teacher_weight come proxy dell'eta' della classe). "
        "Riduce il rischio che un docente sia solo sul biennio "
        "(spesso percepito come piu' leggero).",
        "minimize 50 * total_unused_capacity "
        "+ 100 * total_n_classes "
        "+ sum(teacher_weight) "
        "+ 5000 * n_under_18",
    ),
    (
        "max_full_cattedre",
        "Massimizza cattedre piene (18h)",
        "Minimizza il numero di docenti con cattedra incompleta: "
        "soft 18h (peso alto), soft 10h (quasi-hard).",
        "minimize sum(under_min_hours(18)) * 5000 "
        "+ sum(under_min_hours(10)) * 50000 "
        "+ 50 * total_unused_capacity",
    ),
    (
        "minimize_fragmentation",
        "Minimizza frammentazione classi",
        "Riduce il numero di classi distinte per docente (pari "
        "ore -> piu' continuita' su poche classi). Buono per "
        "l'esperienza dello studente.",
        "minimize 200 * total_n_classes "
        "+ 50 * total_unused_capacity "
        "+ 5000 * n_under_18",
    ),
]


def get_preset(key: str) -> tuple[str, str, str, str] | None:
    for p in PRESETS:
        if p[0] == key:
            return p
    return None
