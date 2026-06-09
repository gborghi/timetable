"""Parser for the ``Vincoli`` xlsx/csv constraint language.

A single ``Vincoli`` sheet with a ``tipo_vincolo`` discriminator column lets a
non-technical user define constraints that map onto either the general DSL
(one ``GeneralConstraint`` expression) or a direct ORM insert. A ``raw_dsl``
row type is the power-user escape hatch (the DSL is fully general).

This module is PURE (no DB, no FastAPI): it validates a row and returns an
*intent* dict describing what to create. The endpoint translates intents into
actual constraint creations (DSL via the general-constraint path, ORM via the
constraint dispatcher), so the mapping logic stays unit-testable in isolation.

Intent shapes returned by :func:`map_row`:
  {"target": "dsl", "expression": str, "scope": str, "owner_name": str|None,
   "level": str, "weight": int, "note": str}
  {"target": "orm", "tipo": str, "entity": str, "name": str, "cells":
   [(day,hour),...], "level": str, "weight": int, "note": str}

Unsupported/malformed rows raise :class:`VincoloError` with a human message;
the caller collects these into a per-row ``errors`` list.
"""
from __future__ import annotations


class VincoloError(ValueError):
    """A row could not be mapped (bad tipo, missing field, bad day/hour)."""


# day token -> 1..6 (Italian abbreviations + full names + plain numbers)
_DAY_MAP = {
    "lun": 1, "lunedi": 1, "lunedì": 1, "1": 1,
    "mar": 2, "martedi": 2, "martedì": 2, "2": 2,
    "mer": 3, "mercoledi": 3, "mercoledì": 3, "3": 3,
    "gio": 4, "giovedi": 4, "giovedì": 4, "4": 4,
    "ven": 5, "venerdi": 5, "venerdì": 5, "5": 5,
    "sab": 6, "sabato": 6, "6": 6,
}

_LEVELS = {"hard", "soft", "preferred", "forbidden", "enforced"}

# tipo_vincolo -> ("dsl"|"orm", pragma-or-handler). Single source of the
# supported vocabulary; the endpoint and the template both read it.
VOCAB = (
    "indisponibilita", "giorno_libero", "pref_giorno_libero",
    "max_ore_giorno", "max_consecutive", "no_pomeriggio",
    "no_giorni_consecutivi", "no_buchi", "presenza_ora",
    "indisp_aula", "compresenza", "raw_dsl",
)


def _norm(v) -> str:
    return ("" if v is None else str(v)).strip()


def parse_day(tok) -> int:
    t = _norm(tok).lower()
    if t not in _DAY_MAP:
        raise VincoloError(f"giorno '{tok}' non valido (usa lun..sab o 1..6)")
    return _DAY_MAP[t]


def parse_hour(tok) -> int:
    t = _norm(tok)
    try:
        h = int(float(t))
    except (TypeError, ValueError):
        raise VincoloError(f"ora '{tok}' non numerica")
    return h


def _level(row) -> str:
    lv = _norm(row.get("livello")).lower() or "hard"
    if lv not in _LEVELS:
        raise VincoloError(
            f"livello '{lv}' non valido (hard/soft/preferred/forbidden/enforced)")
    return lv


def _weight(row) -> int:
    w = _norm(row.get("peso"))
    if not w:
        return 0
    try:
        return int(float(w))
    except (TypeError, ValueError):
        raise VincoloError(f"peso '{w}' non numerico")


def _require(row, field, tipo) -> str:
    v = _norm(row.get(field))
    if not v:
        raise VincoloError(f"'{tipo}' richiede la colonna '{field}'")
    return v


def _cell_range(row) -> list[tuple[int, int]]:
    """Expand (giorno, ora_da..ora_a) into [(day, hour), ...]. A blank
    giorno means 'all days'; a blank ora range means 'the whole day'."""
    giorno = _norm(row.get("giorno"))
    days = [parse_day(giorno)] if giorno else list(range(1, 7))
    oda, oa = _norm(row.get("ora_da")), _norm(row.get("ora_a"))
    if not oda and not oa:
        hours = list(range(8, 14))            # default school morning
    else:
        h0 = parse_hour(oda or oa)
        h1 = parse_hour(oa or oda)
        if h1 < h0:
            raise VincoloError(f"ora_a ({h1}) < ora_da ({h0})")
        hours = list(range(h0, h1 + 1))
    return [(d, h) for d in days for h in hours]


def _q(name: str) -> str:
    """Quote a name for embedding in a DSL string."""
    return '"' + name.replace('"', '') + '"'


