"""Plessi dentro la Phase B (il solver di giornata).

Fino a ieri i vincoli di plesso vivevano solo nella fase di
assegnazione delle aule, che pero' arriva DOPO: quando decide le aule
le ore sono gia' congelate, e un docente messo nei due plessi a ore
contigue non ha nessuna assegnazione di aula che possa salvarlo. La
Phase B doveva quindi imparare a leggere il plesso da qualcosa che
esiste gia' mentre le ore sono ancora libere -- la CLASSE, che sta
nella sua aula base tutta la settimana.

Questi test fissano quel comportamento sul modello CP-SAT: la coppia
di ore vietata deve rendere il modello INFEASIBLE quando la si forza,
e non deve toccare nulla quando la regola non si applica.
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "engine"))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)


def _data(**kw):
    import plessi_constraints as pc
    d = pc.PlessiData(
        classroom_to_plesso={"Sede_1A": 1, "Sede_1B": 1, "Succ_2A": 2},
        teacher_name_to_id={"Rossi": 10, "Bianchi": 11},
        class_name_to_id={"1A": 100, "1B": 101, "2A": 200},
        home_classroom_by_class={"1A": "Sede_1A", "1B": "Sede_1B",
                                 "2A": "Succ_2A"},
    )
    for k, v in kw.items():
        setattr(d, k, v)
    return d


def _break_rule(**kw):
    """La regola della scuola su due plessi: trasferimento possibile
    solo attraverso l'intervallo, fra la 3a e la 4a ora (ore legacy
    10 -> 11)."""
    import plessi_constraints as pc
    base = dict(id=1, from_plesso_id=1, to_plesso_id=2,
                entity_kind="teacher", entity_id=None,
                allowed_break_only=True,
                break_start_hour=10, break_end_hour=11,
                symmetric=True)
    base.update(kw)
    return pc.CommutingRule(**base)


def _solve(model, forced):
    from ortools.sat.python import cp_model
    for var in forced:
        model.Add(var == 1)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 2.0
    return solver.Solve(model), cp_model


# ---------- la mappa classe -> plesso ----------

def test_pins_come_from_the_home_classroom():
    import plessi_constraints as pc
    pins = pc.class_plesso_pins(_data())
    assert pins == {"1A": 1, "1B": 1, "2A": 2}


def test_explicit_policy_overrides_the_home_classroom():
    """Se qualcuno ha dichiarato dove sta la classe, quella vince
    sull'aula base."""
    import plessi_constraints as pc
    d = _data(entity_policies=[pc.EntityPolicy(
        id=1, entity_kind="class", entity_id=200,
        policy="single_plesso_total", plesso_id=1)])
    assert pc.class_plesso_pins(d)["2A"] == 1


def test_class_without_a_home_room_is_absent_not_guessed():
    """Sede ignota = nessun vincolo. Indovinare "plesso 1" vieterebbe
    orari validi sulla base di un dato mancante."""
    import plessi_constraints as pc
    d = _data(home_classroom_by_class={"1A": "Sede_1A"})
    pins = pc.class_plesso_pins(d)
    assert "2A" not in pins and pins == {"1A": 1}


# ---------- coppie di ore ----------

def test_break_rule_forbids_a_change_inside_the_morning():
    """Rossi in 1A (sede) alla 1a ora e in 2A (succursale) alla 2a:
    il trasferimento non passa dall'intervallo, va vietato."""
    from ortools.sat.python import cp_model
    import plessi_constraints as pc

    model = cp_model.CpModel()
    a, b = model.NewBoolVar("a"), model.NewBoolVar("b")
    slot = {("Rossi", "1A", "Mat", 1, 8): a,
            ("Rossi", "2A", "Mat", 1, 9): b}
    d = _data(commuting_rules=[_break_rule()])
    n = pc.add_plesso_constraints_phase_b(
        model, slot, d, day=1, hours=range(8, 14),
        class_to_plesso=pc.class_plesso_pins(d))
    assert n >= 1
    status, cp = _solve(model, [a, b])
    assert status == cp.INFEASIBLE


