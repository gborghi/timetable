"""Engine diagnostics smoke tests via pytest.

Carica la soluzione optimised del profilo small e verifica che le tre
funzioni diagnostic ritornino strutture sensate.
"""
from __future__ import annotations

import os
import sys

import pytest

# Add parent for engine imports
# Radice del repo: webui/backend/tests -> tre livelli sopra. Prima
# PARENT puntava a webui/backend e il modulo non si importava mai.
REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
PARENT = os.path.join(REPO, "engine")
ENGINE = PARENT
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

# Add engine/scripts for engine_diagnostics
SCRIPTS = os.path.join(PARENT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

# Skip if dependencies missing
cv2 = pytest.importorskip("cpsat_v2_timetable")
meta = pytest.importorskip("metaheuristics")
diag = pytest.importorskip("engine_diagnostics")


def _small_school():
    """Scuola sintetica minima: i pickle storici di `small` non ci sono
    piu' (vedi PICKLE_DEPRECATED.md), la soluzione si calcola qui."""
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


def test_engine_diagnostics():
    """Smoke test for engine diagnostics via pytest."""
    profs = _small_school()
    classes, triples, class_profs = cv2.build_indices(profs)
    dc_value = cv2.solve_phase_a(profs, classes, triples, class_profs,
                                 time_limit=10, workers=2, log=False)
    assert dc_value
    sol = {}
    for d in cv2.DAYS:
        out, _ = cv2.solve_phase_b_for_day(d, profs, classes, triples,
                                           class_profs, dc_value,
                                           time_limit=10, workers=2)
        assert out is not None
        sol.update(out)

    print("[test] HARD check sulla soluzione attuale: ", end="")
    print("OK" if meta.is_hard_feasible(sol, profs) else "FAIL")

    obj0, m0 = meta.compute_soft(sol, profs)
    print(f"[test] obj iniziale: {obj0} {m0}")

    # Pick a class + day with at least one lesson
    sample_class, sample_day = None, None
    for (p, cl, subj, d, h), v in sol.items():
        if v == 1:
            sample_class, sample_day = cl, d
            break

    print(f"[test] repair_slot_neighborhood class_day "
          f"({sample_class}, d{sample_day})")
    res = diag.repair_slot_neighborhood(
        sol, profs, dc_value,
        scope=dict(kind="class_day", **{"class": sample_class}, day=sample_day),
        time_budget_s=5,
    )
    print(f"       ok={res['ok']} delta_soft={res['delta_soft']} "
          f"time={res['time_used']:.1f}s")
    assert res["ok"], "repair_slot_neighborhood deve avere successo "
    assert res["delta_soft"] >= 0, "repair_slot non deve peggiorare"

    print(f"[test] explain_infeasibility(d{sample_day})")
    expl = diag.explain_infeasibility(profs, dc_value, sample_day)
    print(f"       summary: {expl['summary']}")
    print(f"       hall_violations={len(expl['hall_violations'])} "
          f"class_outliers={len(expl['class_load_outliers'])} "
          f"prof_overload={len(expl['prof_overload'])}")

    # why_not su una lezione: prendi una lezione esistente e prova a
    # "spostarla" al suo stesso slot (deve essere ok perche' la cella
    # e' la stessa).
    sample_lesson = None
    for (p, cl, subj, d, h), v in sol.items():
        if v == 1:
            sample_lesson = (p, cl, subj)
            target_day, target_hour = d, h
            break
    print(f"[test] why_not_lesson({sample_lesson}, "
          f"d{target_day}, h{target_hour})")
    wn = diag.why_not_lesson(
        sol, profs, sample_lesson, target_day, target_hour
    )
    print(f"       ok={wn['ok']} violations={len(wn['violations'])}")

    # Anti-test: prova a mettere una lezione di un docente in uno slot
    # dove un'altra delle sue classi e' gia' presente -> deve essere
    # not ok con violazione PROF_OVERLAP.
    p_ref = sample_lesson[0]
    p_busy_slot = None
    for (p, cl, subj, d, h), v in sol.items():
        if v == 1 and p == p_ref and (cl, subj) != (sample_lesson[1], sample_lesson[2]):
            p_busy_slot = (d, h, cl, subj)
            break
    if p_busy_slot:
        d_b, h_b, cl_b, subj_b = p_busy_slot
        wn2 = diag.why_not_lesson(
            sol, profs, sample_lesson, d_b, h_b,
        )
        print(f"[test] why_not su slot occupato dal prof: "
              f"ok={wn2['ok']} violations={len(wn2['violations'])}")
        assert not wn2["ok"], "doveva trovare un PROF_OVERLAP"

    print("[test] all green")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
# Moved from engine/scripts/ (audit T3)
