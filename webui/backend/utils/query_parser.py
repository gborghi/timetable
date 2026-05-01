"""Tiny query DSL evaluator. Lives entirely in Python so the same
language is used regardless of which list endpoint calls it.

Grammar (informal):

    expr      := term ( ('AND'|'OR'|'and'|'or') term )*
    term      := func | comparison | '(' expr ')'
    func      := ident '(' arg ( ',' arg )* ')'
    comparison:= ident op value
    op        := '=' | '!=' | '<' | '<=' | '>' | '>=' | 'contains'
                  | 'startswith' | 'endswith' | 'in'
    value     := number | string | bool | '[' value ',' ... ']'
    string    := bare_word | quoted

Each entity (teachers, classes, classrooms, subjects) supplies a
*record-getter*: a callable that takes (record, field_name) -> Python
value. The evaluator is row-by-row -- the parser is small (regex-based)
and the dataset is small enough (<200 records typical) that filtering
in Python is cheaper than translating the AST to SQLAlchemy clauses.

Sort spec syntax:

    sort='field1,desc:field2,asc:field3'

(`asc` is the default if omitted)."""
from __future__ import annotations

import re
from typing import Any, Callable, Iterable

# Tokenizer ---------------------------------------------------------------

_TOKEN_RE = re.compile(
    r"""
    \s+                                       |
    (?P<lparen>\()                            |
    (?P<rparen>\))                            |
    (?P<lbrack>\[)                            |
    (?P<rbrack>\])                            |
    (?P<comma>,)                              |
    (?P<op>(<=|>=|!=|=|<|>))                  |
    (?P<dq>"(?:[^"\\]|\\.)*")                 |
    (?P<sq>'(?:[^'\\]|\\.)*')                 |
    # Word: any run of letters / digits / underscore / accented letters
    # that contains AT LEAST ONE non-digit character. This lets us
    # tokenize bare values that start with a digit (e.g. "3B",
    # "3B_scientifico", "1A") as a single word so queries like
    # `classe = 3B_scientifico` work without quoting. Pure-digit
    # tokens fall through to `num` below.
    (?P<word>[A-Za-z0-9_À-ſ]*[A-Za-z_À-ſ][A-Za-z0-9_À-ſ]*) |
    (?P<num>-?\d+(?:\.\d+)?)
    """,
    re.VERBOSE,
)


class QueryError(ValueError):
    pass


def _tokenize(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m:
            raise QueryError(
                f"Token sconosciuto a colonna {pos+1}: '{text[pos:pos+20]}'"
            )
        pos = m.end()
        for k, v in m.groupdict().items():
            if v is None:
                continue
            if k in ("dq", "sq"):
                out.append(("STRING", v[1:-1]))
            elif k == "num":
                out.append(("NUM", v))
            elif k == "word":
                low = v.lower()
                if low in ("and", "or"):
                    out.append(("LOGOP", low))
                elif low in ("contains", "startswith", "endswith", "in"):
                    out.append(("WORDOP", low))
                elif low in ("true", "false"):
                    out.append(("BOOL", low == "true"))
                else:
                    out.append(("IDENT", v))
            elif k == "op":
                out.append(("OP", v))
            elif k == "lparen":
                out.append(("LP", "("))
            elif k == "rparen":
                out.append(("RP", ")"))
            elif k == "lbrack":
                out.append(("LB", "["))
            elif k == "rbrack":
                out.append(("RB", "]"))
            elif k == "comma":
                out.append(("COMMA", ","))
            break  # whitespace match (no group set) just advances pos
    return out


# Parser ------------------------------------------------------------------


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]]):
        self.tokens = tokens
        self.i = 0

    def _peek(self):
        return self.tokens[self.i] if self.i < len(self.tokens) else (None, None)

    def _eat(self, kind: str | None = None, value: str | None = None):
        tok = self._peek()
        if tok == (None, None):
            raise QueryError("Fine inattesa della query")
        if kind is not None and tok[0] != kind:
            raise QueryError(f"Atteso {kind}, trovato {tok[0]} ({tok[1]})")
        if value is not None and tok[1] != value:
            raise QueryError(f"Atteso '{value}', trovato '{tok[1]}'")
        self.i += 1
        return tok

    def parse(self):
        if not self.tokens:
            return ("CONST_TRUE",)
        node = self._parse_or()
        if self.i != len(self.tokens):
            raise QueryError(
                f"Token in piu\\` dopo la query: {self.tokens[self.i:]}"
            )
        return node

    def _parse_or(self):
        left = self._parse_and()
        while self._peek() == ("LOGOP", "or"):
            self._eat()
            right = self._parse_and()
            left = ("OR", left, right)
        return left

    def _parse_and(self):
        left = self._parse_term()
        while self._peek() == ("LOGOP", "and"):
            self._eat()
            right = self._parse_term()
            left = ("AND", left, right)
        return left

    def _parse_term(self):
        tok = self._peek()
        if tok == ("LP", "("):
            self._eat()
            inner = self._parse_or()
            self._eat("RP")
            return inner
        if tok[0] != "IDENT":
            raise QueryError(f"Atteso identificatore, trovato {tok}")
        # function call?
        if self.i + 1 < len(self.tokens) and self.tokens[self.i + 1] == ("LP", "("):
            return self._parse_func()
        # comparison
        return self._parse_comparison()

    def _parse_func(self):
        ident = self._eat("IDENT")[1]
        self._eat("LP")
        args = [self._parse_value()]
        while self._peek() == ("COMMA", ","):
            self._eat()
            args.append(self._parse_value())
        self._eat("RP")
        return ("FUNC", ident.lower(), args)

    def _parse_comparison(self):
        ident = self._eat("IDENT")[1]
        tok = self._peek()
        if tok[0] == "OP":
            op = self._eat()[1]
        elif tok[0] == "WORDOP":
            op = self._eat()[1]
        else:
            raise QueryError(f"Atteso operatore, trovato {tok}")
        if op == "in":
            self._eat("LB")
            vals = [self._parse_value()]
            while self._peek() == ("COMMA", ","):
                self._eat()
                vals.append(self._parse_value())
            self._eat("RB")
            return ("CMP", ident, op, vals)
        return ("CMP", ident, op, self._parse_value())

    def _parse_value(self):
        tok = self._peek()
        if tok[0] == "STRING":
            return self._eat()[1]
        if tok[0] == "NUM":
            v = self._eat()[1]
            return float(v) if "." in v else int(v)
        if tok[0] == "BOOL":
            return self._eat()[1]
        if tok[0] == "IDENT":
            # bare word treated as string
            return self._eat()[1]
        raise QueryError(f"Atteso valore, trovato {tok}")