def map_row(row: dict) -> dict:
    """Map one normalized ``Vincoli`` row to a creation intent.

    ``row`` keys are the lowercased column headers. Raises
    :class:`VincoloError` on any structural problem.
    """
    tipo = _norm(row.get("tipo_vincolo")).lower()
    if not tipo:
        raise VincoloError("colonna 'tipo_vincolo' mancante")
    if tipo not in VOCAB:
        raise VincoloError(
            f"tipo_vincolo '{tipo}' sconosciuto (ammessi: {', '.join(VOCAB)})")

    level = _level(row)
    weight = _weight(row)
    note = _norm(row.get("note"))
    entity = _norm(row.get("entita")).lower()
    name = _norm(row.get("nome"))

    def dsl(expr, scope, owner=None):
        return {"target": "dsl", "expression": expr, "scope": scope,
                "owner_name": owner, "level": level, "weight": weight,
                "note": note}

    if tipo == "raw_dsl":
        expr = _require(row, "dsl", tipo)
        return dsl(expr, entity or "global", name or None)

    if tipo == "indisponibilita":
        nm = _require(row, "nome", tipo)
        return {"target": "orm", "tipo": "indisponibilita",
                "entity": "docente", "name": nm, "cells": _cell_range(row),
                "level": level, "weight": weight, "note": note}

    if tipo == "indisp_aula":
        nm = _require(row, "nome", tipo)
        return {"target": "orm", "tipo": "indisp_aula", "entity": "aula",
                "name": nm, "cells": _cell_range(row), "level": level,
                "weight": weight, "note": note}

    if tipo == "giorno_libero":
        nm = _require(row, "nome", tipo)
        d = parse_day(_require(row, "giorno", tipo))
        return {"target": "orm", "tipo": "giorno_libero", "entity": "docente",
                "name": nm, "cells": [(d, h) for h in range(8, 14)],
                "level": "hard", "weight": 0, "note": note}

    if tipo == "pref_giorno_libero":
        nm = _require(row, "nome", tipo)
        d = parse_day(_require(row, "giorno", tipo))
        return {"target": "orm", "tipo": "pref_giorno_libero",
                "entity": "docente", "name": nm,
                "cells": [(d, h) for h in range(8, 14)],
                "level": "preferred", "weight": weight or 30, "note": note}

    if tipo == "compresenza":
        nm = _require(row, "nome", tipo)
        subj = _require(row, "materia", tipo)
        n = parse_hour(_require(row, "valore", tipo))
        return {"target": "orm", "tipo": "compresenza", "entity": "classe",
                "name": nm, "subject": subj, "n_teachers": n,
                "level": level, "weight": weight, "note": note}

    # DSL-pragma tipos
    if tipo == "max_ore_giorno":
        nm = _require(row, "nome", tipo)
        n = parse_hour(_require(row, "valore", tipo))
        return dsl(f"teacher_max_per_day({_q(nm)}, {n})", "teacher", nm)

    if tipo == "max_consecutive":
        nm = _require(row, "nome", tipo)
        n = parse_hour(_require(row, "valore", tipo))
        return dsl(f"teacher_max_consecutive({_q(nm)}, {n})", "teacher", nm)

    if tipo == "no_pomeriggio":
        thr = parse_hour(_require(row, "valore", tipo))
        nm = name or None
        if weight:
            expr = f"slot_after_hour_penalty({thr}, {weight})"
        else:
            expr = f"slot_after_hour_penalty({thr})"
        return dsl(expr, entity or "global", nm)

    if tipo == "no_giorni_consecutivi":
        nm = _require(row, "nome", tipo)
        return dsl(f"no_same_class_consecutive_days({_q(nm)})", "class", nm)

    if tipo == "no_buchi":
        nm = _require(row, "nome", tipo)
        return dsl(f"no_holes_class({_q(nm)})", "class", nm)

    if tipo == "presenza_ora":
        nm = _require(row, "nome", tipo)
        h = parse_hour(_require(row, "valore", tipo))
        return dsl(f"class_present_at_hour({_q(nm)}, {h})", "class", nm)

    raise VincoloError(f"tipo_vincolo '{tipo}' non ancora implementato")


def parse_rows(rows):
    """Map a list of normalized rows. Returns ``(intents, errors)`` where
    ``errors`` is a list of ``{"row": idx, "tipo": str, "error": msg}``
    (1-based row index for human reference)."""
    intents, errors = [], []
    for i, row in enumerate(rows, start=1):
        # skip fully-empty rows
        if not any(_norm(v) for v in (row or {}).values()):
            continue
        try:
            intents.append(map_row(row))
        except VincoloError as e:
            errors.append({
                "row": i, "tipo": _norm((row or {}).get("tipo_vincolo")),
                "error": str(e)})
    return intents, errors