def test_break_rule_allows_a_change_across_the_break():
    """Sede fino alla 3a ora (h=10), succursale dalla 4a (h=11): e'
    esattamente il caso che la regola deve lasciar passare."""
    from ortools.sat.python import cp_model
    import plessi_constraints as pc

    model = cp_model.CpModel()
    a, b = model.NewBoolVar("a"), model.NewBoolVar("b")
    slot = {("Rossi", "1A", "Mat", 1, 10): a,
            ("Rossi", "2A", "Mat", 1, 11): b}
    d = _data(commuting_rules=[_break_rule()])
    pc.add_plesso_constraints_phase_b(
        model, slot, d, day=1, hours=range(8, 14),
        class_to_plesso=pc.class_plesso_pins(d))
    status, cp = _solve(model, [a, b])
    assert status in (cp.OPTIMAL, cp.FEASIBLE)


def test_non_adjacent_hours_are_checked_too():
    """Il motivo per cui `_pair_violates_rule` non guarda solo h+1:
    1a ora in sede, 3a in succursale, buco in mezzo. Il cambio non
    avviene comunque all'intervallo, e guardando solo le ore contigue
    sarebbe passato liscio."""
    from ortools.sat.python import cp_model
    import plessi_constraints as pc

    model = cp_model.CpModel()
    a, b = model.NewBoolVar("a"), model.NewBoolVar("b")
    slot = {("Rossi", "1A", "Mat", 1, 8): a,
            ("Rossi", "2A", "Mat", 1, 10): b}
    d = _data(commuting_rules=[_break_rule()])
    pc.add_plesso_constraints_phase_b(
        model, slot, d, day=1, hours=range(8, 14),
        class_to_plesso=pc.class_plesso_pins(d))
    status, cp = _solve(model, [a, b])
    assert status == cp.INFEASIBLE


def test_min_gap_counts_the_free_hours_between():
    """`min_gap_hours=2` vuole due ore libere in mezzo: a distanza 2
    (una sola libera) e' ancora troppo poco, a distanza 3 va bene."""
    import plessi_constraints as pc
    rule = _break_rule(allowed_break_only=False, min_gap_hours=2)
    assert pc._pair_violates_rule(rule, 8, 9) is True
    assert pc._pair_violates_rule(rule, 8, 10) is True
    assert pc._pair_violates_rule(rule, 8, 11) is False


def test_same_plesso_pair_is_never_constrained():
    from ortools.sat.python import cp_model
    import plessi_constraints as pc

    model = cp_model.CpModel()
    a, b = model.NewBoolVar("a"), model.NewBoolVar("b")
    slot = {("Rossi", "1A", "Mat", 1, 8): a,
            ("Rossi", "1B", "Mat", 1, 9): b}
    d = _data(commuting_rules=[_break_rule()])
    n = pc.add_plesso_constraints_phase_b(
        model, slot, d, day=1, hours=range(8, 14),
        class_to_plesso=pc.class_plesso_pins(d))
    assert n == 0
    status, cp = _solve(model, [a, b])
    assert status in (cp.OPTIMAL, cp.FEASIBLE)


def test_other_days_are_not_read():
    """Il solver di giornata riceve la vista 5-tupla completa ma deve
    guardare solo il proprio giorno."""
    import plessi_constraints as pc
    from ortools.sat.python import cp_model

    model = cp_model.CpModel()
    a, b = model.NewBoolVar("a"), model.NewBoolVar("b")
    slot = {("Rossi", "1A", "Mat", 1, 8): a,
            ("Rossi", "2A", "Mat", 2, 9): b}   # giorno diverso
    d = _data(commuting_rules=[_break_rule()])
    n = pc.add_plesso_constraints_phase_b(
        model, slot, d, day=1, hours=range(8, 14),
        class_to_plesso=pc.class_plesso_pins(d))
    assert n == 0


