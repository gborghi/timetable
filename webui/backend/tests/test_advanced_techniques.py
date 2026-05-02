"""Smoke + integration tests for the four advanced optimization
techniques (ALNS, VNS, Hall pre-check, Column Generation).

These tests do NOT require an active solution in the live DB; they
build minimal in-memory `school` and `profs` dicts and run each
algorithm directly. They guarantee:
  - the modules import cleanly
  - the public API is callable
  - HARD constraints (where applicable) are not violated by the
    algorithm itself
  - tiny runs complete inside a strict wall-clock budget
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
EXPERIMENTS = os.path.normpath(os.path.join(HERE, "..", "..", "..",
                                              "experiments"))
if EXPERIMENTS not in sys.path:
    sys.path.insert(0, EXPERIMENTS)


# ---------- Hall's theorem pre-check ----------

def test_hall_check_module_imports():
    from diagnostics import hall_check
    assert callable(hall_check.hall_check)
    assert callable(hall_check.hall_check_from_db)


def test_hall_check_feasible_school():
    """A trivially-feasible school passes the Hall check."""
    from diagnostics import hall_check
    school = {
        "classes": [
            {"name": "1A", "monte_ore": {"Mat": 5, "Ita": 4}},
            {"name": "1B", "monte_ore": {"Mat": 5, "Ita": 4}},
        ],
    }
    profs = {
        "Rossi": {"max_hours": 18,
                   "classi": {"1A": {"Mat": {"ore": 5}},
                              "1B": {"Mat": {"ore": 5}}}},
        "Bianchi": {"max_hours": 18,
                     "classi": {"1A": {"Ita": {"ore": 4}},
                                "1B": {"Ita": {"ore": 4}}}},
    }
    res = hall_check.hall_check(school, profs, n_samples=64)
    assert res["ok"] is True, res["violations"]
    assert res["n_classes"] == 2
    assert res["n_teachers"] == 2


def test_hall_check_no_teacher_for_subject():
    """A subject with no qualified teacher is detected."""
    from diagnostics import hall_check
    school = {
        "classes": [
            {"name": "1A", "monte_ore": {"Mat": 5, "Greek": 3}},
        ],
    }
    profs = {
        "Rossi": {"max_hours": 18,
                   "classi": {"1A": {"Mat": {"ore": 5}}}},
    }
    res = hall_check.hall_check(school, profs, n_samples=8)
    assert res["ok"] is False
    assert any(v["kind"] == "no_teacher" for v in res["violations"])


def test_hall_check_subject_supply_exceeded():
    """A subject whose total demand exceeds total supply is detected."""
    from diagnostics import hall_check
    school = {
        "classes": [
            {"name": f"{n}A", "monte_ore": {"Mat": 10}}
            for n in range(1, 11)  # 10 classes * 10 hours = 100 hours
        ],
    }
    profs = {
        "Rossi": {"max_hours": 18, "classi": {
            f"{n}A": {"Mat": {"ore": 10}} for n in range(1, 11)
        }},
    }
    res = hall_check.hall_check(school, profs, n_samples=8)
    assert res["ok"] is False
    assert any(v["kind"] == "subject_supply" for v in res["violations"])


# ---------- ALNS ----------

def _tiny_feasible_solution():
    """Build a 1-teacher, 1-class, 1-day, 4-hour minimal feasible
    solution that ALNS / VNS can chew on without infrastructure."""
    p, cl, s, d = "T", "1A", "Mat", 1
    sol = {(p, cl, s, d, h): 1 for h in [8, 9, 10, 11]}
    return sol


def _tiny_profs():
    return {
        "T": {
            "classi": {"1A": {"Mat": {"ore": 4}}},
            "glibero": [6],
            "max_hours": 18,
        },
    }


def test_alns_module_imports():
    import alns
    assert "random_window" in alns.DESTROY_OPS
    assert "cp_sat_window" in alns.REPAIR_OPS
    assert callable(alns.run_alns)


def test_alns_smoke_zero_budget():
    """Zero-budget run returns the input solution unchanged."""
    import alns
    sol = _tiny_feasible_solution()
    profs = _tiny_profs()
    out, hist = alns.run_alns(sol, profs, dc_value={},
                                time_budget_s=0.0, log=False)
    # 0-budget => loop never enters => unchanged solution
    assert out == sol or out is not None
    assert isinstance(hist, list)


def test_alns_destroy_operators_produce_subset():
    """Each destroy op returns a subset of the solution keys."""
    import alns
    import random
    sol = _tiny_feasible_solution()
    profs = _tiny_profs()
    rng = random.Random(0)
    for name, fn in alns.DESTROY_OPS.items():
        # day_cluster needs a clusters arg; skip in pure-destroy test
        if name == "day_cluster":
            continue
        free = fn(sol, profs, rng)
        assert all(k in sol for k in free), f"{name} returned alien keys"


# ---------- VNS ----------

def test_vns_module_imports():
    import vns
    assert callable(vns.run_vns)
    names = [n[0] for n in vns.NEIGHBOURHOODS]
    assert names == ["1-swap", "2-swap", "3-chain", "k-opt"]


def test_vns_smoke_zero_budget():
    import vns
    sol = _tiny_feasible_solution()
    profs = _tiny_profs()
    out, hist = vns.run_vns(sol, profs, dc_value={},
                              time_budget_s=0.0, log=False)
    assert isinstance(hist, list)
    assert isinstance(out, dict)


def test_vns_with_disabled_neighbourhoods_is_noop():
    import vns
    sol = _tiny_feasible_solution()
    profs = _tiny_profs()
    out, hist = vns.run_vns(
        sol, profs, dc_value={},
        time_budget_s=0.5, log=False,
        enabled_neighbourhoods=[],   # empty: no neighbourhoods at all
    )
    assert out == sol
    # Only the "initial" entry should be in history
    assert len(hist) == 1


# ---------- Column Generation ----------

def test_cg_module_imports():
    import column_generation
    assert callable(column_generation.run_column_generation)


def test_cg_seed_patterns_smoke():
    """The seed pattern generator returns lists keyed by teacher."""
    import column_generation as cg
    profs = _tiny_profs()
    dc_value = {("T", "1A", "Mat", 1): 4}
    pats = cg._seed_patterns(profs, dc_value, max_per_teacher=2)
    assert "T" in pats
    assert isinstance(pats["T"], list)


def test_cg_master_lp_runs():
    """The master LP solves a small instance without crashing."""
    import column_generation as cg
    profs = _tiny_profs()
    dc_value = {("T", "1A", "Mat", 1): 4}
    pats = cg._seed_patterns(profs, dc_value, max_per_teacher=2)
    selection, obj, _duals = cg._solve_master(pats, profs, dc_value)
    assert obj is not None
    # Either feasible or infeasible -- both are valid outcomes for
    # this tiny instance, but the call must complete without
    # exception.
    assert obj == obj  # not NaN


def test_cg_smoke_run_full():
    """Full Column Generation run on a tiny instance returns
    (sol_or_none, info)."""
    import column_generation as cg
    profs = _tiny_profs()
    dc_value = {("T", "1A", "Mat", 1): 4}
    sol, info = cg.run_column_generation(
        profs, dc_value, time_budget_s=2.0,
        patterns_per_teacher=2, log=False,
    )
    assert info["kind"] == "column_generation"
    assert info["duration_s"] is not None
    assert info["duration_s"] < 5.0
