"""Il modello settimanale (``MonolithicSolver`` con ``dc_value=None``) e il
validatore ``metaheuristics.is_hard_feasible`` devono descrivere lo stesso
insieme di orari ammessi (revisione Kepler, punti 2 e 3).

* proprieta': ogni soluzione OPTIMAL/FEASIBLE del modello settimanale passa
  il validatore, su istanze sintetiche con Matematica, Italiano e Scienze
  motorie (le regole che prima sfuggivano: doppia settimanale di Mat/Ita,
  motorie 0-o-2, tetti giornalieri per cattedra e per docente-classe);
* i casi che il validatore rifiuta sono ora INFEASIBLE anche nel modello;
* le regole SOFT del DSL entrano nell'obiettivo del percorso settimanale
  (``optimization._week_objective_terms``).
"""
from __future__ import annotations

import os
import random
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(HERE)
WEBUI_DIR = os.path.dirname(BACKEND_DIR)
REPO_ROOT = os.path.dirname(WEBUI_DIR)
ENGINE_DIR = os.path.join(REPO_ROOT, "engine")
for p in (WEBUI_DIR, ENGINE_DIR, REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from ortools.sat.python import cp_model  # noqa: E402

_OTHER = [("Inglese", 3), ("Storia", 2), ("Filosofia", 3), ("Fisica", 3),
          ("Scienze", 3), ("Latino", 3)]


def _profs(seed: int, n_classes: int = 2) -> dict:
    """Istanza sintetica: per classe Mat 4, Ita 4, Motorie 2 + 20 ore di
    altre materie (27 ore). Alcuni docenti insegnano piu' materie nella
    stessa classe (per far scattare il tetto docente-classe)."""
    rnd = random.Random(seed)
    profs: dict = {}
    for c in range(n_classes):
        cl = f"{c + 1}A"
        subjects = [("Matematica", 4), ("Italiano", 4),
                    ("Scienzemotorie", 2)] + _OTHER
        rnd.shuffle(subjects)
        # Coppie di materie sullo stesso docente (es. Mat+Fis, Ita+Lat).
        owners: dict = {}
        k = 0
        for subj, _ore in subjects:
            if subj in owners:
                continue
            owners[subj] = f"T{c}_{k}"
            k += 1
        if rnd.random() < 0.7:
            owners["Fisica"] = owners["Matematica"]
        if rnd.random() < 0.7:
            owners["Latino"] = owners["Italiano"]
        for subj, ore in subjects:
            t = owners[subj]
            profs.setdefault(t, {"classi": {}, "min_free_days": 1})
            profs[t]["classi"].setdefault(cl, {})[subj] = {"ore": ore}
    return profs


def _week_solver(profs):
    import cp_sat_constraint_model as csm
    cfg = csm.ConstraintConfig(enforce_no_holes=True,
                               enforce_h3_presence_at_11=True,
                               enforce_motorie_pair=True,
                               enforce_math_italian_pair=True, locks=[])
    s = csm.MonolithicSolver(profs, dc_value=None, config=cfg, scope=None)
    s.add_all_hard_constraints()
    s.add_class_no_overlap()
    for t in sorted(profs):
        s.add_dsl_constraint(f'teacher_max_per_day("{t}", 5)',
                             level="phase_b")
        s.add_dsl_constraint(f'teacher_at_least_n_free_days("{t}", 1)',
                             level="phase_b")
    return s


def _solve(model, seconds=20.0):
    cs = cp_model.CpSolver()
    cs.parameters.max_time_in_seconds = seconds
    cs.parameters.num_workers = 4
    cs.parameters.random_seed = 0
    return cs, cs.Solve(model)


@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_every_week_model_solution_passes_validator(seed):
    import metaheuristics as meta
    profs = _profs(seed)
    s = _week_solver(profs)
    # Obiettivo "cattivo": spinge verso ore isolate e giorni carichi, cioe'
    # proprio verso gli orari che il validatore rifiuta se il modello li
    # ammette.
    rnd = random.Random(1000 + seed)
    s.model.Minimize(sum(rnd.randint(-3, 3) * v for v in s.slot.values()))
    cs, st = _solve(s.model)
    assert st in (cp_model.OPTIMAL, cp_model.FEASIBLE), cs.StatusName(st)
    sol = {k: 1 for k, v in s.slot.items() if cs.Value(v)}
    assert meta.is_hard_feasible(sol, profs, verbose=True), (
        f"seed={seed}: soluzione del modello settimanale rifiutata "
        "dal validatore")
    # Tetti giornalieri uguali alla Fase A.
    per_triple: dict = {}
    per_prof_cl: dict = {}
    for (t, cl, subj, d, _h) in sol:
        per_triple[(t, cl, subj, d)] = per_triple.get((t, cl, subj, d), 0) + 1
        per_prof_cl[(t, cl, d)] = per_prof_cl.get((t, cl, d), 0) + 1
    assert max(per_triple.values()) <= 2
    assert max(per_prof_cl.values()) <= 3


def _pairs_profs():
    P = {"M": {"classi": {"1A": {"Matematica": {"ore": 4}}},
               "min_free_days": 1},
         "E": {"classi": {"1A": {"Scienzemotorie": {"ore": 2}}},
               "min_free_days": 1}}
    for i in range(4):
        P[f"T{i}"] = {"classi": {"1A": {f"S{i}": {"ore": 5}}},
                      "min_free_days": 1}
    return P


def test_math_without_weekly_double_is_infeasible():
    """4 ore di Matematica forzate a <= 1 al giorno: il validatore (H_A)
    le rifiuta, quindi il modello deve essere INFEASIBLE."""
    import metaheuristics as meta
    P = _pairs_profs()
    s = _week_solver(P)
    for d in meta.DAYS:
        s.model.Add(sum(v for k, v in s.slot.items()
                        if k[0] == "M" and k[3] == d) <= 1)
    cs, st = _solve(s.model)
    assert st == cp_model.INFEASIBLE, cs.StatusName(st)


def test_motorie_single_hour_is_infeasible():
    """Motorie 1 ora il lunedi': il validatore (H_B) vuole 0 o 2."""
    P = _pairs_profs()
    s = _week_solver(P)
    s.model.Add(sum(v for k, v in s.slot.items()
                    if k[0] == "E" and k[3] == 1) == 1)
    cs, st = _solve(s.model)
    assert st == cp_model.INFEASIBLE, cs.StatusName(st)


def test_week_objective_includes_soft_dsl_rules():
    """Regola SOFT con peso enorme («T0 libero il giorno 1») nel percorso
    settimanale: con i termini DSL nell'obiettivo T0 non lavora il giorno 1
    (prima ne aveva 2 ore)."""
    from backend.optimization import _week_objective_terms
    P = {f"T{i}": {"classi": {"1A": {f"S{i}": {"ore": 5}}},
                   "min_free_days": 1} for i in range(6)}
    s = _week_solver(P)
    s.add_dsl_constraint(
        'teacher_preferred_free_day_penalty("T0", 1, 1000000)',
        is_hard=False, soft_weight=1000000, level="phase_b")
    assert s.dsl_soft_cost_terms, "la regola SOFT deve essere compilata"
    terms = _week_objective_terms(s)
    s.model.Minimize(sum(terms))
    cs, st = _solve(s.model)
    assert st in (cp_model.OPTIMAL, cp_model.FEASIBLE), cs.StatusName(st)
    d1 = sum(cs.Value(v) for k, v in s.slot.items()
             if k[0] == "T0" and k[3] == 1)
    assert d1 == 0, f"T0 ha {d1} ore il giorno 1 nonostante la regola SOFT"


def test_phase_a_free_day_preferences_do_not_make_it_infeasible():
    """Revisione Kepler #1: con i pesi reali delle preferenze (150/45/15) il
    vecchio tetto di ``fdpref_pen`` (9 * n_docenti) diventava un vincolo
    HARD e la Fase A risultava PhaseAInfeasible. Le preferenze sono SOFT:
    la Fase A deve restare risolvibile."""
    import cpsat_v2_timetable as cv2
    P = {f"T{i}": {"classi": {"1A": {f"S{i}": {"ore": 5}}},
                   "min_free_days": 1,
                   "free_day_prefs": [(1, 150), (2, 45), (3, 15)]}
         for i in range(6)}
    cl, tr, cp = cv2.build_indices(P)
    dc = cv2.solve_phase_a(P, cl, tr, cp, time_limit=10, workers=4,
                           log=False)
    assert dc, "la Fase A deve trovare una distribuzione"
