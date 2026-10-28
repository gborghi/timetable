"""Punto 6 di Kepler: le ore di potenziamento nel modello settimanale
occupano il docente come una lezione (tetto 5 h/giorno, giorno libero,
indisponibilita'), non cadono su ore inesistenti (sabato corto) e la
soluzione le restituisce (``pot_solution`` / ``metrics['potenziamento']``).
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
for p in (os.path.join(REPO_ROOT, "webui"), os.path.join(REPO_ROOT, "engine")):
    if p not in sys.path:
        sys.path.insert(0, p)

from ortools.sat.python import cp_model  # noqa: E402


def _build(monkeypatch, *, free_day_pref=None):
    import cp_sat_constraint_model as csm
    # sabato a 4 ore (Tab Ore)
    monkeypatch.setitem(csm.SLOTS_PER_DAY, 6, 4)
    # Docente P: 18 ore in 4 classi + 2 ore di potenziamento.
    P = {"P": {"classi": {"1A": {"Mat": {"ore": 5}},
                          "2A": {"Mat": {"ore": 5}},
                          "3A": {"Mat": {"ore": 4}},
                          "4A": {"Mat": {"ore": 4}}},
               "min_free_days": 1}}
    for c in ("1A", "2A", "3A", "4A"):
        for i in range(4):
            P[f"T{c}{i}"] = {"classi": {c: {f"S{i}": {"ore": 5}}},
                             "min_free_days": 1}
    cfg = csm.ConstraintConfig(
        enforce_no_holes=False, enforce_h3_presence_at_11=False,
        locks=[],
        potenziamento_assignments=[{"teacher_name": "P", "n_hours": 2,
                                    "subject": "Potenziamento"}])
    s = csm.MonolithicSolver(P, dc_value=None, config=cfg, scope=None)
    s.add_potenziamento_assignments()
    s.add_all_hard_constraints()
    s.add_class_no_overlap()
    s.add_dsl_constraint('teacher_max_per_day("P", 5)', level="phase_b")
    s.add_dsl_constraint('teacher_at_least_n_free_days("P", 1)',
                         level="phase_b")
    return P, s


def test_potenziamento_counts_as_busy(monkeypatch):
    P, s = _build(monkeypatch)
    m = s.model
    # spinge il potenziamento verso le ore «vietate»: giorni pieni, sabato
    # pomeriggio, giorno libero
    m.Maximize(sum(v for (t, d, h), v in s.pot_slot.items()
                   if d == 6 or h >= 12))
    cs = cp_model.CpSolver()
    cs.parameters.max_time_in_seconds = 30
    cs.parameters.num_workers = 8
    st = cs.Solve(m)
    assert st in (cp_model.OPTIMAL, cp_model.FEASIBLE), cs.StatusName(st)
    pot = {k for k, v in s.pot_slot.items() if cs.Value(v)}
    assert len(pot) == 2
    # niente potenziamento nelle ore inesistenti del sabato (12, 13)
    assert not any(d == 6 and h in (12, 13) for (_t, d, h) in pot)
    load = {d: 0 for d in s.days}
    for (t, _c, _s, d, _h), v in s.slot.items():
        if t == "P" and cs.Value(v):
            load[d] += 1
    for (_t, d, _h) in pot:
        load[d] += 1
    assert max(load.values()) <= 5, load
    # giorno libero vero: nessuna lezione e nessun potenziamento
    assert any(v == 0 for v in load.values()), load


def test_free_day_counts_potenziamento(monkeypatch):
    """Il giorno libero non puo' essere «riempito» dal potenziamento."""
    P, s = _build(monkeypatch)
    m = s.model
    # Giorno 1 senza lezioni di P ma con potenziamento: deve violare il
    # giorno libero se tutti gli altri giorni sono occupati.
    for d in s.days:
        if d != 1:
            m.Add(sum(v for k, v in s.slot.items()
                      if k[0] == "P" and k[3] == d) >= 1)
    m.Add(sum(v for k, v in s.slot.items()
              if k[0] == "P" and k[3] == 1) == 0)
    m.Add(sum(v for (t, d, h), v in s.pot_slot.items() if d == 1) >= 1)
    cs = cp_model.CpSolver()
    cs.parameters.max_time_in_seconds = 20
    st = cs.Solve(m)
    assert st == cp_model.INFEASIBLE, cs.StatusName(st)


def test_forbid_potenziamento_cells(monkeypatch):
    P, s = _build(monkeypatch)
    n = s.forbid_potenziamento_cells([("P", d, h) for d in s.days
                                      for h in s.hours if h != 8])
    assert n > 0
    cs = cp_model.CpSolver()
    cs.parameters.max_time_in_seconds = 20
    st = cs.Solve(s.model)
    assert st in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    pot = [k for k, v in s.pot_slot.items() if cs.Value(v)]
    assert pot and all(h == 8 for (_t, _d, h) in pot)


def test_pot_solution_helper(monkeypatch):
    from backend.optimization import _pot_solution
    P, s = _build(monkeypatch)
    cs = cp_model.CpSolver()
    cs.parameters.max_time_in_seconds = 20
    st = cs.Solve(s.model)
    assert st in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    rows = _pot_solution(s, cs)
    assert len(rows) == 2 and all(r["teacher"] == "P" for r in rows)
