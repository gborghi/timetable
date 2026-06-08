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
