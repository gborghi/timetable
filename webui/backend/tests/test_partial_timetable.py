"""Punto 7a di Kepler: modalita' «orario parziale».

Il modello settimanale con ``ConstraintConfig(partial=True)`` sostituisce
``sum(slot) == ore`` con ``sum(slot) + miss == ore`` (penalita' forte su
``miss``): invece di fallire restituisce un orario e l'elenco esatto delle
ore non collocate.
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


def _solve(P, partial, extra=None):
    import cp_sat_constraint_model as csm
    from backend.optimization import _week_objective_terms
    cfg = csm.ConstraintConfig(locks=[], partial=partial)
    s = csm.MonolithicSolver(P, dc_value=None, config=cfg, scope=None)
    s.add_all_hard_constraints()
    s.add_class_no_overlap()
    for t in sorted(P):
        s.add_dsl_constraint(f'teacher_max_per_day("{t}", 5)',
                             level="phase_b")
        n = P[t].get("min_free_days", 0)
        if n:
            s.add_dsl_constraint(
                f'teacher_at_least_n_free_days("{t}", {n})',
                level="phase_b")
    if extra:
        extra(s)
    s.model.Minimize(sum(_week_objective_terms(s)))
    cs = cp_model.CpSolver()
    cs.parameters.max_time_in_seconds = 30
    cs.parameters.num_workers = 8
    return s, cs, cs.Solve(s.model)


def _proto7():
    """Istanza di proto7.py: il docente M ha 26 ore, ma con un giorno
    libero e 5 ore al giorno ne puo' fare al piu' 25."""
    P = {"M": {"classi": {f"1{c}": {"Matematica": {"ore": 4}}
                          for c in "ABCDE"}, "min_free_days": 1}}
    P["M"]["classi"]["1F"] = {"Matematica": {"ore": 6}}
    for c in "ABCDEF":
        for i in range(4):
            P[f"T{c}{i}"] = {"classi": {f"1{c}": {f"S{i}": {"ore": 6}}},
                             "min_free_days": 0}
    return P


def test_proto7_normal_infeasible_partial_one_missing():
    P = _proto7()
    _s, cs, st = _solve(P, partial=False)
    assert st == cp_model.INFEASIBLE, cs.StatusName(st)
    s, cs, st = _solve(P, partial=True)
    assert st in (cp_model.OPTIMAL, cp_model.FEASIBLE), cs.StatusName(st)
    rep = s.missing_report(cs)
    assert sum(r["missing"] for r in rep) == 1, rep
    assert all(r["teacher"] == "M" for r in rep)


def test_partial_motorie_missing_is_even():
    """Motorie 2 h ma la classe puo' farla solo in un'ora: il parziale deve
    togliere 2 ore (non 1, che renderebbe motorie infeasible)."""
    P = {"E": {"classi": {"1A": {"Scienzemotorie": {"ore": 2}}},
               "min_free_days": 0}}
    for i in range(5):
        P[f"T{i}"] = {"classi": {"1A": {f"S{i}": {"ore": 5}}},
                      "min_free_days": 0}

    def only_one_hour(s):
        # E puo' lavorare solo il lunedi' alle 8
        s.model.Add(sum(v for k, v in s.slot.items()
                        if k[0] == "E" and (k[3], k[4]) != (1, 8)) == 0)
    s, cs, st = _solve(P, partial=True, extra=only_one_hour)
    assert st in (cp_model.OPTIMAL, cp_model.FEASIBLE), cs.StatusName(st)
    rep = s.missing_report(cs)
    assert rep == [{"teacher": "E", "class": "1A",
                    "subject": "Scienzemotorie", "missing": 2}], rep


def test_partial_mat_double_follows_placed_hours():
    """Matematica 4 h con al piu' 1 ora al giorno: in parziale restano 1 ora
    collocata (la doppia non serve) e 3 mancanti, invece di INFEASIBLE."""
    import metaheuristics as meta
    P = {"M": {"classi": {"1A": {"Matematica": {"ore": 4}}},
               "min_free_days": 0}}
    for i in range(5):
        P[f"T{i}"] = {"classi": {"1A": {f"S{i}": {"ore": 5}}},
                      "min_free_days": 0}

    def cap(s):
        for d in meta.DAYS:
            s.model.Add(sum(v for k, v in s.slot.items()
                            if k[0] == "M" and k[3] == d) <= 1)
    _s, cs, st = _solve(P, partial=False, extra=cap)
    # normal mode: the weekly double is impossible
    assert st == cp_model.INFEASIBLE
    s, cs, st = _solve(P, partial=True, extra=cap)
    assert st in (cp_model.OPTIMAL, cp_model.FEASIBLE), cs.StatusName(st)
    rep = s.missing_report(cs)
    assert rep and rep[0]["missing"] in (3,), rep


def test_partial_off_is_byte_identical():
    """Senza ``partial`` nessuna variabile ``miss`` e nessun termine."""
    import cp_sat_constraint_model as csm
    P = _proto7()
    s = csm.MonolithicSolver(P, dc_value=None,
                             config=csm.ConstraintConfig(locks=[]),
                             scope=None)
    assert s.miss == {}
    assert s.miss_objective_terms() == []
