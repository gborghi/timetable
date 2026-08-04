"""Capienza delle aule speciali dentro la FASE ORARIO.

``Subject.required_kind`` obbliga una materia a finire in un'aula di
un certo tipo, ma i posti di quelle aule li conosce solo lo step aule,
che gira dopo e prende l'orario come dato. Il pragma
``subjects_max_concurrent_classes`` porta il tetto dei posti dentro la
fase orario, dove le lezioni si possono ancora spostare.

Copre i tre livelli: compilatore CP-SAT, valutatore post-hoc
(``general_dsl``, che e' cio' che usa il gate) e traduttore dai dati.
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
ENGINE = os.path.join(ROOT, "engine")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

cp_model = pytest.importorskip("ortools.sat.python.cp_model")
dsl_to_cpsat = pytest.importorskip("dsl_to_cpsat")
general_dsl = pytest.importorskip("general_dsl")


def _model_with_slots(classes, day=0, hour=0, subject="Motorie"):
    """Un BoolVar per (classe, slot) con la stessa materia."""
    m = cp_model.CpModel()
    slot = {}
    for cl in classes:
        k = (f"T{cl}", cl, subject, day, hour)
        slot[k] = m.NewBoolVar(f"x_{cl}")
    return m, slot


def _solve_all_on(m, slot):
    """Forza tutti gli slot a 1 e risolve: se il tetto morde, il
    modello e' INFEASIBLE."""
    for v in slot.values():
        m.Add(v == 1)
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = 5
    return s.Solve(m)


def test_tetto_hard_blocca_le_classi_eccedenti():
    m, slot = _model_with_slots(["1A", "1B", "1C"])
    c = dsl_to_cpsat.DSLConstraintCompiler(m, slot, is_hard=True)
    c.compile('subjects_max_concurrent_classes(2, "Motorie")')
    assert _solve_all_on(m, slot) == cp_model.INFEASIBLE


def test_entro_il_tetto_resta_ammissibile():
    m, slot = _model_with_slots(["1A", "1B"])
    c = dsl_to_cpsat.DSLConstraintCompiler(m, slot, is_hard=True)
    c.compile('subjects_max_concurrent_classes(2, "Motorie")')
    assert _solve_all_on(m, slot) in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_la_compresenza_occupa_un_posto_solo():
    """Due docenti sulla stessa classe/ora sono UNA classe in palestra,
    non due: contarli due volte renderebbe infattibile un orario
    perfettamente valido."""
    m = cp_model.CpModel()
    slot = {
        ("T1", "1A", "Motorie", 0, 0): m.NewBoolVar("a1"),
        ("T2", "1A", "Motorie", 0, 0): m.NewBoolVar("a2"),
        ("T3", "1B", "Motorie", 0, 0): m.NewBoolVar("b1"),
        ("T4", "1C", "Motorie", 0, 0): m.NewBoolVar("c1"),
    }
    c = dsl_to_cpsat.DSLConstraintCompiler(m, slot, is_hard=True)
    c.compile('subjects_max_concurrent_classes(2, "Motorie")')
    for v in slot.values():
        m.Add(v == 1)
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = 5
    # 3 classi distinte su 2 posti -> infattibile...
    assert s.Solve(m) == cp_model.INFEASIBLE

    m2 = cp_model.CpModel()
    slot2 = {
        ("T1", "1A", "Motorie", 0, 0): m2.NewBoolVar("a1"),
        ("T2", "1A", "Motorie", 0, 0): m2.NewBoolVar("a2"),
        ("T3", "1B", "Motorie", 0, 0): m2.NewBoolVar("b1"),
    }
    c2 = dsl_to_cpsat.DSLConstraintCompiler(m2, slot2, is_hard=True)
    c2.compile('subjects_max_concurrent_classes(2, "Motorie")')
    # ...ma 2 classi con 3 docenti no.
    assert _solve_all_on(m2, slot2) in (cp_model.OPTIMAL,
                                        cp_model.FEASIBLE)


def test_materie_diverse_condividono_lo_stesso_tetto():
    """Due materie che chiedono la stessa palestra competono per gli
    stessi posti."""
    m = cp_model.CpModel()
    slot = {
        ("T1", "1A", "Motorie", 0, 0): m.NewBoolVar("a"),
        ("T2", "1B", "Ed. fisica", 0, 0): m.NewBoolVar("b"),
        ("T3", "1C", "Motorie", 0, 0): m.NewBoolVar("c"),
    }
    c = dsl_to_cpsat.DSLConstraintCompiler(m, slot, is_hard=True)
    c.compile(
        'subjects_max_concurrent_classes(2, "Motorie", "Ed. fisica")')
    assert _solve_all_on(m, slot) == cp_model.INFEASIBLE


