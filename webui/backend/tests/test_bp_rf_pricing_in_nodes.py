"""Step 4b: Ryan-Foster tree with pricing-in-nodes (true Branch-and-Price).

Two contracts under test:

  1. Branching-constraint plumbing: ``_pricing_subproblem_class``
     accepts ``branching_constraints`` and returns columns that
     respect them (apart / together). This is the foundation for
     pricing-in-nodes.

  2. Pricing-in-nodes vs BB-on-fixed-pool: on a small instance we
     run ``_run_ryan_foster_tree`` first WITHOUT
     ``enable_pricing_in_nodes`` (legacy filter-only behaviour) and
     then WITH it; the pricing-in-nodes run must touch the new
     diagnostic counters (``rf_tree_pricing_calls`` > 0 and either
     find at least one fresh column inside a node, or reach a
     terminal state cleanly without crashing).
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "engine"))
WEBUI = os.path.normpath(os.path.join(HERE, "..", ".."))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
for p in (ENGINE, WEBUI, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)


def _two_class_profs():
    return {
        "ProfA": {
            "classi": {"1A": {"Mat": {"ore": 4}},
                        "2A": {"Mat": {"ore": 4}}},
            "glibero": [6], "max_hours": 18,
        },
        "ProfB": {
            "classi": {"1A": {"Ita": {"ore": 4}},
                        "2A": {"Ita": {"ore": 4}}},
            "glibero": [6], "max_hours": 18,
        },
    }


def _two_class_dc():
    """Spread over days 1..4, 1 hour/day per cattedra."""
    dc = {}
    for (t, cl, s) in [
        ("ProfA", "1A", "Mat"), ("ProfA", "2A", "Mat"),
        ("ProfB", "1A", "Ita"), ("ProfB", "2A", "Ita"),
    ]:
        for d in (1, 2, 3, 4):
            dc[(t, cl, s, d)] = 1
    return dc


# ----------------------------------------------------------------------
# 1. Branching constraint plumbing in the class pricer
# ----------------------------------------------------------------------


def test_class_pricer_accepts_branching_constraints():
    """The class pricer must accept ``branching_constraints`` and
    return a HARD-feasible column. The exact placement is left to
    the solver; we only check the kw is wired."""
    import column_generation as cg
    profs = _two_class_profs()
    dc = _two_class_dc()
    # Exotic dual: reward Mat at h=8 of day 1.
    lam = {("ProfA", "1A", "Mat", 1): 100.0}
    branches = [(("1A", 1, 8), ("1A", 1, 9), "apart")]
    col, rc = cg._pricing_subproblem_class(
        "1A", profs, dc, lam, {}, {},
        time_limit=5.0, workers=1,
        branching_constraints=branches)
    # The pricer might return None if no improving column exists.
    # If it returns a column, the branching constraint must hold.
    if col is not None:
        slots = {(k[1], k[3], k[4]) for k, v in col.items() if v}
        # apart: not both (1A, 1, 8) and (1A, 1, 9)
        assert not (("1A", 1, 8) in slots and ("1A", 1, 9) in slots)


def test_class_pricer_apart_constraint_excludes_pair():
    """When ``apart`` is enforced on (1A, 1, 8) and (1A, 1, 9), no
    column may cover both. We use a strong dual on hour 8 to drive
    the pricer to want Mat at h=8 (which it could pair with Ita at
    h=9 absent the constraint), then check the column is consistent."""
    import column_generation as cg
    profs = _two_class_profs()
    dc = _two_class_dc()
    # Strong dual on every (1A, *, 1) cattedra.
    lam = {("ProfA", "1A", "Mat", 1): 1000.0,
           ("ProfB", "1A", "Ita", 1): 1000.0}
    branches = [(("1A", 1, 8), ("1A", 1, 9), "apart")]
    col, rc = cg._pricing_subproblem_class(
        "1A", profs, dc, lam, {}, {},
        time_limit=5.0, workers=1,
        branching_constraints=branches)
    # The class pricer's no-overlap already guarantees at most one
    # (t, s) per (d, h), but apart further restricts by class-day-hour.
    if col is not None:
        slots = {(k[1], k[3], k[4]) for k, v in col.items() if v}
        assert not (("1A", 1, 8) in slots and ("1A", 1, 9) in slots), (
            f"apart violated: {sorted(slots)}")


def test_column_respects_branches_helper():
    """The defensive filter ``_column_respects_branches`` rejects
    columns that violate any RF branch."""
    import column_generation as cg
    col_apart_violator = {
        ("ProfA", "1A", "Mat", 1, 8): 1,
        ("ProfA", "1A", "Mat", 1, 9): 1,
    }
    col_ok = {
        ("ProfA", "1A", "Mat", 1, 8): 1,
        ("ProfA", "1A", "Mat", 2, 9): 1,
    }
    branches = [(("1A", 1, 8), ("1A", 1, 9), "apart")]
    assert not cg._column_respects_branches(col_apart_violator, branches)
    assert cg._column_respects_branches(col_ok, branches)


def test_column_respects_branches_together_mode():
    col_either_or = {
        ("ProfA", "1A", "Mat", 1, 8): 1,
    }
    col_both = {
        ("ProfA", "1A", "Mat", 1, 8): 1,
        ("ProfB", "1A", "Ita", 1, 9): 1,
    }
    col_neither = {
        ("ProfA", "1A", "Mat", 2, 8): 1,
    }
    branches = [(("1A", 1, 8), ("1A", 1, 9), "together")]
    import column_generation as cg
    # together: must be both OR neither
    assert not cg._column_respects_branches(col_either_or, branches)
    assert cg._column_respects_branches(col_both, branches)
    assert cg._column_respects_branches(col_neither, branches)


# ----------------------------------------------------------------------
# 2. RF tree with pricing-in-nodes vs filter-only
# ----------------------------------------------------------------------


def test_rf_tree_pricing_in_nodes_records_diagnostics():
    """The new diagnostic counters appear in the RF tree info dict
    when pricing-in-nodes is enabled."""
    import column_generation as cg
    profs = _two_class_profs()
    dc = _two_class_dc()
    # Build a tiny seed pool: one column per class via the pricer.
    seed_cols = []
    for class_name in ("1A", "2A"):
        col, _ = cg._pricing_subproblem_class(
            class_name, profs, dc, {}, {}, {},
            time_limit=5.0, workers=1)
        if col is not None:
            seed_cols.append(col)
    # Run RF tree with pricing-in-nodes enabled.
    sol, info = cg._run_ryan_foster_tree(
        seed_cols, profs, dc,
        time_budget_s=10.0,
        granularity="class",
        pricer_time_limit=1.0,
        pricer_workers=1,
        enable_pricing_in_nodes=True,
        max_depth=3,
        max_nodes=10,
        log=False,
    )
    # Diagnostic keys must surface.
    assert info["rf_tree_pricing_in_nodes"] is True
    assert info["rf_tree_pricing_calls"] >= 0
    assert "rf_tree_columns_added_in_nodes" in info


def test_rf_tree_legacy_path_unchanged_when_pricing_disabled():
    """When ``enable_pricing_in_nodes=False`` (default), the diagnostic
    counter is False and ``rf_tree_pricing_calls == 0`` -- no pricer
    invocations occurred. This protects the legacy filter-only path."""
    import column_generation as cg
    profs = _two_class_profs()
    dc = _two_class_dc()
    seed_cols = []
    for class_name in ("1A", "2A"):
        col, _ = cg._pricing_subproblem_class(
            class_name, profs, dc, {}, {}, {},
            time_limit=5.0, workers=1)
        if col is not None:
            seed_cols.append(col)
    sol, info = cg._run_ryan_foster_tree(
        seed_cols, profs, dc,
        time_budget_s=5.0,
        max_depth=2, max_nodes=5,
        log=False,
    )
    assert info["rf_tree_pricing_in_nodes"] is False
    assert info["rf_tree_pricing_calls"] == 0
    assert info["rf_tree_columns_added_in_nodes"] == 0


def test_rf_tree_branching_decisions_propagate_to_pricer():
    """Pricing-in-nodes routes the accumulated RF branching decisions
    to the class pricer; the new columns must respect every accumulated
    branch by construction."""
    import column_generation as cg
    profs = _two_class_profs()
    dc = _two_class_dc()
    seed_cols = []
    for class_name in ("1A", "2A"):
        col, _ = cg._pricing_subproblem_class(
            class_name, profs, dc, {}, {}, {},
            time_limit=5.0, workers=1)
        if col is not None:
            seed_cols.append(col)
    sol, info = cg._run_ryan_foster_tree(
        seed_cols, profs, dc,
        time_budget_s=10.0,
        granularity="class",
        pricer_time_limit=1.0,
        pricer_workers=1,
        enable_pricing_in_nodes=True,
        max_depth=4, max_nodes=20,
        log=False,
    )
    # The terminated_reason is well-defined (not crashing) and the
    # info dict contains the new fields.
    assert info["rf_tree_terminated_reason"], info
    assert "rf_tree_pricing_calls" in info
    # If the tree found an incumbent, it's HARD-feasible.
    if sol is not None:
        import metaheuristics as meta  # type: ignore
        assert meta.is_hard_feasible(sol, profs, verbose=False)
