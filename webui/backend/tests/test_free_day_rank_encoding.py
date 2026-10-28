"""Preferenze sul giorno libero con codifica a rango + DSL_SCALE
(verifica di Kepler, punto (b)).

* La regola ``teacher_free_day_preferences`` paga ``w_1 - w_migliore``:
  liberare anche la 2a o la 3a scelta non fa risparmiare nulla.
* Nel percorso settimanale i termini SOFT DSL sono scalati di
  ``DSL_SCALE = SCALE = 100``, quindi la 1a scelta (30) vale 3 buchi.
* Sull'istanza di ``exp_b4.py`` (4 classi, 8 docenti) il costo interno
  resta 0 e tutte le prime scelte sono rispettate.
"""
from __future__ import annotations

import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
for p in (os.path.join(REPO_ROOT, "webui"), os.path.join(REPO_ROOT, "engine")):
    if p not in sys.path:
        sys.path.insert(0, p)

from ortools.sat.python import cp_model  # noqa: E402

PW = {1: 30, 2: 20, 3: 10}


def _profs(nc=4):
    P: dict = {}
    subj = [("Matematica", 4, "MF"), ("Fisica", 3, "MF"),
            ("Italiano", 4, "IL"), ("Latino", 3, "IL"),
            ("Inglese", 3, "EN"), ("Storia", 2, "SF"),
            ("Filosofia", 3, "SF"), ("Scienze", 3, "SC"),
            ("Scienzemotorie", 2, "SM")]
    for c in range(nc):
        cl = f"{c + 1}A"
        for s, o, g in subj:
            t = f"{g}{c // 2}" if g in ("MF", "IL") else f"{g}{c // 4}"
            P.setdefault(t, {"classi": {}, "min_free_days": 1})[
                "classi"].setdefault(cl, {})[s] = {"ore": o}
    return P


def _week_solver(P):
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
    return s


def test_rank_pragma_increments():
    """30/20/10 -> incrementi [10, 10, 10]; 150/45/15 -> [105, 30, 15]."""
    P = {"T": {"classi": {"1A": {"S": {"ore": 5}}}, "min_free_days": 1}}
    for prefs, incs in (([30, 20, 10], [10, 10, 10]),
                        ([150, 45, 15], [105, 30, 15])):
        s = _week_solver(P)
        n0 = len(s.dsl_soft_cost_terms)
        args = ", ".join(f"{d}, {w}" for d, w in zip((1, 2, 3), prefs))
        s.add_dsl_constraint(f'teacher_free_day_preferences("T", {args})',
                             is_hard=False, soft_weight=prefs[0],
                             level="phase_b")
        assert [w for w, _ in s.dsl_soft_cost_terms[n0:]] == incs


def test_rank_pref_no_extra_free_days():
    """Istanza di exp_b4 (Kepler): con DSL_SCALE = 100 e la codifica a
    rango il costo interno resta 0 e le prime scelte sono 8/8."""
    import metaheuristics as meta
    from backend.optimization import _week_objective_terms
    P = _profs(4)
    rnd = random.Random(0)
    s = _week_solver(P)
    prefs = {}
    for t in sorted(P):
        ds = rnd.sample(list(meta.DAYS), 3)
        prefs[t] = ds
        args = ", ".join(f"{d}, {PW[i + 1]}" for i, d in enumerate(ds))
        s.add_dsl_constraint(f'teacher_free_day_preferences("{t}", {args})',
                             is_hard=False, soft_weight=30, level="phase_b")
    internal, _ = s.compute_soft_cost_expr(mode="default")
    s.model.Minimize(sum(_week_objective_terms(s)))
    cs = cp_model.CpSolver()
    cs.parameters.max_time_in_seconds = 60
    cs.parameters.num_workers = 8
    cs.parameters.random_seed = 0
    st = cs.Solve(s.model)
    assert st in (cp_model.OPTIMAL, cp_model.FEASIBLE), cs.StatusName(st)

    def busy(t, d):
        return any(cs.Value(v) for k, v in s.slot.items()
                   if k[0] == t and k[3] == d)
    first = sum(1 for t in P if not busy(t, prefs[t][0]))
    assert first == len(P)
    assert sum(cs.Value(e) for e in internal) == 0


def test_dsl_soft_terms_scaled_and_clamped():
    import cp_sat_constraint_model as csm
    P = {"T": {"classi": {"1A": {"S": {"ore": 5}}}, "min_free_days": 1}}
    s = _week_solver(P)
    s.add_dsl_constraint('teacher_preferred_free_day_penalty("T", 1, 30)',
                         is_hard=False, soft_weight=30, level="phase_b")
    s.add_dsl_constraint(
        'teacher_preferred_free_day_penalty("T", 2, 1000000000000)',
        is_hard=False, soft_weight=1, level="phase_b")
    terms = s.dsl_soft_objective_terms()
    assert len(terms) == 2
    s.model.Minimize(sum(terms))
    coefs = sorted(s.model.Proto().objective.coeffs)
    assert coefs == [30 * csm.DSL_SCALE, 10_000 * csm.DSL_SCALE]


def test_phase_a_rank_first_choice_honoured():
    """Fase A con la codifica a rango: la 1a scelta di T0 viene
    rispettata e la Fase A resta risolvibile."""
    import cpsat_v2_timetable as cv2
    P = {f"T{i}": {"classi": {"1A": {f"S{i}": {"ore": 5}}},
                   "min_free_days": 1} for i in range(6)}
    P["T0"]["free_day_prefs"] = [(1, 150), (2, 45), (3, 15)]
    cl, tr, cp = cv2.build_indices(P)
    dc = cv2.solve_phase_a(P, cl, tr, cp, time_limit=10, workers=4,
                           log=False)
    assert dc
    assert sum(v for (tt, _c, _s, d), v in dc.items()
               if tt == "T0" and d == 1) == 0


def test_translator_groups_preferences_per_teacher():
    import dsl_translator as dt
    expr = dt.teacher_free_day_preferences_to_dsl("Rossi", [(3, 30), (1, 20)])
    assert expr == 'teacher_free_day_preferences("Rossi", 3, 30, 1, 20)'
