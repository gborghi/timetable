"""Subproject D core — ``compute_soft`` scores DSL SOFT rules.

Verifies that ``metaheuristics.compute_soft`` optionally accepts a
pre-parsed ``soft_rules`` list of ``(tree, weight)`` pairs and adds
``weight`` to the objective for every VIOLATED rule, while leaving the
structural objective (sixth/buchi/five/one) byte-identical and the
default 2-arg call form unchanged (zero-drift).
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(HERE)
WEBUI_DIR = os.path.dirname(BACKEND_DIR)
REPO_ROOT = os.path.dirname(WEBUI_DIR)
ENGINE_DIR = os.path.join(REPO_ROOT, "engine")
for p in (WEBUI_DIR, ENGINE_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import metaheuristics as meta  # noqa: E402


def _profs():
    return {"T1": {"classi": {"1A": {"Mat": {"ore": 2}}}, "max_hours": 18}}


def test_compute_soft_scores_dsl_soft_rules():
    profs = _profs()

    # SOFT-unavailability: T1 must NOT teach on (day1, hour8).
    expr = (
        'forall l in lessons where l.teacher == "T1" '
        'and l.day == 1 and l.hour == 8: false'
    )
    # Pre-parse via the project helper so the tree is produced by the
    # SAME general_dsl module object that compute_soft evaluates with.
    # (Parsing with a *different* import alias of general_dsl would give
    # node classes that fail compute_soft's evaluator isinstance checks.)
    parsed = meta.parse_soft_rules(
        [{"expression": expr, "is_hard": False, "weight": 100,
          "label": "no-T1-mon-8"}])
    assert len(parsed) == 1
    tree, weight = parsed[0]
    assert weight == 100
    # Sanity: the helper skips HARD / non-positive-weight rules.
    assert meta.parse_soft_rules(
        [{"expression": expr, "is_hard": True, "weight": 100}]) == []
    assert meta.parse_soft_rules(
        [{"expression": expr, "is_hard": False, "weight": 0}]) == []

    # Both solutions place exactly 2 contiguous hours for T1/1A/Mat on
    # day 1. Structurally identical (same per-(prof,day) and per-(class,
    # day) hour counts, both 2 contiguous hours -> buchi 0, no five, no
    # one, neither touches h13 -> sixth 0). Only difference: violating
    # uses hours {8,9} (hits h8), ok uses {9,10} (misses h8).
    sol_violating = {
        ("T1", "1A", "Mat", 1, 8): 1,
        ("T1", "1A", "Mat", 1, 9): 1,
    }
    sol_ok = {
        ("T1", "1A", "Mat", 1, 9): 1,
        ("T1", "1A", "Mat", 1, 10): 1,
    }

    # Structural parity: with NO soft_rules the two solutions score equal.
    struct_viol, _ = meta.compute_soft(sol_violating, profs)
    struct_ok, _ = meta.compute_soft(sol_ok, profs)
    assert struct_viol == struct_ok

    # Default 2-arg call form still works and returns (val, metrics).
    assert isinstance(struct_ok, (int, float))

    # With the soft rule, the violating solution costs exactly +100.
    soft_rules = [(tree, 100)]
    v_viol, m_viol = meta.compute_soft(
        sol_violating, profs, soft_rules=soft_rules)
    v_ok, m_ok = meta.compute_soft(
        sol_ok, profs, soft_rules=soft_rules)

    assert v_viol - v_ok == 100
    # The full delta equals the soft penalty since structural parts match.
    assert v_viol - v_ok == 100 - (struct_ok - struct_viol)
    assert m_viol.get("dsl_soft") == 100
    assert m_ok.get("dsl_soft") == 0


# --------------------------------------------------------------------------
# Task 2 — meta runners honour the pre-parsed soft_rules in their inner loop.
# --------------------------------------------------------------------------

def _feasible_world_with_soft():
    """Small HARD-feasible (sol, profs, dc_value) plus a SOFT rule that
    penalises ProfA teaching at (day1, hour8).

    1A has 8 weekly hours over days 1 and 2, each day the contiguous
    block {8,9,10,11} (H1/H2/H3 satisfied: starts at 8, contiguous,
    includes 11). Initially ProfA-Mat sits on {8,9} of each day -> the
    rule is VIOLATED on day 1 (penalty present). A same-class swap can
    move ProfB onto hour 8 of day 1 and ProfA off it without breaking
    any HARD constraint, so SA *can* reduce the soft penalty.
    """
    profs = {
        "ProfA": {
            "classi": {"1A": {"Mat": {"ore": 4}}},
            "glibero": [6, 5, 4],
        },
        "ProfB": {
            "classi": {"1A": {"Ita": {"ore": 4}}},
            "glibero": [6, 5, 4],
        },
    }
    sol = {}
    for d in (1, 2):
        for h in (8, 9):
            sol[("ProfA", "1A", "Mat", d, h)] = 1
        for h in (10, 11):
            sol[("ProfB", "1A", "Ita", d, h)] = 1
    # Fill the rest of the (prof, class, subj) slot space with zeros.
    for p, s in (("ProfA", "Mat"), ("ProfB", "Ita")):
        for d in range(1, 7):
            for h in range(8, 14):
                sol.setdefault((p, "1A", s, d, h), 0)
    dc_value = {
        ("ProfA", "1A", "Mat", 1): 2,
        ("ProfA", "1A", "Mat", 2): 2,
        ("ProfB", "1A", "Ita", 1): 2,
        ("ProfB", "1A", "Ita", 2): 2,
    }
    return profs, sol, dc_value


def test_run_sa_honours_soft_rules_without_worsening():
    profs, sol, dc_value = _feasible_world_with_soft()

    # Sanity: the start is HARD-feasible.
    assert meta.is_hard_feasible(sol, profs, verbose=False)

    # SOFT: ProfA must NOT teach on (day1, hour8). Pre-parse via the
    # project helper so the tree comes from the SAME general_dsl module
    # object compute_soft evaluates with (dual-module AST safety).
    expr = (
        'forall l in lessons where l.teacher == "ProfA" '
        'and l.day == 1 and l.hour == 8: false'
    )
    parsed = meta.parse_soft_rules(
        [{"expression": expr, "is_hard": False, "weight": 500,
          "label": "no-ProfA-mon-8"}])
    assert len(parsed) == 1

    # The start solution violates the soft rule.
    _, start_m = meta.compute_soft(sol, profs, soft_rules=parsed)
    start_pen = start_m["dsl_soft"]
    assert start_pen == 500

    new_sol = meta.run_sa(
        sol, profs, dc_value, time_budget_s=2.0,
        T0=5.0, alpha=0.99, log=False, soft_rules=parsed,
    )

    # SACRED: the result must remain HARD-feasible.
    assert meta.is_hard_feasible(new_sol, profs, verbose=False)

    # The soft penalty must not be made WORSE by the run.
    _, end_m = meta.compute_soft(new_sol, profs, soft_rules=parsed)
    assert end_m["dsl_soft"] <= start_pen