def test_no_plessi_configured_is_a_no_op():
    import plessi_constraints as pc
    from ortools.sat.python import cp_model

    model = cp_model.CpModel()
    slot = {("Rossi", "1A", "Mat", 1, 8): model.NewBoolVar("a")}
    d = _data()  # nessuna regola, nessuna policy
    assert pc.add_plesso_constraints_phase_b(
        model, slot, d, day=1, hours=range(8, 14),
        class_to_plesso=pc.class_plesso_pins(d)) == 0


# ---------- policy di entita' sul docente ----------

def test_single_plesso_per_day_confines_the_teacher():
    from ortools.sat.python import cp_model
    import plessi_constraints as pc

    model = cp_model.CpModel()
    a, b = model.NewBoolVar("a"), model.NewBoolVar("b")
    slot = {("Rossi", "1A", "Mat", 1, 10): a,
            ("Rossi", "2A", "Mat", 1, 11): b}
    d = _data(entity_policies=[pc.EntityPolicy(
        id=1, entity_kind="teacher", entity_id=None,
        policy="single_plesso_per_day")])
    pc.add_plesso_constraints_phase_b(
        model, slot, d, day=1, hours=range(8, 14),
        class_to_plesso=pc.class_plesso_pins(d))
    # Attraverso l'intervallo sarebbe ammesso da una regola di
    # trasferimento, ma la policy dice un plesso al giorno e basta.
    status, cp = _solve(model, [a, b])
    assert status == cp.INFEASIBLE


def test_single_plesso_total_pins_to_the_named_site():
    from ortools.sat.python import cp_model
    import plessi_constraints as pc

    model = cp_model.CpModel()
    a, b = model.NewBoolVar("a"), model.NewBoolVar("b")
    slot = {("Rossi", "1A", "Mat", 1, 8): a,     # plesso 1
            ("Rossi", "2A", "Mat", 1, 12): b}    # plesso 2
    d = _data(entity_policies=[pc.EntityPolicy(
        id=1, entity_kind="teacher", entity_id=10,
        policy="single_plesso_total", plesso_id=1)])
    pc.add_plesso_constraints_phase_b(
        model, slot, d, day=1, hours=range(8, 14),
        class_to_plesso=pc.class_plesso_pins(d))
    status, cp = _solve(model, [b])
    assert status == cp.INFEASIBLE, "la lezione nel plesso 2 va vietata"


def test_policy_on_one_teacher_leaves_the_others_alone():
    from ortools.sat.python import cp_model
    import plessi_constraints as pc

    model = cp_model.CpModel()
    a, b = model.NewBoolVar("a"), model.NewBoolVar("b")
    slot = {("Bianchi", "1A", "Mat", 1, 8): a,
            ("Bianchi", "2A", "Mat", 1, 12): b}
    d = _data(entity_policies=[pc.EntityPolicy(
        id=1, entity_kind="teacher", entity_id=10,   # Rossi, non Bianchi
        policy="single_plesso_total", plesso_id=1)])
    pc.add_plesso_constraints_phase_b(
        model, slot, d, day=1, hours=range(8, 14),
        class_to_plesso=pc.class_plesso_pins(d))
    status, cp = _solve(model, [a, b])
    assert status in (cp.OPTIMAL, cp.FEASIBLE)


# ---------- caricamento dal DB ----------

