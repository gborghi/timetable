"""Il passo aule legge il preset Alternativa. Il parallel group non si tocca.

Il nome del gruppo e la stanza non stanno nel motore: il test li
legge dal JSON, oppure li mette nel dato che passa al solver.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "engine"))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

PRESET = (
    Path(__file__).resolve().parents[3] / "data" / "preset_alternativa.json"
)


def _dato():
    return json.loads(PRESET.read_text(encoding="utf-8"))


def _ancora(dato=None) -> str:
    return str((dato or _dato())["in_simultanea_con"])


def _kind_scelto(dato=None) -> str:
    dato = dato or _dato()
    scelta = dato["modalita_scelta"]
    mode = next(m for m in dato["modalita"] if m["id"] == scelta)
    return str(mode.get("required_kind") or "")


def _con_modalita(mode_id, **fields):
    dato = _dato()
    dato["modalita_scelta"] = mode_id
    for mode in dato["modalita"]:
        mode["selezionata"] = mode["id"] == mode_id
        if mode["id"] == mode_id:
            mode.update(fields)
    return dato


def _lezione(subject, *, cl="1A", day=1, hour=8, home_room="",
             shares_room=False, teacher="T"):
    row = {
        "teacher": teacher,
        "class": cl,
        "subject": subject,
        "day": day,
        "hour": hour,
        "n_students": 10,
    }
    if home_room:
        row["home_room"] = home_room
    if shares_room:
        row["shares_room"] = True
    return row


def _solve(lessons, rooms, **kwargs):
    from classroom_assignment import solve_classroom_assignment
    kwargs.setdefault("time_limit_s", 5)
    kwargs.setdefault("workers", 1)
    return solve_classroom_assignment(lessons, rooms, **kwargs)


def test_default_del_file_aula_del_kind_in_simultanea():
    """La modalità già selezionata vale solo per chi condivide lo slot
    con la materia del file. Lo slot non si sposta: due aule diverse.
    """
    dato = _dato()
    ancora = _ancora(dato)
    kind = _kind_scelto(dato)
    assert kind
    gruppo = "Gruppo"
    lessons = [
        _lezione(ancora, teacher="Tirc", home_room="StdA"),
        _lezione(gruppo, teacher="Talt", home_room="StdA"),
        _lezione("Italiano", cl="1B", teacher="Tita"),
        # Stessa materia del gruppo, ma non in simultanea: non è il preset.
        _lezione(gruppo, day=2, hour=9, teacher="Talt"),
    ]
    raw = json.dumps(lessons, sort_keys=True)
    rooms = [
        {"name": "StdA", "kind": "standard", "capacity": 30},
        {"name": "StdB", "kind": "standard", "capacity": 30},
        {"name": "Spec", "kind": kind, "capacity": 30},
    ]
    mapping, status = _solve(lessons, rooms)
    assert mapping is not None, status
    assert json.dumps(lessons, sort_keys=True) == raw
    assert mapping[("1A", gruppo, 1, 8)] == "Spec"
    assert mapping[("1A", ancora, 1, 8)] == "StdA"
    assert mapping[("1B", "Italiano", 1, 8)] == "StdB"
    assert mapping[("1A", gruppo, 2, 9)] in {"StdA", "StdB"}

    from classroom_assignment import greedy_classroom_assignment
    greedy = greedy_classroom_assignment(lessons, rooms, preset=dato)
    assert greedy[("1A", gruppo, 1, 8)] == "Spec"
    assert greedy[("1A", gruppo, 2, 9)] in {"StdA", "StdB"}


def test_solo_aula_ordinaria_il_file_rende_inellegibile():
    """Senza un'aula del kind scelto il passo lo dice. Non è un orario
    da sistemare: manca il tipo di aula del dato.
    """
    ancora = _ancora()
    lessons = [
        _lezione(ancora, teacher="Tirc"),
        _lezione("Gruppo", teacher="Talt"),
    ]
    rooms = [{"name": "StdA", "kind": "standard", "capacity": 30}]
    mapping, status = _solve(lessons, rooms)
    assert mapping is None
    assert status.startswith("NO_ELIGIBLE")


def test_file_assente_non_cambia_il_passo(monkeypatch, tmp_path):
    """Senza il file le due lezioni sono un normale sdoppiamento: una
    aula ordinaria basta a non renderle strutturalmente ineleggibili.
    Con il file, la stessa aula dà NO_ELIGIBLE (test sopra).
    """
    import classroom_assignment as ca
    monkeypatch.setattr(
        ca, "preset_alternativa_path", lambda: tmp_path / "mancante.json")
    ancora = _ancora()
    lessons = [
        _lezione(ancora, teacher="Tirc"),
        _lezione("Gruppo", teacher="Talt"),
    ]
    rooms = [{"name": "StdA", "kind": "standard", "capacity": 30}]
    mapping, status = _solve(lessons, rooms)
    assert mapping is not None, status
    assert not status.startswith("NO_ELIGIBLE")
    assert set(mapping.values()) == {"StdA"}
    assert ("1A", "Gruppo", 1, 8) in mapping or ("1A", ancora, 1, 8) in mapping
    assert ("1A", "Gruppo", 1, 8) not in mapping or (
        ("1A", ancora, 1, 8) not in mapping)


def test_file_assente_due_aule_libere(monkeypatch, tmp_path):
    import classroom_assignment as ca
    monkeypatch.setattr(
        ca, "preset_alternativa_path", lambda: tmp_path / "mancante.json")
    ancora = _ancora()
    lessons = [
        _lezione(ancora, teacher="Tirc"),
        _lezione("Gruppo", teacher="Talt"),
    ]
    rooms = [
        {"name": "StdA", "kind": "standard", "capacity": 30},
        {"name": "StdB", "kind": "standard", "capacity": 30},
    ]
    mapping, status = _solve(lessons, rooms)
    assert mapping is not None, status
    assert mapping[("1A", "Gruppo", 1, 8)] in {"StdA", "StdB"}
    assert mapping[("1A", ancora, 1, 8)] in {"StdA", "StdB"}
    assert mapping[("1A", "Gruppo", 1, 8)] != mapping[("1A", ancora, 1, 8)]


def test_preset_spento_o_illeggibile(monkeypatch, tmp_path):
    import classroom_assignment as ca
    spento = tmp_path / "spento.json"
    dato = _dato()
    dato["attivo"] = False
    spento.write_text(json.dumps(dato), encoding="utf-8")
    monkeypatch.setattr(ca, "preset_alternativa_path", lambda: spento)
    lessons = [
        _lezione(_ancora(), teacher="Tirc"),
        _lezione("Gruppo", teacher="Talt"),
    ]
    rooms = [{"name": "StdA", "kind": "standard", "capacity": 30},
             {"name": "StdB", "kind": "standard", "capacity": 30}]
    mapping, status = _solve(lessons, rooms)
    assert mapping is not None, status
    assert mapping[("1A", "Gruppo", 1, 8)] in {"StdA", "StdB"}

    rotto = tmp_path / "rotto.json"
    rotto.write_text("{", encoding="utf-8")
    monkeypatch.setattr(ca, "preset_alternativa_path", lambda: rotto)
    mapping, status = _solve(lessons, rooms)
    assert mapping is not None, status


def test_aula_fissa_usa_la_stanza_nominata_nel_dato():
    nome = "Stanza Nord"
    preset = _con_modalita("aula_fissa", home_room=nome, required_kind="")
    ancora = _ancora(preset)
    lessons = [
        _lezione(ancora, teacher="Tirc", home_room="StdA"),
        _lezione("Gruppo", teacher="Talt", home_room="StdA"),
    ]
    rooms = [
        {"name": nome, "kind": "standard", "capacity": 30},
        {"name": "StdA", "kind": "standard", "capacity": 30},
    ]
    mapping, status = _solve(lessons, rooms, preset=preset)
    assert mapping is not None, status
    assert mapping[("1A", "Gruppo", 1, 8)] == nome
    assert mapping[("1A", ancora, 1, 8)] == "StdA"


def test_aula_fissa_senza_nome_non_toglie_il_pin():
    preset = _con_modalita("aula_fissa", home_room="", required_kind="")
    ancora = _ancora(preset)
    lessons = [
        _lezione(ancora, teacher="Tirc"),
        _lezione("Gruppo", teacher="Talt", home_room="Aula 1"),
    ]
    rooms = [
        {"name": "Aula 1", "kind": "standard", "capacity": 30,
         "unavailability": {(1, 8)}},
        {"name": "Aula 2", "kind": "standard", "capacity": 30},
        {"name": "Aula 3", "kind": "standard", "capacity": 30},
    ]
    mapping, status = _solve(lessons, rooms, preset=preset)
    assert mapping is None
    assert status.startswith("NO_ELIGIBLE")


def test_aule_libere_qualsiasi_aula_libera():
    preset = _con_modalita("aule_libere", required_kind="", home_room="")
    ancora = _ancora(preset)
    lessons = [
        _lezione(ancora, teacher="Tirc"),
        _lezione("Gruppo", teacher="Talt", home_room="Aula 1"),
    ]
    rooms = [
        {"name": "Aula 1", "kind": "standard", "capacity": 30,
         "unavailability": {(1, 8)}},
        {"name": "Aula 2", "kind": "standard", "capacity": 30},
        {"name": "Aula 3", "kind": "standard", "capacity": 30},
    ]
    mapping, status = _solve(lessons, rooms, preset=preset)
    assert mapping is not None, status
    assert mapping[("1A", "Gruppo", 1, 8)] in {"Aula 2", "Aula 3"}
    assert mapping[("1A", ancora, 1, 8)] in {"Aula 2", "Aula 3"}
    assert (mapping[("1A", "Gruppo", 1, 8)]
            != mapping[("1A", ancora, 1, 8)])


def test_il_nome_del_gruppo_non_basta():
    """Una materia che si chiama come il gruppo, ma non è in simultanea
    con l'ancora del file, non riceve il vincolo.
    """
    lessons = [_lezione("Alternativa", day=2, hour=9)]
    rooms = [{"name": "StdA", "kind": "standard", "capacity": 30}]
    mapping, status = _solve(lessons, rooms)
    assert mapping is not None, status
    assert mapping[("1A", "Alternativa", 2, 9)] == "StdA"


def test_compresenza_non_e_il_gruppo():
    from classroom_assignment import stamp_preset_rooms
    dato = _dato()
    ancora = _ancora(dato)
    lessons = [
        _lezione(ancora, teacher="Tirc"),
        _lezione("Sostegno", teacher="Tsos", shares_room=True),
    ]
    stamped, reserved = stamp_preset_rooms(lessons, dato)
    assert stamped[1] is lessons[1]
    assert lessons[1].get("required_kind", "") == ""
    assert reserved == frozenset()


def test_kind_del_dato_non_e_riservato_nel_codice():
    from classroom_assignment import (
        _can_host,
        _normalize_classroom,
        stamp_preset_rooms,
    )
    dato = _dato()
    kind = _kind_scelto(dato)
    room = _normalize_classroom(
        {"name": "Spec", "kind": kind, "capacity": 30})
    ordinary = _lezione("Italiano", cl="1B")
    _, reserved = stamp_preset_rooms(
        [_lezione(_ancora(dato), teacher="Tirc"),
         _lezione("Gruppo", teacher="Talt")],
        dato,
    )
    assert kind in reserved
    assert not _can_host(room, ordinary, reserved)
    # Senza il dato il kind non è speciale: il codice non lo elenca.
    assert _can_host(room, ordinary)


def test_joint_legge_lo_stesso_file():
    from ortools.sat.python import cp_model

    from classroom_assignment import add_joint_room_vars

    dato = _dato()
    ancora = _ancora(dato)
    kind = _kind_scelto(dato)
    cell_a = ("1A", ancora, 1, 8)
    cell_g = ("1A", "Gruppo", 1, 8)
    cells = {
        cell_a: {"teacher": "Tirc", "n_students": 10},
        cell_g: {"teacher": "Talt", "n_students": 10},
    }
    rooms = [
        {"name": "StdA", "kind": "standard", "capacity": 30},
        {"name": "Spec", "kind": kind, "capacity": 30},
    ]
    model = cp_model.CpModel()
    x, _terms, info = add_joint_room_vars(
        model, {cell_a: 1, cell_g: 1}, cells, rooms)
    assert (cell_g, "Spec") in x
    assert (cell_g, "StdA") not in x
    assert (cell_a, "Spec") not in x
    assert not info["no_room_cells"]
    assert cells[cell_g].get("required_kind", "") == ""

    model_off = cp_model.CpModel()
    x_off, _, _ = add_joint_room_vars(
        model_off, {cell_a: 1, cell_g: 1}, cells, rooms, preset=False)
    assert (cell_g, "StdA") in x_off
