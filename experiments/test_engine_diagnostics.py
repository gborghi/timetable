r"""Smoke tests per engine_diagnostics.

Carica la soluzione optimised del profilo small e verifica che le tre
funzioni diagnostic ritornino strutture sensate. Usa:

    python experiments/test_engine_diagnostics.py
"""
from __future__ import annotations

import os
import pickle
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import engine_diagnostics as diag  # noqa: E402
import metaheuristics as meta  # noqa: E402


def main():
    profs_path = os.path.join(HERE, "profs_small.pkl")
    sol_path = os.path.join(HERE, "solution_timetable_small_optimized.pkl")
    dc_path = os.path.join(HERE, "phase_a_dc_small.pkl")
    if not os.path.exists(sol_path):
        print(f"SKIP: {sol_path} non esiste; runna prima "
              f"run_full_pipeline.py --profile small.")
        return 0
    with open(profs_path, "rb") as f:
        profs = pickle.load(f)
    with open(sol_path, "rb") as f:
        sol = pickle.load(f)
    with open(dc_path, "rb") as f:
        dc_value = pickle.load(f)

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
    return 0


if __name__ == "__main__":
    sys.exit(main())
