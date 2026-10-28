"""run_lns (verifica di Kepler, punto d):

* ``dc_value`` viene ricavato da ``best`` all'ingresso, quindi un
  ``dc_value`` vecchio (es. quello della Fase A dopo un solve settimanale)
  non produce cattedre con le ore settimanali sbagliate;
* se la soluzione iniziale non e' valida, un candidato valido viene
  accettato anche se costa di piu': la LNS ripara l'orario.
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


def _profs():
    P = {"M": {"classi": {"1A": {"Matematica": {"ore": 4}}},
               "min_free_days": 1},
         "I": {"classi": {"1A": {"Italiano": {"ore": 4}}},
               "min_free_days": 1},
         "E": {"classi": {"1A": {"Scienzemotorie": {"ore": 2}}},
               "min_free_days": 1}}
    for i in range(4):
        P[f"T{i}"] = {"classi": {"1A": {f"S{i}": {"ore": 4}}},
                      "min_free_days": 1}
    return P


def _valid_solution(P):
    import cp_sat_constraint_model as csm
    cfg = csm.ConstraintConfig(enforce_no_holes=True,
                               enforce_h3_presence_at_11=True,
                               enforce_motorie_pair=True,
                               enforce_math_italian_pair=True, locks=[])
    s = csm.MonolithicSolver(P, dc_value=None, config=cfg, scope=None)
    s.add_all_hard_constraints()
    s.add_class_no_overlap()
    for t in sorted(P):
        s.add_dsl_constraint(f'teacher_max_per_day("{t}", 5)',
                             level="phase_b")
        s.add_dsl_constraint(f'teacher_at_least_n_free_days("{t}", 1)',
                             level="phase_b")
    cs = cp_model.CpSolver()
    cs.parameters.max_time_in_seconds = 20
    cs.parameters.num_workers = 4
    cs.parameters.random_seed = 0
    st = cs.Solve(s.model)
    assert st in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    return {k: 1 for k, v in s.slot.items() if cs.Value(v)}


def _break_motorie(sol):
    """Rende non consecutive le 2 ore di motorie dello stesso giorno
    (scambio con un'altra lezione dello stesso giorno): stessi conteggi
    giornalieri, ma il validatore (H_B) rifiuta l'orario."""
    mot = sorted(k for k in sol if k[0] == "E")
    _, cl, s, d, h1 = mot[0]
    h2 = mot[1][4]
    assert mot[1][3] == d and abs(h2 - h1) == 1
    hi = max(h1, h2)
    lo = min(h1, h2)
    target = next(k for k in sorted(sol)
                  if k[3] == d and k[0] != "E" and abs(k[4] - lo) >= 2
                  and k[4] != hi)
    new = dict(sol)
    del new[("E", cl, s, d, hi)]
    del new[target]
    new[("E", cl, s, d, target[4])] = 1
    new[(target[0], target[1], target[2], d, hi)] = 1
    return new


def test_lns_repairs_invalid_start_and_ignores_stale_dc():
    import metaheuristics as meta
    P = _profs()
    good = _valid_solution(P)
    assert meta.is_hard_feasible(good, P)
    bad = _break_motorie(good)
    assert not meta.is_hard_feasible(bad, P)
    # dc_value "vecchio": tutto spostato di un giorno (come quello della
    # Fase A dopo che il settimanale ha scelto un'altra distribuzione).
    stale = {(p, cl, s, (d % 6) + 1): 1 for (p, cl, s, d, _h) in good}
    best, entries = meta.run_lns(bad, P, stale, 12, log=False, workers=4)
    assert meta.is_hard_feasible(best, P, verbose=True), entries[-5:]
    # ore settimanali per cattedra invariate
    for p, info in P.items():
        for cl, subjs in info["classi"].items():
            for s, sd in subjs.items():
                assert sum(v for k, v in best.items()
                           if k[:3] == (p, cl, s)) == sd["ore"]


def test_dc_from_solution():
    import metaheuristics as meta
    sol = {("A", "1A", "Mat", 1, 8): 1, ("A", "1A", "Mat", 1, 9): 1,
           ("A", "1A", "Mat", 2, 8): 1, ("B", "1A", "Ita", 2, 9): 0}
    assert meta.dc_from_solution(sol) == {("A", "1A", "Mat", 1): 2,
                                          ("A", "1A", "Mat", 2): 1}


def test_lns_accepts_costlier_valid_candidate_when_start_invalid(
        monkeypatch):
    """Partenza non valida ma «economica»: ogni candidato costa di piu'.
    Prima la LNS accettava solo candidati migliorativi e restituiva
    l'orario non valido; ora accetta il primo candidato valido."""
    import metaheuristics as meta
    P = _profs()
    bad = _break_motorie(_valid_solution(P))
    calls = {"n": 0}
    real = meta.compute_soft

    def fake(sol, profs, **kw):
        calls["n"] += 1
        v, br = real(sol, profs, **kw)
        return (0 if calls["n"] == 1 else 10**6 + v), br
    monkeypatch.setattr(meta, "compute_soft", fake)
    best, _ = meta.run_lns(bad, P, None, 8, log=False, workers=4)
    assert meta.is_hard_feasible(best, P, verbose=True)
