"""Preset «al massimo N giorni liberi sopra S ore» (Kepler, dopo R1+R3).

N e S non sono cablati: il preset di partenza è N=1, S=18, spento
finché il payload non lo accende.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(HERE)
WEBUI_DIR = os.path.dirname(BACKEND_DIR)
REPO_ROOT = os.path.dirname(WEBUI_DIR)
ENGINE_DIR = os.path.join(REPO_ROOT, "engine")
for p in (WEBUI_DIR, ENGINE_DIR, REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from ortools.sat.python import cp_model  # noqa: E402

import max_free_days as mfd  # noqa: E402
import dsl_to_cpsat as d2c  # noqa: E402


DAYS = [1, 2, 3, 4, 5, 6]


def _info(hours, *, min_free=1, pot=0, caps=None, rule=True, threshold=18,
          max_free=1):
    info = {
        "classi": {"1A": {"S": {"ore": hours - pot}}},
        "min_free_days": min_free,
        "potenziamento_hours": pot,
    }
    if caps is not None:
        info["day_capacity"] = caps
    if rule:
        info["max_free_if_hours"] = {
            "max_free": max_free, "threshold": threshold}
    return info


def _phase_a_model(hours, *, with_rule, force_free_at_least=None,
                   pot=0, threshold=18, max_free=1, min_free=0):
    """Modello di Fase A: ore di cattedra sui 6 giorni, tetto 5,
    più eventuale potenziamento. La regola, se accesa, è compilata
    dal pragma, non da un vincolo scritto nel test."""
    model = cp_model.CpModel()
    day_count = {}
    for d in DAYS:
        day_count[("T", "1A", "S", d)] = model.NewIntVar(0, 5, f"dc_{d}")
    lesson_hours = hours - pot
    model.Add(sum(day_count.values()) == lesson_hours)
    pot_vars = {}
    if pot:
        for d in DAYS:
            pot_vars[("T", d)] = model.NewIntVar(0, 5, f"pot_{d}")
        model.Add(sum(pot_vars.values()) == pot)
        for d in DAYS:
            model.Add(day_count[("T", "1A", "S", d)] + pot_vars[("T", d)] <= 5)
    if force_free_at_least:
        zeros = []
        for d in DAYS:
            z = model.NewBoolVar(f"z_{d}")
            lesson = day_count[("T", "1A", "S", d)]
            pot_v = pot_vars.get(("T", d))
            if pot_v is None:
                model.Add(lesson == 0).OnlyEnforceIf(z)
                model.Add(lesson >= 1).OnlyEnforceIf(z.Not())
            else:
                model.Add(lesson + pot_v == 0).OnlyEnforceIf(z)
                model.Add(lesson + pot_v >= 1).OnlyEnforceIf(z.Not())
            zeros.append(z)
        model.Add(sum(zeros) >= int(force_free_at_least))
    compiler = d2c.DSLConstraintCompiler(
        model, {}, day_count=day_count, level="phase_a")
    compiler.teacher_meta = {
        "T": _info(hours, min_free=min_free, pot=pot, rule=with_rule,
                   threshold=threshold, max_free=max_free),
    }
    compiler.pot_day_count = pot_vars
    if with_rule:
        compiler.compile(
            mfd.pragma("T", max_free, threshold))
    return model, compiler


def _solve(model):
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = 1
    status = solver.Solve(model)
    return status, solver


def test_preset_is_data_not_engine_constant():
    assert mfd.PRESET["enabled_by_default"] is False
    assert mfd.PRESET["max_free"] == 1
    assert mfd.PRESET["threshold"] == 18
    assert "18" not in mfd.pragma("T", 2, 12)


def test_precheck_min_free_two_is_impossible():
    profs = {"T": _info(18, min_free=2, max_free=1)}
    errors = mfd.precheck(profs)
    assert errors
    assert errors[0]["code"] == "min_free_exceeds_max"


def test_precheck_below_threshold_not_applied():
    profs = {"T": _info(12, min_free=2, max_free=1, threshold=18)}
    assert mfd.precheck(profs) == []


def test_precheck_hard_unavailability():
    profs = {"T": _info(18, caps={1: 0, 2: 0, 3: 5})}
    errors = mfd.precheck(profs)
    assert errors and errors[0]["code"] == "hard_unavailability"


def test_18h_with_rule_rejects_two_free_days():
    model, compiler = _phase_a_model(
        18, with_rule=True, force_free_at_least=2)
    status, _ = _solve(model)
    assert status == cp_model.INFEASIBLE, compiler.diagnostics


def test_mutant_without_constraint_would_accept_two_free_days():
    """Senza il vincolo 18 ore su 6 giorni ammettono 2 giorni liberi
    (5+5+4+4). Se il pragma non aggiunge il tetto, questo test diventa
    rosso perché lo status non è più INFEASIBLE."""
    bare, _ = _phase_a_model(18, with_rule=False, force_free_at_least=2)
    status, _ = _solve(bare)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    ruled, _ = _phase_a_model(18, with_rule=True, force_free_at_least=2)
    assert _solve(ruled)[0] == cp_model.INFEASIBLE


def test_18h_with_rule_finds_at_most_one_free_day():
    model, compiler = _phase_a_model(18, with_rule=True)
    status, solver = _solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE), compiler.diagnostics
    dc = compiler.day_count
    free = sum(
        1 for d in DAYS if solver.Value(dc[("T", "1A", "S", d)]) == 0)
    assert free <= 1


def test_12h_rule_not_applied():
    model, compiler = _phase_a_model(
        12, with_rule=True, force_free_at_least=2, threshold=18)
    status, _ = _solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert any("non applicata" in d for d in compiler.diagnostics)


def test_potenziamento_counts_as_busy():
    """16 ore di lezione + 2 di potenziamento: due giorni senza lezione
    restano ammessi se il potenziamento ne occupa uno."""
    model, compiler = _phase_a_model(
        18, with_rule=True, force_free_at_least=None, pot=2)
    # Force exactly two days with zero LESSONS; pot may fill one.
    zeros = []
    dc = compiler.day_count
    pot = compiler.pot_day_count
    for d in DAYS:
        z = model.NewBoolVar(f"lessonfree_{d}")
        model.Add(dc[("T", "1A", "S", d)] == 0).OnlyEnforceIf(z)
        model.Add(dc[("T", "1A", "S", d)] >= 1).OnlyEnforceIf(z.Not())
        zeros.append(z)
    model.Add(sum(zeros) == 2)
    status, solver = _solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE), compiler.diagnostics
    truly_free = 0
    for d in DAYS:
        busy = solver.Value(dc[("T", "1A", "S", d)]) + solver.Value(pot[("T", d)])
        if busy == 0:
            truly_free += 1
    assert truly_free <= 1


def test_validator_rejects_two_free_days():
    import metaheuristics as meta
    profs = {"T": _info(18)}
    sol = {}
    # 18 hours on 4 days (two free).
    hours_left = 18
    for d, n in ((1, 5), (2, 5), (3, 4), (4, 4)):
        for h in range(8, 8 + n):
            sol[("T", "1A", "S", d, h)] = 1
        hours_left -= n
    assert hours_left == 0
    assert meta.is_hard_feasible(sol, profs) is False


def test_validator_ignores_teacher_below_threshold():
    profs = {"T": _info(12, threshold=18)}
    sol = {("T", "1A", "S", d, 8): 1 for d in (1, 2, 3, 4)}
    # 4 hours placed, two free days, below threshold: the cap does not apply.
    # Other HARD checks may still fail (coverage). The max-free helper
    # itself must not be the reason.
    assert mfd.solution_respects(sol, profs) is True


def test_per_day_slice_does_not_false_unsat():
    model = cp_model.CpModel()
    slot = {("T", "1A", "S", 1, h): model.NewBoolVar(f"s{h}")
            for h in range(8, 14)}
    compiler = d2c.DSLConstraintCompiler(model, slot, level="phase_b")
    compiler.teacher_meta = {"T": _info(18)}
    compiler.compile(mfd.pragma("T", 1, 18))
    assert any("slice" in d for d in compiler.diagnostics)
    status, _ = _solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_infeasible_core_names_the_teacher():
    """Il letterale maxfree_ è un'assumption: il nucleo minimo lo nomina.
    L'insieme ammissibile non cambia: senza la regola i due giorni
    liberi restano ammessi (test sopra)."""
    model, compiler = _phase_a_model(
        18, with_rule=True, force_free_at_least=2)
    status, solver = _solve(model)
    assert status == cp_model.INFEASIBLE
    names = mfd.assumption_core_teachers(
        solver, compiler.maxfree_lits, model=model)
    assert names == ["T"]


def test_phase_a_infeasible_message_names_the_teacher():
    """Il percorso di produzione (solve_phase_a) interroga il modello
    vero e mette il nucleo nel messaggio già esistente."""
    import cpsat_v2_timetable as cv2
    profs = {
        "T": {
            "classi": {"1A": {
                "S1": {"ore": 6},
                "S2": {"ore": 6},
                "S3": {"ore": 6},
            }},
            "min_free_days": 0,
            "max_free_if_hours": {"max_free": 1, "threshold": 18},
        }
    }
    classes, triples, class_profs = cv2.build_indices(profs)
    try:
        cv2.solve_phase_a(
            profs, classes, triples, class_profs,
            time_limit=15, workers=1, log=False,
            class_flags={"1A": {
                "entry_at_8": False,
                "no_holes": False,
                "exit_after_12": False,
                "max_6_per_day": True,
            }},
        )
    except cv2.PhaseAInfeasible as exc:
        msg = str(exc)
    else:
        raise AssertionError("atteso PhaseAInfeasible")
    assert "Nucleo minimo" in msg
    assert "T" in msg



def test_weekly_hours_skips_pseudo_class_potenziamento():
    """Kepler G1: il potenziamento in ``classi`` non si conta due volte."""
    info = {"classi": {"1A": {"Matematica": {"ore": 16}},
                       "__potenziamento__": {"Pot": {"ore": 2}}},
            "potenziamento_hours": 2}
    assert mfd.weekly_hours(info) == 18


def test_precheck_hours_exceed_capacity_of_remaining_days():
    """Kepler G2: 20 ore, 6 giorni da 4 ore, max 2 liberi -> 16 < 20."""
    profs = {"T": {"classi": {"1A": {"X": {"ore": 20}}},
                   "potenziamento_hours": 0,
                   "max_free_if_hours": {"max_free": 2, "threshold": 18}}}
    errs = mfd.precheck(profs, days=[1, 2, 3, 4, 5, 6], hours_per_day=4)
    assert [e["code"] for e in errs] == ["hours_exceed_capacity"]
    assert mfd.precheck(profs, days=[1, 2, 3, 4, 5, 6], hours_per_day=5) == []
