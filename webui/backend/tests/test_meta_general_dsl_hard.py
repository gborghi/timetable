"""Universal DSL solver — the metaheuristic enforces arbitrary DSL HARD.

Symmetric to Subproject D (which wired SOFT DSL through ``run_meta`` →
``compute_soft``), this proves the HARD side:

1. Runner level — ``run_sa`` (and the atomic-move family) REJECT any move
   that would violate an arbitrary DSL HARD expression that the per-day
   CP compiler cannot model (a per-slot teacher forbid). The post-hoc
   ``general_dsl`` evaluator accepts the FULL grammar, so once the moves
   honour it the metaheuristic accepts ANY DSL constraint.

2. ``run_meta`` wiring — the helper ``optimization._load_dsl_hard_expressions``
   loads HARD rule expression STRINGS from the DB (via the same
   ``dsl_translator.load_all_dsl_constraints`` the SOFT path uses) so
   ``run_meta`` can thread them into every runner as
   ``dsl_hard_expressions=``. Strings (not parsed trees) cross the module
   boundary, dodging the dual-module AST hazard.
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


# The DSL HARD expression under test: teacher "ProfA" must NEVER be at
# (day 1, hour 8). This is a per-slot forbid the per-day Phase B CP model
# cannot express as a structural constraint, but the post-hoc DSL
# evaluator understands it natively.
HARD_EXPR = (
    'forall l in lessons where l.teacher == "ProfA" '
    'and l.day == 1 and l.hour == 8: false'
)


def _feasible_world():
    """Small HARD-feasible (profs, sol, dc_value).

    1A has 8 weekly hours (ProfA-Mat 4 + ProfB-Ita 4) over days 1 and 2,
    each day the contiguous block {8,9,10,11} (H1/H2/H3 ok). ProfA-Mat
    starts on {10,11} of each day so it does NOT touch (day1, hour8) —
    the DSL HARD is satisfied at the start.
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
            sol[("ProfB", "1A", "Ita", d, h)] = 1
        for h in (10, 11):
            sol[("ProfA", "1A", "Mat", d, h)] = 1
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


# --------------------------------------------------------------------------
# Runner level — the check has teeth, and run_sa never moves into violation.
# --------------------------------------------------------------------------

def test_is_hard_feasible_dsl_has_teeth():
    """A hand-built solution that DOES place ProfA at (1,8) must be
    rejected by is_hard_feasible when the DSL HARD is supplied — proving
    the DSL layer actually enforces, not no-ops."""
    profs, sol, _ = _feasible_world()

    # Start is HARD-feasible both structurally and against the DSL HARD.
    assert meta.is_hard_feasible(sol, profs, verbose=False)
    assert meta.is_hard_feasible(
        sol, profs, dsl_hard_expressions=[HARD_EXPR])

    # Now build a structurally-feasible variant that swaps ProfA onto
    # (day1, hour8): move ProfA from {10,11} to {8,9} and ProfB from
    # {8,9} to {10,11} on day 1. Still H1/H2/H3 ok, no overlaps, full
    # coverage — but it places ProfA at (1,8).
    viol = dict(sol)
    viol[("ProfA", "1A", "Mat", 1, 10)] = 0
    viol[("ProfA", "1A", "Mat", 1, 11)] = 0
    viol[("ProfA", "1A", "Mat", 1, 8)] = 1
    viol[("ProfA", "1A", "Mat", 1, 9)] = 1
    viol[("ProfB", "1A", "Ita", 1, 8)] = 0
    viol[("ProfB", "1A", "Ita", 1, 9)] = 0
    viol[("ProfB", "1A", "Ita", 1, 10)] = 1
    viol[("ProfB", "1A", "Ita", 1, 11)] = 1

    # Structurally still feasible (no DSL): the swap preserves all HARD.
    assert meta.is_hard_feasible(viol, profs, verbose=False)
    # But the DSL HARD rejects it — the check has teeth.
    assert not meta.is_hard_feasible(
        viol, profs, dsl_hard_expressions=[HARD_EXPR])


def test_run_sa_enforces_arbitrary_dsl_hard():
    """run_sa, given dsl_hard_expressions, must never produce a solution
    that violates the arbitrary DSL HARD — its atomic moves reject such
    moves via is_hard_feasible(..., dsl_hard_expressions=...)."""
    profs, sol, dc_value = _feasible_world()
    assert meta.is_hard_feasible(
        sol, profs, dsl_hard_expressions=[HARD_EXPR])

    result = meta.run_sa(
        sol, profs, dc_value, time_budget_s=2.0,
        T0=10.0, alpha=0.99, log=False,
        dsl_hard_expressions=[HARD_EXPR],
    )

    # The result is HARD-feasible AND honours the DSL HARD.
    assert meta.is_hard_feasible(result, profs, verbose=False)
    assert meta.is_hard_feasible(
        result, profs, dsl_hard_expressions=[HARD_EXPR]), (
        "run_sa produced a solution that violates the DSL HARD")


# --------------------------------------------------------------------------
# run_meta wiring — the hard-expression loader builds the string list.
# --------------------------------------------------------------------------

def test_run_meta_loads_dsl_hard_expressions(app_with_temp_db):
    """optimization._load_dsl_hard_expressions(db) returns the HARD DSL
    expression STRINGS (and NOT the SOFT ones) so run_meta can thread
    them into the runners as dsl_hard_expressions=."""
    from backend import models
    from backend import optimization as opt

    _app, TestSession = app_with_temp_db
    with TestSession() as db:
        # One HARD rule + one SOFT rule.
        db.add(models.GeneralConstraint(
            expression=HARD_EXPR, label="no-ProfA-mon-8",
            level="hard", weight=0, scope="global"))
        db.add(models.GeneralConstraint(
            expression=(
                'forall l in lessons where l.teacher == "ProfB" '
                'and l.day == 2 and l.hour == 13: false'),
            label="soft-rule", level="soft", weight=50, scope="global"))
        db.commit()

        hard = opt._load_dsl_hard_expressions(db)

    assert hard is not None
    assert HARD_EXPR in hard
    # The SOFT rule's expression must NOT be in the HARD list.
    assert all("hour == 13" not in e for e in hard)


def test_load_dsl_hard_expressions_none_when_empty(app_with_temp_db):
    """No HARD rules → loader returns None (zero-drift: runners get the
    default None and behave exactly as before)."""
    from backend import optimization as opt

    _app, TestSession = app_with_temp_db
    with TestSession() as db:
        assert opt._load_dsl_hard_expressions(db) is None