def parse_query(text: str):
    text = (text or "").strip()
    if not text:
        return ("CONST_TRUE",)
    return _Parser(_tokenize(text)).parse()


# Evaluator ---------------------------------------------------------------


def _coerce_pair(a, b):
    """Try to coerce a/b to comparable types. Numbers -> float; otherwise
    string compare (case-insensitive)."""
    if a is None:
        a = ""
    if b is None:
        b = ""
    if isinstance(a, (int, float)) and isinstance(b, str):
        try:
            b = float(b)
        except ValueError:
            a = str(a)
    elif isinstance(b, (int, float)) and isinstance(a, str):
        try:
            a = float(a)
        except ValueError:
            b = str(b)
    if isinstance(a, str) and isinstance(b, str):
        return a.lower(), b.lower()
    return a, b


def _eval_cmp(left, op, right):
    if op == "in":
        right_lc = [str(v).lower() if isinstance(v, str) else v for v in right]
        if isinstance(left, str):
            return left.lower() in right_lc
        return left in right_lc
    a, b = _coerce_pair(left, right)
    if op == "=":  return a == b
    if op == "!=": return a != b
    if op == "<":  return a < b
    if op == "<=": return a <= b
    if op == ">":  return a > b
    if op == ">=": return a >= b
    if op == "contains":   return str(b) in str(a)
    if op == "startswith": return str(a).startswith(str(b))
    if op == "endswith":   return str(a).endswith(str(b))
    raise QueryError(f"Operatore non supportato: {op}")


def evaluate(node, record, fields: dict[str, Callable[[Any], Any]],
             funcs: dict[str, Callable[..., bool]]):
    if node[0] == "CONST_TRUE":
        return True
    if node[0] == "AND":
        return evaluate(node[1], record, fields, funcs) and \
               evaluate(node[2], record, fields, funcs)
    if node[0] == "OR":
        return evaluate(node[1], record, fields, funcs) or \
               evaluate(node[2], record, fields, funcs)
    if node[0] == "FUNC":
        name = node[1]
        args = node[2]
        fn = funcs.get(name)
        if fn is None:
            raise QueryError(f"Funzione sconosciuta: {name}")
        return fn(record, *args)
    if node[0] == "CMP":
        _, ident, op, value = node
        getter = fields.get(ident)
        if getter is None:
            raise QueryError(f"Campo sconosciuto: {ident}")
        left = getter(record)
        return _eval_cmp(left, op, value)
    raise QueryError(f"Nodo AST non gestito: {node[0]}")


# Sort spec ---------------------------------------------------------------


def parse_sort(spec: str) -> list[tuple[str, bool]]:
    """Parse 'a,desc:b:c,asc' -> [('a', True), ('b', False), ('c', False)]."""
    out: list[tuple[str, bool]] = []
    if not spec:
        return out
    for part in spec.split(":"):
        part = part.strip()
        if not part:
            continue
        if "," in part:
            field, direction = part.split(",", 1)
            desc = direction.strip().lower() == "desc"
        else:
            field, desc = part, False
        out.append((field.strip(), desc))
    return out


def sort_records(records: list, sort_spec: list[tuple[str, bool]],
                 fields: dict[str, Callable[[Any], Any]]):
    """Stable multi-level sort, applying the LAST spec first (Python's
    sort is stable, so applying primary last preserves the secondary
    ordering)."""
    out = list(records)
    for field, desc in reversed(sort_spec):
        getter = fields.get(field)
        if getter is None:
            raise QueryError(f"Campo sort sconosciuto: {field}")
        out.sort(
            key=lambda r, g=getter: ("" if g(r) is None else g(r)),
            reverse=desc,
        )
    return out


# Helpers for building (fields, funcs) dicts ------------------------------


def _to_lower(v):
    return v.lower() if isinstance(v, str) else v
