"""Punto 4 di Kepler: «niente buchi» = un solo blocco di ore, che puo'
cominciare a qualsiasi ora; l'entrata alla prima ora e' un vincolo a parte
(flag di classe ``entry_at_8``). Verificato nei tre percorsi: modello
settimanale, per giorno (cpsat_v2) e compilatore DSL."""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
for p in (os.path.join(REPO_ROOT, "webui"), os.path.join(REPO_ROOT, "engine")):
    if p not in sys.path:
        sys.path.insert(0, p)

from ortools.sat.python import cp_model  # noqa: E402

OK = (cp_model.OPTIMAL, cp_model.FEASIBLE)


def _flags(e8, nh=True):
    return {"1A": {"no_holes": nh, "entry_at_8": e8}}


def _weekly(e8):
    import cp_sat_constraint_model as csm
    P = {f"T{i}": {"classi": {"1A": {f"S{i}": {"ore": 4}}},
                   "min_free_days": 0} for i in range(6)}
    s = csm.MonolithicSolver(
        P, dc_value=None,
        config=csm.ConstraintConfig(locks=[], class_flags=_flags(e8)),
        scope=None)
    s.add_all_hard_constraints()
    s.add_class_no_overlap()
    return P, s


def _solve(m):
    cs = cp_model.CpSolver()
    cs.parameters.num_workers = 4
    cs.parameters.max_time_in_seconds = 20
    return cs, cs.Solve(m)


@pytest.mark.parametrize("e8,expected_ok", [(False, True), (True, False)])
def test_weekly_entry_at_9(e8, expected_ok):
    import metaheuristics as meta
    P, s = _weekly(e8)
    m = s.model
    m.Add(sum(v for k, v in s.slot.items() if k[3] == 1 and k[4] == 8) == 0)
    m.Add(sum(v for k, v in s.slot.items() if k[3] == 1) >= 4)
    cs, st = _solve(m)
    assert (st in OK) == expected_ok, cs.StatusName(st)
    if expected_ok:
        sol = {k: 1 for k, v in s.slot.items() if cs.Value(v)}
        hrs = sorted(k[4] for k in sol if k[3] == 1)
        assert hrs[0] > 8 and hrs == list(range(hrs[0], hrs[0] + len(hrs)))
        assert meta.is_hard_feasible(sol, P, class_flags=_flags(e8),
                                     verbose=True)


def test_weekly_hole_still_forbidden_without_entry():
    _P, s = _weekly(False)
    m = s.model
    m.Add(sum(v for k, v in s.slot.items() if k[3] == 1 and k[4] == 10) == 0)
    m.Add(sum(v for k, v in s.slot.items()
              if k[3] == 1 and k[4] in (9, 11)) == 2)
    cs, st = _solve(m)
    assert st == cp_model.INFEASIBLE, cs.StatusName(st)


def _per_day_dc():
    P = {f"T{i}": {"classi": {"1A": {f"S{i}": {"ore": 1}}}}
         for i in range(4)}
    dc = {(f"T{i}", "1A", f"S{i}", 1): 1 for i in range(4)}
    return P, dc


@pytest.mark.parametrize("e8,expected_ok", [(False, True), (True, False)])
def test_per_day_entry_flag(e8, expected_ok):
    """Classe con 4 ore il giorno 1 e una lezione bloccata alle 12: con
    l'entrata alle 8 servirebbero 5 ore (8..12) -> impossibile; senza,
    il blocco 9..12 va bene."""
    import cpsat_v2_timetable as cv2
    P, dc = _per_day_dc()
    classes, triples, class_profs = cv2.build_indices(P)
    out = cv2.solve_phase_b_for_day(
        1, P, classes, triples, class_profs, dc, time_limit=10,
        workers=2, enforce_no_holes=True,
        locked_slots_for_day=[("T0", "1A", "S0", 12)],
        class_flags={"1A": {"no_holes": True, "entry_at_8": e8,
                            "exit_after_12": True}})
    sol = out[0] if isinstance(out, tuple) else out
    assert bool(sol) == expected_ok, out
    if expected_ok:
        hrs = sorted(k[-1] for k, v in sol.items() if v)
        assert hrs == [9, 10, 11, 12], hrs


@pytest.mark.parametrize("via_dsl", [False, True])
@pytest.mark.parametrize("e8,expected_ok", [(False, True), (True, False)])
def test_dsl_and_legacy_same_entry_semantics(via_dsl, e8, expected_ok):
    """Percorso per giorno di MonolithicSolver, diretto e via DSL (seed
    ``no_holes_class`` + ``class_entry_first_hour``)."""
    import cp_sat_constraint_model as csm
    P, dc = _per_day_dc()
    cfg = csm.ConstraintConfig(enforce_no_holes=True,
                               enforce_h3_presence_at_11=False,
                               enforce_motorie_pair=False,
                               enforce_math_italian_pair=False,
                               locks=[], class_flags=_flags(e8))
    s = csm.MonolithicSolver(P, dc, cfg)
    s.build(via_dsl=via_dsl)
    s.model.Add(s.slot[("T0", "1A", "S0", 1, 12)] == 1)
    cs, st = _solve(s.model)
    assert (st in OK) == expected_ok, cs.StatusName(st)


def test_seed_emits_entry_pragma_only_with_flag():
    import dsl_translator as dt
    P, _dc = _per_day_dc()
    on = dt.seed_implicit_hardcoded(P, classes=["1A"], enforce_no_holes=True,
                                    class_flags=_flags(True))
    off = dt.seed_implicit_hardcoded(P, classes=["1A"],
                                     enforce_no_holes=True,
                                     class_flags=_flags(False))
    assert 'class_entry_first_hour("1A")' in on
    assert 'class_entry_first_hour("1A")' not in off
    assert 'no_holes_class("1A")' in off


def test_general_dsl_evaluator_matches():
    import general_dsl as g
    hours = [{"index": h} for h in range(8, 14)]

    def world(hs):
        return {"hours": hours, "days": [{"index": 1}],
                "lessons": [{"teacher": "T", "class": "1A", "subject": "S",
                             "day": 1, "hour": h} for h in hs]}
    assert g._eval_no_holes_class(world([9, 10, 11]), "1A")
    assert not g._eval_no_holes_class(world([9, 11]), "1A")
    assert not g._eval_class_entry_first_hour(world([9, 10]), "1A")
    assert g._eval_class_entry_first_hour(world([8, 9]), "1A")
