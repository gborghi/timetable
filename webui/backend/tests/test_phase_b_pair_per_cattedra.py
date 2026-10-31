"""Fase B: la doppia (pair_exists) si conta per cattedra (docente, materia).

Regressione Kepler B1 (31/10/2026): un docente di lettere con Italiano e
Storia nella stessa classe. La Fase B contava insieme le ore delle due
materie, quindi accettava Italiano-Storia come "doppia di Italiano"; il
validatore ``is_hard_feasible`` (H_A) invece vuole due ore consecutive di
Italiano. Fase A + Fase B devono dare un orario che il validatore accetta.
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
WEBUI_DIR = os.path.dirname(os.path.dirname(HERE))
REPO_ROOT = os.path.dirname(WEBUI_DIR)
ENGINE_DIR = os.path.join(REPO_ROOT, "engine")
for p in (WEBUI_DIR, ENGINE_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from ortools.sat.python import cp_model  # noqa: E402


def _profs():
    g = [6, 5, 4]
    return {
        "Lettere": {"classi": {"3A": {"Italiano": {"ore": 4},
                                      "Storia": {"ore": 3}}}, "glibero": g},
        "Mate": {"classi": {"3A": {"Matematica": {"ore": 4}}}, "glibero": g},
        "Ing": {"classi": {"3A": {"Inglese": {"ore": 3}}}, "glibero": g},
        "Sci": {"classi": {"3A": {"Scienze": {"ore": 3}}}, "glibero": g},
        "Fil": {"classi": {"3A": {"Filosofia": {"ore": 3}}}, "glibero": g},
        "Fis": {"classi": {"3A": {"Fisica": {"ore": 3}}}, "glibero": g},
        "Art": {"classi": {"3A": {"Disegno": {"ore": 2}}}, "glibero": g},
        "Mot": {"classi": {"3A": {"Scienzemotorie": {"ore": 2}}},
                "glibero": g},
    }


def test_phase_b_ita_sto_same_teacher_is_hard_feasible():
    import cpsat_v2_timetable as cv2
    import metaheuristics as meta
    profs = _profs()
    classes, triples, class_profs = cv2.build_indices(profs)
    dc = cv2.solve_phase_a(profs, classes, triples, class_profs,
                           time_limit=10, workers=2, log=False)
    assert dc, "Fase A senza soluzione"
    full = {}
    for d in cv2.DAYS:
        out, _ = cv2.solve_phase_b_for_day(d, profs, classes, triples,
                                           class_profs, dc, time_limit=10,
                                           workers=2, log=False)
        assert out is not None, f"Fase B infeasible il giorno {d}"
        full.update(out)
    assert meta.is_hard_feasible(full, profs, verbose=True)


def test_pair_exists_ignores_other_subject_of_same_teacher():
    """Italiano alle ore 1 e 3, Storia alla 2: non e' una doppia di
    Italiano, quindi il vincolo deve rendere il giorno INFEASIBLE."""
    import cpsat_v2_timetable as cv2
    profs = {"L": {"classi": {"3A": {"Italiano": {"ore": 2},
                                     "Storia": {"ore": 1}}}}}
    H = cv2.HOURS
    m = cp_model.CpModel()
    slot = {("L", "3A", s, h): m.NewBoolVar(f"{s}{h}")
            for s in ("Italiano", "Storia") for h in H}
    fixed = {H[0]: "Italiano", H[1]: "Storia", H[2]: "Italiano"}
    for (p, cl, s, h), v in slot.items():
        m.Add(v == (1 if fixed.get(h) == s else 0))
    dc = {("L", "3A", "Italiano", 1): 2, ("L", "3A", "Storia", 1): 1}
    cv2.add_consecutive_constraints_phase_b(
        m, slot, 1, profs, dc,
        pairing={("3A", "Italiano"): "pair_exists"})
    st = cp_model.CpSolver().Solve(m)
    assert st == cp_model.INFEASIBLE