def test_load_plessi_data_reads_home_classrooms(app_with_temp_db):
    """`home_classroom_by_class` e' cio' che rende utilizzabile la
    mappa in Phase B: se il loader non la riempie, `class_plesso_pins`
    torna vuota e il vincolo non viene mai emesso."""
    import plessi_constraints as pc
    from backend import models

    _app, TestSession = app_with_temp_db
    with TestSession() as db:
        p = models.Plesso(name="Succursale", code="SUC")
        db.add(p)
        db.flush()
        room = models.Classroom(name="Aula 2A", capacity=30,
                                plesso_id=p.id)
        db.add(room)
        db.add(models.SchoolClass(name="2A"))
        db.flush()
        db.add(models.ClassroomClassPreference(
            classroom_id=room.id, class_name="2A", is_home=True))
        db.add(models.PlessoCommutingRule(
            from_plesso_id=p.id, to_plesso_id=p.id,
            entity_kind="teacher", min_gap_hours=1))
        db.commit()

        data = pc.load_plessi_data(db)

    assert data.home_classroom_by_class.get("2A") == "Aula 2A"
    assert pc.class_plesso_pins(data).get("2A") is not None


def test_build_plessi_ctx_is_none_without_plessi(app_with_temp_db):
    """Nessun plesso configurato -> nessun contesto -> il solver resta
    identico a prima. E' il caso della stragrande maggioranza delle
    scuole, e non deve costare nulla."""
    import cpsat_v2_timetable as cv2

    _app, TestSession = app_with_temp_db
    with TestSession() as db:
        assert cv2.build_plessi_ctx(db) is None


@pytest.mark.parametrize("h_a,h_b", [(8, 9), (9, 8)])
def test_pair_rule_is_order_independent(h_a, h_b):
    import plessi_constraints as pc
    assert pc._pair_violates_rule(_break_rule(), h_a, h_b) is True


# ---------- fino in fondo: il solver di giornata vero ----------

def _profs_two_plessi():
    """Un docente che insegna in entrambi i plessi, e due colleghi che
    riempiono le classi. 4 ore al giorno per classe: le ore della
    giornata sono 8..11, quindi ce n'e' abbastanza sia prima che dopo
    l'intervallo (h=10 -> h=11)."""
    return {
        "Pendolare": {
            "classi": {"1A": {"Mat": {"ore": 6}},
                       "2A": {"Mat": {"ore": 6}}},
            "glibero": [6, 5, 4],
        },
        "SoloSede": {
            "classi": {"1A": {"Ita": {"ore": 6}}},
            "glibero": [6, 5, 4],
        },
        "SoloSucc": {
            "classi": {"2A": {"Ita": {"ore": 6}}},
            "glibero": [6, 5, 4],
        },
    }


def _run_day_solver(plessi_ctx):
    import cpsat_v2_timetable as cv2  # type: ignore
    profs = _profs_two_plessi()
    classes_v, triples, class_profs = cv2.build_indices(profs)
    dc_value = cv2.solve_phase_a(
        profs, classes_v, triples, class_profs,
        time_limit=5, workers=2, log=False)
    sol = {}
    for d in cv2.DAYS:
        out, _st = cv2.solve_phase_b_for_day(
            d, profs, classes_v, triples, class_profs, dc_value,
            time_limit=5, workers=2, log=False,
            plessi_ctx=plessi_ctx)
        if out:
            sol.update({k: v for k, v in out.items() if v})
    return sol


def _illegal_transitions(sol, pins, rule):
    """Coppie (giorno, h_a, h_b) in cui il Pendolare cambia plesso in
    un modo che la regola vieta."""
    import plessi_constraints as pc
    by_day: dict[int, list[tuple[int, int]]] = {}
    for (t, cl, _s, d, h) in sol:
        if t != "Pendolare":
            continue
        pl = pins.get(cl)
        if pl is not None:
            by_day.setdefault(d, []).append((h, pl))
    bad = []
    for d, cells in by_day.items():
        cells.sort()
        for i, (h_a, pl_a) in enumerate(cells):
            for (h_b, pl_b) in cells[i + 1:]:
                if pl_a != pl_b and pc._pair_violates_rule(rule, h_a, h_b):
                    bad.append((d, h_a, h_b))
    return bad


