"""Unit tests for the Vincoli xlsx constraint-language parser (pure mapper).

Crucially, every DSL expression the parser emits must PARSE cleanly via the
real grammar -- otherwise the endpoint would create un-loadable rules.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "engine"))
WEBUI = os.path.normpath(os.path.join(HERE, "..", ".."))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
for _p in (ENGINE, WEBUI, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest  # noqa: E402

from backend.routers import _vincoli_parser as vp  # noqa: E402


def test_dsl_pragma_rows_map_and_parse():
    import general_dsl as gd
    cases = [
        {"tipo_vincolo": "max_ore_giorno", "nome": "Rossi Mario",
         "valore": "5", "livello": "hard"},
        {"tipo_vincolo": "max_consecutive", "nome": "Bianchi", "valore": "4"},
        {"tipo_vincolo": "no_pomeriggio", "entita": "classe", "nome": "1A",
         "valore": "14", "livello": "soft", "peso": "50"},
        {"tipo_vincolo": "no_giorni_consecutivi", "nome": "3B"},
        {"tipo_vincolo": "no_buchi", "nome": "2C"},
        {"tipo_vincolo": "presenza_ora", "nome": "2C", "valore": "11"},
        {"tipo_vincolo": "raw_dsl", "entita": "global",
         "dsl": "forall t in teachers: teacher_max_consecutive(t.name, 4)"},
    ]
    for row in cases:
        intent = vp.map_row(row)
        assert intent["target"] == "dsl", intent
        # the emitted expression must parse with the real grammar
        gd.parse(intent["expression"])

    # spot-check a couple of concrete expressions
    assert vp.map_row(cases[0])["expression"] == 'teacher_max_per_day("Rossi Mario", 5)'
    assert vp.map_row(cases[2])["expression"] == 'slot_after_hour_penalty(14, 50)'
    assert vp.map_row(cases[3])["expression"] == 'no_same_class_consecutive_days("3B")'


def test_indisponibilita_expands_cells():
    intent = vp.map_row({
        "tipo_vincolo": "indisponibilita", "entita": "docente",
        "nome": "Rossi", "giorno": "ven", "ora_da": "8", "ora_a": "13",
        "livello": "hard"})
    assert intent["target"] == "orm" and intent["tipo"] == "indisponibilita"
    assert intent["name"] == "Rossi"
    assert intent["cells"] == [(5, h) for h in range(8, 14)]  # ven 8..13


def test_indisponibilita_blank_day_is_all_days():
    intent = vp.map_row({
        "tipo_vincolo": "indisponibilita", "nome": "X",
        "ora_da": "8", "ora_a": "8"})
    days = {d for d, _h in intent["cells"]}
    assert days == {1, 2, 3, 4, 5, 6}


def test_giorno_libero_full_day():
    intent = vp.map_row({
        "tipo_vincolo": "giorno_libero", "nome": "Y", "giorno": "mer"})
    assert intent["tipo"] == "giorno_libero"
    assert intent["cells"] == [(3, h) for h in range(8, 14)]


def test_compresenza():
    intent = vp.map_row({
        "tipo_vincolo": "compresenza", "nome": "4A", "materia": "Scienze",
        "valore": "2"})
    assert intent["tipo"] == "compresenza" and intent["n_teachers"] == 2
    assert intent["subject"] == "Scienze"


def test_errors_collected_and_empty_rows_skipped():
    rows = [
        {"tipo_vincolo": "max_ore_giorno", "nome": "A", "valore": "5"},  # ok
        {"tipo_vincolo": "bogus", "nome": "B"},                          # bad tipo
        {"tipo_vincolo": "max_ore_giorno", "nome": "C"},                 # missing valore
        {"tipo_vincolo": "indisponibilita", "nome": "D", "giorno": "xyz"},  # bad day
        {},                                                              # empty -> skipped
        {"tipo_vincolo": "", "nome": ""},                               # empty -> skipped
    ]
    intents, errors = vp.parse_rows(rows)
    assert len(intents) == 1
    assert len(errors) == 3
    assert {e["row"] for e in errors} == {2, 3, 4}


def test_bad_level_and_hour_raise():
    with pytest.raises(vp.VincoloError):
        vp.map_row({"tipo_vincolo": "max_ore_giorno", "nome": "A",
                    "valore": "5", "livello": "kinda-hard"})
    with pytest.raises(vp.VincoloError):
        vp.map_row({"tipo_vincolo": "presenza_ora", "nome": "A",
                    "valore": "non-numerico"})