def test_altri_slot_non_sono_toccati():
    """Il tetto e' per (giorno, ora): tre classi in tre ore diverse
    stanno benissimo."""
    m = cp_model.CpModel()
    slot = {
        ("T1", "1A", "Motorie", 0, 0): m.NewBoolVar("a"),
        ("T2", "1B", "Motorie", 0, 1): m.NewBoolVar("b"),
        ("T3", "1C", "Motorie", 0, 2): m.NewBoolVar("c"),
    }
    c = dsl_to_cpsat.DSLConstraintCompiler(m, slot, is_hard=True)
    c.compile('subjects_max_concurrent_classes(1, "Motorie")')
    assert _solve_all_on(m, slot) in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_soft_paga_invece_di_vietare():
    m, slot = _model_with_slots(["1A", "1B", "1C"])
    c = dsl_to_cpsat.DSLConstraintCompiler(m, slot, is_hard=False, soft_weight=7)
    c.compile('subjects_max_concurrent_classes(2, "Motorie")')
    assert c.soft_cost_terms, "nessun termine di penalita' emesso"
    assert _solve_all_on(m, slot) in (cp_model.OPTIMAL, cp_model.FEASIBLE)


# ---------------- valutatore post-hoc (usato dal gate) -------------


def _world(lessons):
    return {"lessons": lessons}


def _L(cl, subj="Motorie", d=0, h=0, t="T"):
    return {"teacher": t, "class": cl, "subject": subj,
            "day": d, "hour": h}


def test_eval_posthoc_riconosce_la_violazione():
    expr = 'subjects_max_concurrent_classes(2, "Motorie")'
    ok = general_dsl.evaluate(
        general_dsl.parse(expr), _world([_L("1A"), _L("1B")]))
    ko = general_dsl.evaluate(
        general_dsl.parse(expr), _world([_L("1A"), _L("1B"), _L("1C")]))
    assert ok is True
    assert ko is False


def test_eval_posthoc_conta_le_classi_non_le_lezioni():
    expr = 'subjects_max_concurrent_classes(2, "Motorie")'
    world = _world([_L("1A", t="T1"), _L("1A", t="T2"),
                    _L("1B", t="T3")])
    assert general_dsl.evaluate(general_dsl.parse(expr), world) is True


# ---------------- traduttore dai dati ----------------


def test_translator_calcola_i_posti_e_salta_i_tipi_senza_aule():
    dsl_translator = pytest.importorskip("dsl_translator")

    class _Q:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class _Subj:
        def __init__(self, name, kind=None):
            self.name = name
            self.required_kind = kind

    class _Room:
        def __init__(self, kind, multi=False, mmax=1, plesso_id=None):
            self.kind = kind
            self.multi_class = multi
            self.multi_class_max = mmax
            # Real ``models.Classroom.plesso_id`` is nullable; the
            # translator's per-plesso pass reads it, and a double
            # missing the attribute raises instead of exercising the
            # "no plesso" path this test wants.
            self.plesso_id = plesso_id

    subjects = [_Subj("Scienze motorie", "palestra"),
                _Subj("Fisica", "lab_fisica"),
                _Subj("Italiano")]
    # 2 palestre da 2 posti = 4; nessun lab_fisica -> tipo saltato.
    rooms = [_Room("palestra", True, 2), _Room("palestra", True, 2),
             _Room("standard")]

    class _DB:
        def query(self, model):
            name = getattr(model, "__name__", "")
            # Dispatch by name and default to empty: the translator also
            # queries PlessoEntityPolicy/SchoolClass, and handing those
            # the room list made the fake answer questions it was never
            # asked.
            return _Q({"Subject": subjects, "Classroom": rooms}.get(name, []))

    import types
    fake = types.SimpleNamespace(
        Subject=type("Subject", (), {}),
        Classroom=type("Classroom", (), {}),
        SchoolClass=type("SchoolClass", (), {}),
        PlessoEntityPolicy=type("PlessoEntityPolicy", (), {}),
    )
    sys.modules.setdefault("webui", types.ModuleType("webui"))
    sys.modules["webui.backend"] = types.ModuleType("webui.backend")
    sys.modules["webui.backend.models"] = fake

    out = dsl_translator.special_room_capacity_to_dsl(_DB())
    assert len(out) == 1, out
    kind, clause = out[0]
    assert kind == "palestra"
    assert clause == (
        'subjects_max_concurrent_classes(4, "Scienze motorie")')