@pytest.mark.slow
def test_day_solver_respects_the_commuting_rule_end_to_end():
    """La prova che conta: Phase A + Phase B veri, e nell'orario
    prodotto il docente pendolare non cambia mai sede fuori
    dall'intervallo."""
    import plessi_constraints as pc
    d = _data(commuting_rules=[_break_rule()])
    pins = pc.class_plesso_pins(d)
    sol = _run_day_solver((d, pins))
    assert sol, "il solver non ha prodotto nulla"
    bad = _illegal_transitions(sol, pins, _break_rule())
    assert not bad, f"cambi di plesso vietati: {bad}"


def _forced_interleave_day():
    """Una giornata in cui il cambio di sede e' OBBLIGATO.

    Le due classi -- in plessi diversi -- hanno quattro ore ciascuna
    quel giorno, dalle 8 alle 11 (meno non si puo': il solver esige la
    4a ora occupata per chi ha lezione). Il Pendolare ne tiene due per
    classe: non potendo stare in due posti alla stessa ora occupa
    tutte e quattro le ore, e l'unico modo di rispettare l'intervallo
    sarebbe tenere le ore di una sede fino alle 10 e quelle dell'altra
    dalle 11 in poi -- ma dalle 11 in poi ce n'e' una sola. Il cambio
    fuori intervallo e' quindi inevitabile.

    Serve un caso costruito cosi' perche' il controllo negativo sia
    una prova e non una coincidenza: su un'istanza libera il solver
    puo' benissimo raggruppare le ore da solo, e allora il confronto
    con/senza vincolo non dimostrerebbe niente.
    """
    profs = {
        "Pendolare": {"classi": {"1A": {"Mat": {"ore": 2}},
                                 "2A": {"Mat": {"ore": 2}}},
                      "glibero": []},
        "SoloSede": {"classi": {"1A": {"Ita": {"ore": 2}}},
                     "glibero": []},
        "SoloSucc": {"classi": {"2A": {"Ita": {"ore": 2}}},
                     "glibero": []},
    }
    dc_value = {
        ("Pendolare", "1A", "Mat", 1): 2,
        ("Pendolare", "2A", "Mat", 1): 2,
        ("SoloSede", "1A", "Ita", 1): 2,
        ("SoloSucc", "2A", "Ita", 1): 2,
    }
    return profs, dc_value


def _solve_forced_day(plessi_ctx):
    import cpsat_v2_timetable as cv2  # type: ignore
    profs, dc_value = _forced_interleave_day()
    classes_v, triples, class_profs = cv2.build_indices(profs)
    out, _st = cv2.solve_phase_b_for_day(
        1, profs, classes_v, triples, class_profs, dc_value,
        time_limit=5, workers=2, log=False, plessi_ctx=plessi_ctx)
    return out


def test_forced_interleave_is_feasible_without_the_plessi_context():
    """Controllo negativo: senza contesto la giornata si risolve, ed e'
    proprio la soluzione che attraversa i plessi fra 1a e 2a ora."""
    import plessi_constraints as pc
    out = _solve_forced_day(None)
    assert out is not None, "la giornata deve essere risolvibile di per se'"
    placed = {k for k, v in out.items() if v}
    d = _data(commuting_rules=[_break_rule()])
    pins = pc.class_plesso_pins(d)
    assert _illegal_transitions(placed, pins, _break_rule()), (
        "l'istanza doveva forzare il cambio di sede fuori intervallo")


def test_forced_interleave_becomes_infeasible_with_the_plessi_context():
    """E con il contesto la stessa giornata non si risolve piu': il
    vincolo morde davvero dentro il solver, non solo nell'helper."""
    import plessi_constraints as pc
    d = _data(commuting_rules=[_break_rule()])
    out = _solve_forced_day((d, pc.class_plesso_pins(d)))
    assert out is None, (
        "il solver ha trovato una soluzione dove il Pendolare cambia "
        "plesso fra la 1a e la 2a ora: il vincolo non e' stato applicato")
