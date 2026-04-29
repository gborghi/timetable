"""Logic-expression parser for "disjunctive availability" constraints.

Grammar (case-insensitive):

    expr     := or_expr
    or_expr  := and_expr ('OR' and_expr)*
    and_expr := not_expr ('AND' not_expr)*
    not_expr := 'NOT' not_expr | atom
    atom     := slot | '(' expr ')'
    slot     := day_code hour_num
    day_code := lun|mar|mer|gio|ven|sab
                | luned[ìi'] | marted[ìi'] | mercoled[ìi']
                | gioved[ìi'] | venerd[ìi'] | sabato
                | monday | tuesday | ... (English aliases also accepted)
    hour_num := 1..6   (ordinal: 1->8:00, 2->9:00, ..., 6->13:00)
                | 8..13 (absolute hour)

The parser produces a DNF (Disjunctive Normal Form) representation:

    DNF := [Clause1, Clause2, ...]                  ; OR over clauses
    Clause := [Literal1, Literal2, ...]             ; AND inside a clause
    Literal := {day:int, hour:int, negate:bool}     ; (1..6, 8..13, bool)

The constraint is satisfied (in the optimization sense) iff at least one
clause is fully active on the timetable -- i.e. every literal in it is
made true (positive => slot is unavailable; negative => slot is free).

Examples
--------

>>> parse_to_dnf("lun8 AND lun9").clauses
[[{'day': 1, 'hour': 8, 'negate': False},
  {'day': 1, 'hour': 9, 'negate': False}]]

>>> parse_to_dnf("(lun8 AND lun9) OR (mar8 AND mar9)").clauses
[[{'day': 1, 'hour': 8, 'negate': False},
  {'day': 1, 'hour': 9, 'negate': False}],
 [{'day': 2, 'hour': 8, 'negate': False},
  {'day': 2, 'hour': 9, 'negate': False}]]

>>> parse_to_dnf("NOT (lun8 OR lun9)").clauses
[[{'day': 1, 'hour': 8, 'negate': True},
  {'day': 1, 'hour': 9, 'negate': True}]]
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# ---------- Day codes ----------

DAY_ALIASES: dict[str, int] = {
    "lun": 1, "lunedi": 1, "lunedi'": 1, "monday": 1,
    "mar": 2, "martedi": 2, "martedi'": 2, "tuesday": 2,
    "mer": 3, "mercoledi": 3, "mercoledi'": 3, "wednesday": 3,
    "gio": 4, "giovedi": 4, "giovedi'": 4, "thursday": 4,
    "ven": 5, "venerdi": 5, "venerdi'": 5, "friday": 5,
    "sab": 6, "sabato": 6, "saturday": 6,
}

DAY_NAMES_IT = {1: "lun", 2: "mar", 3: "mer", 4: "gio", 5: "ven", 6: "sab"}
HOURS_BASE = 8     # ordinal 1 -> 08:00


def normalize_day(token: str) -> int | None:
    """Accepts both 'lun', 'Lunedi', 'Lunedì', 'monday' (case-insensitive)."""
    if not token:
        return None
    t = token.lower()
    # strip diacritics for a few common cases
    t = (t.replace("ì", "i").replace("í", "i")
           .replace("î", "i").replace("ï", "i"))
    return DAY_ALIASES.get(t)


def normalize_hour(num: int) -> int | None:
    """Accepts ordinal (1..6) or absolute (8..13)."""
    if 1 <= num <= 6:
        return HOURS_BASE + num - 1
    if 8 <= num <= 13:
        return num
    return None


# ---------- Tokenizer ----------


_TOKEN_RE = re.compile(
    r"""
    \s+                                                |
    (?P<lparen>\()                                     |
    (?P<rparen>\))                                     |
    (?P<and>(?:and|AND|And|&&|\&))                     |
    (?P<or>(?:or|OR|Or|\|\||\|))                       |
    (?P<not>(?:not|NOT|Not|\!))                        |
    (?P<slot>[A-Za-z][A-Za-z'à-ÿ]*\s*\d+)
    """,
    re.VERBOSE | re.UNICODE,
)


class LogicError(ValueError):
    pass


def _tokenize(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    pos = 0
    if text is None:
        return out
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m:
            raise LogicError(
                f"Token sconosciuto a colonna {pos+1}: '{text[pos:pos+20]}'"
            )
        pos = m.end()
        for k in ("lparen", "rparen", "and", "or", "not", "slot"):
            v = m.group(k)
            if v is None:
                continue
            if k == "slot":
                # Split into day_code (letters) and hour (digits).
                lett = re.match(r"[A-Za-z'à-ÿ]+", v).group(0)
                digits = v[len(lett):].strip()
                day = normalize_day(lett.replace(" ", ""))
                if day is None:
                    raise LogicError(
                        f"Giorno sconosciuto: '{lett}' (in '{v.strip()}')"
                    )
                try:
                    n = int(digits)
                except Exception:
                    raise LogicError(
                        f"Ora non valida: '{digits}' (in '{v.strip()}')"
                    )
                hour = normalize_hour(n)
                if hour is None:
                    raise LogicError(
                        f"Ora fuori range: {n} (ammessi 1..6 ordinali "
                        f"o 8..13 assoluti)"
                    )
                out.append(("SLOT", (day, hour)))
            else:
                out.append((k.upper(), v))
            break  # whitespace match has no group
    return out


# ---------- AST nodes ----------


@dataclass
class _Lit:
    day: int
    hour: int
    negate: bool = False


@dataclass
class _Node:
    kind: str           # 'lit' | 'and' | 'or' | 'not'
    lit: _Lit | None = None
    children: list["_Node"] = field(default_factory=list)


# ---------- Parser ----------


class _Parser:
    def __init__(self, tokens: list[tuple]):
        self.t = tokens
        self.i = 0

    def _peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def _eat(self, kind=None):
        tok = self._peek()
        if tok == (None, None):
            raise LogicError("fine espressione inattesa")
        if kind is not None and tok[0] != kind:
            raise LogicError(f"atteso {kind}, trovato {tok[0]}")
        self.i += 1
        return tok

    def parse(self):
        if not self.t:
            raise LogicError("espressione vuota")
        node = self._or()
        if self.i != len(self.t):
            raise LogicError(f"token extra: {self.t[self.i:]}")
        return node

    def _or(self):
        left = self._and()
        while self._peek()[0] == "OR":
            self._eat("OR")
            right = self._and()
            left = _Node("or", children=[left, right])
        return left

    def _and(self):
        left = self._not()
        while self._peek()[0] == "AND":
            self._eat("AND")
            right = self._not()
            left = _Node("and", children=[left, right])
        return left

    def _not(self):
        if self._peek()[0] == "NOT":
            self._eat("NOT")
            child = self._not()
            return _Node("not", children=[child])
        return self._atom()

    def _atom(self):
        tok = self._peek()
        if tok[0] == "LPAREN":
            self._eat("LPAREN")
            node = self._or()
            if self._peek()[0] != "RPAREN":
                raise LogicError("manca ')'")
            self._eat("RPAREN")
            return node
        if tok[0] == "SLOT":
            self._eat("SLOT")
            day, hour = tok[1]
            return _Node("lit", lit=_Lit(day=day, hour=hour, negate=False))
        raise LogicError(f"atteso slot o '(', trovato {tok}")


# ---------- DNF transformation ----------


def _push_not(node: _Node) -> _Node:
    """Push NOT down to literals (De Morgan)."""
    if node.kind == "not":
        child = node.children[0]
        if child.kind == "lit":
            return _Node("lit", lit=_Lit(day=child.lit.day,
                                         hour=child.lit.hour,
                                         negate=not child.lit.negate))
        if child.kind == "not":
            return _push_not(child.children[0])
        if child.kind == "and":
            # NOT (A AND B) = NOT A OR NOT B
            return _Node("or", children=[
                _push_not(_Node("not", children=[c])) for c in child.children
            ])
        if child.kind == "or":
            return _Node("and", children=[
                _push_not(_Node("not", children=[c])) for c in child.children
            ])
    if node.kind in ("and", "or"):
        return _Node(node.kind, children=[_push_not(c) for c in node.children])
    return node


def _to_dnf(node: _Node) -> list[list[_Lit]]:
    """Returns list of clauses, each a list of literals (AND inside, OR outside)."""
    if node.kind == "lit":
        return [[node.lit]]
    if node.kind == "or":
        out: list[list[_Lit]] = []
        for c in node.children:
            out.extend(_to_dnf(c))
        return out
    if node.kind == "and":
        # Cartesian product of child DNFs.
        product: list[list[_Lit]] = [[]]
        for c in node.children:
            child_dnf = _to_dnf(c)
            new_product: list[list[_Lit]] = []
            for left in product:
                for right in child_dnf:
                    new_product.append(left + right)
            product = new_product
        # de-dup literals inside each clause
        cleaned: list[list[_Lit]] = []
        for clause in product:
            seen = set()
            uniq: list[_Lit] = []
            for lit in clause:
                key = (lit.day, lit.hour, lit.negate)
                if key in seen:
                    continue
                seen.add(key)
                uniq.append(lit)
            cleaned.append(uniq)
        return cleaned
    raise LogicError(f"DNF: nodo inatteso {node.kind}")


# ---------- Public API ----------


@dataclass
class ParsedExpression:
    expression: str
    clauses: list[list[dict]]  # JSON-friendly DNF
    pretty: str                # canonical text


def _lit_to_str(lit: dict) -> str:
    label = DAY_NAMES_IT.get(lit["day"], "?") + str(lit["hour"])
    return ("NOT " + label) if lit.get("negate") else label


def dnf_to_pretty(clauses: list[list[dict]]) -> str:
    if not clauses:
        return ""
    out_clauses = []
    for clause in clauses:
        if not clause:
            continue
        if len(clause) == 1:
            out_clauses.append(_lit_to_str(clause[0]))
        else:
            out_clauses.append("(" + " AND ".join(
                _lit_to_str(l) for l in clause) + ")")
    return " OR ".join(out_clauses)


def parse_to_dnf(expression: str) -> ParsedExpression:
    """Parse `expression` into DNF. Raises LogicError on syntax issues."""
    tokens = _tokenize(expression or "")
    if not tokens:
        return ParsedExpression(expression=expression or "", clauses=[],
                                pretty="")
    ast = _Parser(tokens).parse()
    ast = _push_not(ast)
    dnf = _to_dnf(ast)
    clauses_json = [
        [{"day": l.day, "hour": l.hour, "negate": l.negate} for l in clause]
        for clause in dnf
    ]
    pretty = dnf_to_pretty(clauses_json)
    return ParsedExpression(expression=expression or "",
                            clauses=clauses_json,
                            pretty=pretty)


# ---------- Evaluation against an availability set ----------


def evaluate_against_unavailable(clauses: list[list[dict]],
                                  unavail_set: set[tuple[int, int]]) -> bool:
    """Returns True if the constraint is satisfied: i.e. at least one
    clause is fully active given `unavail_set` (a set of (day, hour) the
    target is unavailable on).

    Positive literal `(day, hour, negate=False)` holds iff `(day, hour)`
    is in unavail_set. Negative literal holds iff NOT in unavail_set.
    """
    for clause in clauses:
        ok = True
        for lit in clause:
            present = (lit["day"], lit["hour"]) in unavail_set
            if lit.get("negate"):
                if present:
                    ok = False
                    break
            else:
                if not present:
                    ok = False
                    break
        if ok:
            return True
    return False
