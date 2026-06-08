"""Post-assembly cross-column HARD-DSL verification for CG / BP.

Branch-and-price decomposes the problem by COLUMN (a per-teacher /
per-class / per-day pattern); a pricer's CP-SAT sub-problem only sees its
own column's scope, so a HARD DSL rule that couples MULTIPLE columns (or
the whole week) cannot be modeled inside any single pricer. Instead,
``run_column_generation`` VERIFIES the assembled full solution post-hoc
against every hard DSL expression passed via ``dsl_hard_expressions=`` and
REPORTS any violation as a structured warning (so the user can run a
metaheuristic post-pass, the universal enforcer).

These tests pin that behaviour as ADDITIVE: the engine still produces a
HARD-feasible solution; the DSL gate only adds reporting.

Self-contained under top-level ``tests/`` so
``pytest tests/test_cg_dsl_post_assembly.py`` runs from the repo root.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
ENGINE = os.path.join(ROOT, "engine")
SCHEDULE = os.path.join(ROOT, "schedule")
for _p in (ENGINE, SCHEDULE):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _two_class_profs():
    """Two-teacher, two-class scaffold (mirrors test_bp_granularities)."""
    return {
        "T1": {
            "classi": {"1A": {"Mat": {"ore": 4}},
                       "1B": {"Mat": {"ore": 4}}},
            "glibero": [6],
            "max_hours": 18,
        },
        "T2": {
            "classi": {"1A": {"Ita": {"ore": 4}},
                       "1B": {"Ita": {"ore": 4}}},
            "glibero": [6],
            "max_hours": 18,
        },
    }


def _two_class_dc():
    """Each cattedra on its own day; T1 Mat 1A lives on day 1."""
    return {
        ("T1", "1A", "Mat", 1): 4,
        ("T1", "1B", "Mat", 2): 4,
        ("T2", "1A", "Ita", 3): 4,
        ("T2", "1B", "Ita", 4): 4,
    }


def _run_cg(dsl_hard_expressions):
    import column_generation as cg
    return cg.run_column_generation(
        _two_class_profs(), _two_class_dc(),
        time_budget_s=30.0, patterns_per_teacher=2, max_iterations=2,
        log=False, dsl_hard_expressions=dsl_hard_expressions,
    )


def test_post_assembly_reports_violated_cross_column_dsl():
    """A whole-week HARD DSL the pricer cannot see (T1 must have NO
    lesson on day 1 -- but the day-counts force 4 there) is DETECTED
    and REPORTED post-assembly, while CG still returns a feasible sol."""
    # T1's Mat for 1A is pinned to day 1 by the day-counts, so any
    # assembled solution places T1 on day 1 -> this rule is violated.
    expr = 'forall l in lessons where l.teacher == "T1" and l.day == 1: false'
    sol, info = _run_cg([expr])

    # CG still produces a HARD-feasible solution (the DSL gate is additive).
    assert sol is not None, info
    assert (info["feasible_after_assembly"]
            or info["feasible_after_completion"]), info

    # The cross-column DSL violation is detected + reported.
    assert info.get("dsl_unsatisfied") == [expr], info.get("dsl_unsatisfied")
    warns = info.get("dsl_warnings") or []
    assert warns, "expected at least one structured DSL warning"
    w0 = warns[0]
    assert w0["pipeline"] == "branch_and_price", w0
    # The full expression is preserved verbatim in `dsl_unsatisfied`
    # (asserted above) and in the warning's `raw` diagnostic; the
    # `constraint` label is the constraint_compat short form (it splits
    # on ':' so the trailing ': false' is trimmed -- that's expected).
    assert expr in w0["raw"], w0
    assert "not_modeled_in_pricer" in w0["raw"], w0
    # The free-text warnings list also carries a human-readable line.
    assert any("cross-column" in str(x) for x in info.get("warnings", [])), \
        info.get("warnings")


def test_post_assembly_satisfied_dsl_no_warning():
    """A HARD DSL satisfied by the assembled solution produces NO DSL
    warning (the gate is silent when everything holds)."""
    # T1 is never scheduled at the 6th hour (hour 13) in this scaffold,
    # so forbidding it is trivially satisfied.
    expr = ('forall l in lessons where l.teacher == "T1" '
            'and l.hour == 13: false')
    sol, info = _run_cg([expr])
    assert sol is not None, info
    assert "dsl_unsatisfied" not in info, info.get("dsl_unsatisfied")
    assert not info.get("dsl_warnings"), info.get("dsl_warnings")


def test_no_dsl_exprs_is_byte_identical_default():
    """dsl_hard_expressions=None (the default) leaves the result and
    info untouched by the gate -- zero-drift."""
    sol, info = _run_cg(None)
    assert sol is not None, info
    assert "dsl_unsatisfied" not in info
    assert "dsl_warnings" not in info
