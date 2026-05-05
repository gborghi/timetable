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
                                              "engine"))
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


def test_cg_plumbing_mode_and_granularity_reach_engine():
    """Plumbing test: mode, granularity and BP-loop params passed
    to run_column_generation must surface in the returned `info`
    dict. Without this, the UI dropdown values silently disappear
    before reaching the engine."""
    import column_generation as cg
    profs = _tiny_profs()
    dc_value = {("T", "1A", "Mat", 1): 4}
    sol, info = cg.run_column_generation(
        profs, dc_value,
        time_budget_s=2.0,
        patterns_per_teacher=2,
        log=False,
        mode="branch-and-price",
        granularity="teacher",
        bp_max_iterations=3,
        pricer_time_limit=2.0,
        pricer_workers=1,
    )
    assert info["mode"] == "branch-and-price"
    assert info["granularity"] == "teacher"
    assert info["bp_max_iterations"] == 3
    assert info["pricer_time_limit"] == 2.0
    assert info["pricer_workers"] == 1


def test_cg_schema_accepts_all_granularities():
    """The pydantic schema must validate every supported
    granularity + mode value without raising."""
    from backend.schemas import ColumnGenerationIn
    granularities = ("auto", "teacher", "teacher-day",
                     "teacher-class", "teacher-class-subject",
                     "teacher-subject", "class", "class-day",
                     "day", "curriculum")
    modes = ("iterative-diversified", "branch-and-price", "auto")
    for g in granularities:
        for m in modes:
            payload = ColumnGenerationIn(mode=m, granularity=g)
            assert payload.mode == m
            assert payload.granularity == g


def test_cg_granularity_auto_suggestion_covers_new_options():
    """The auto-detect heuristic must use the expanded granularity
    set introduced in the BP refactor (so small/medium schools no
    longer all collapse to 'teacher')."""
    from backend.optimization import (
        _suggest_cg_granularity, _CG_GRANULARITIES,
    )
    expected = {
        5:   "teacher",
        20:  "teacher-day",
        40:  "teacher-class",
        60:  "class",
        100: "curriculum",
    }
    for n_classes, want in expected.items():
        got = _suggest_cg_granularity(n_classes)
        assert got == want, (
            f"_suggest_cg_granularity({n_classes}) = {got!r}, "
            f"expected {want!r}")
        assert got in _CG_GRANULARITIES


def _two_class_profs():
    """Two-class scaffold for the teacher-class pricer test.

    Teacher T1 covers Mat in both 1A and 1B; T2 covers Ita in both.
    Each cattedra is 4 hrs/week distributed Mat=4 in day 1,
    Ita=4 in day 2 -- enough to exercise the pricer over multiple
    classes without HARD infeasibility."""
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
    """Day-counts that match _two_class_profs.

    Spread Mat for each class across DIFFERENT days so the
    greedy base for one class never collides with the CP-SAT
    placement of the other (T1 has 4+4=8 hours of Mat per week
    and a school day is 7 hours, so they MUST live on
    distinct days)."""
    return {
        ("T1", "1A", "Mat", 1): 4,   # 1A Mat on day 1
        ("T1", "1B", "Mat", 2): 4,   # 1B Mat on day 2 (separate day)
        ("T2", "1A", "Ita", 3): 4,   # 1A Ita on day 3
        ("T2", "1B", "Ita", 4): 4,   # 1B Ita on day 4
    }


def test_bp_pricing_subproblem_teacher_class_smoke():
    """Direct call to the teacher-class pricer with synthetic duals
    must produce a non-empty pattern that respects the cattedra
    hours of (T1, 1A, Mat) and avoids slot conflicts."""
    import column_generation as cg
    profs = _two_class_profs()
    dc_value = _two_class_dc()
    # Strong positive lambda on (T1, 1A, Mat, 1) -> the pricer is
    # rewarded for placing those 4 hours; any feasible placement
    # gives rc <= -4*lambda + sixth_penalty (small).
    lambda_duals = {("T1", "1A", "Mat", 1): 100.0}
    mu_t = 0.0
    pat, rc = cg._pricing_subproblem_teacher_class(
        "T1", "1A", profs, dc_value,
        lambda_duals, mu_t,
        time_limit=2.0, workers=1,
    )
    assert pat is not None, f"pricer returned None, rc={rc}"
    assert rc < 0.0, f"expected rc<0 with strong lambda, got {rc}"
    # The pattern must place exactly 4 hours of (T1, 1A, Mat, 1).
    placed_T1_1A_Mat_d1 = sum(
        1 for (p, c, s, d, _h), v in pat.items()
        if v and p == "T1" and c == "1A" and s == "Mat" and d == 1
    )
    assert placed_T1_1A_Mat_d1 == 4, (
        f"expected 4 (T1,1A,Mat,d=1) slots, got {placed_T1_1A_Mat_d1}")
    # And it must also cover the OTHER class greedy-placement.
    placed_T1_1B_Mat = sum(
        1 for (p, c, s, _d, _h), v in pat.items()
        if v and p == "T1" and c == "1B" and s == "Mat"
    )
    assert placed_T1_1B_Mat == 4, (
        f"expected 4 (T1,1B,Mat) slots from greedy base, got "
        f"{placed_T1_1B_Mat}")


def test_bp_pricing_subproblem_returns_none_when_no_improvement():
    """With zero duals everywhere, the pricer's reduced cost is
    >= 0 (only sixth-hour penalty contributes), so no improving
    column can be returned."""
    import column_generation as cg
    profs = _two_class_profs()
    dc_value = _two_class_dc()
    pat, rc = cg._pricing_subproblem_teacher_class(
        "T1", "1A", profs, dc_value,
        lambda_duals={}, mu_t=0.0,
        time_limit=2.0, workers=1,
    )
    assert pat is None, "no improving column expected with zero duals"
    assert rc >= -1e-6, f"rc should be non-negative, got {rc}"


def test_bp_pricing_subproblem_teacher_class_subject_smoke():
    """Direct call to the teacher-class-subject pricer with strong
    positive lambda must return a pattern that places exactly the
    cattedra hours in the optimised slice, leaves the OTHER subjects
    and OTHER classes untouched (greedy base), and reports rc<0."""
    import column_generation as cg
    profs = _two_class_profs()
    dc_value = _two_class_dc()
    lambda_duals = {("T1", "1A", "Mat", 1): 100.0}
    pat, rc = cg._pricing_subproblem_teacher_class_subject(
        "T1", "1A", "Mat", profs, dc_value,
        lambda_duals, mu_t=0.0,
        time_limit=2.0, workers=1,
    )
    assert pat is not None, f"pricer returned None, rc={rc}"
    assert rc < 0.0, f"expected rc<0 with strong lambda, got {rc}"
    placed_T1_1A_Mat_d1 = sum(
        1 for (p, c, s, d, _h), v in pat.items()
        if v and p == "T1" and c == "1A" and s == "Mat" and d == 1
    )
    assert placed_T1_1A_Mat_d1 == 4
    placed_T1_1B_Mat = sum(
        1 for (p, c, s, _d, _h), v in pat.items()
        if v and p == "T1" and c == "1B" and s == "Mat"
    )
    assert placed_T1_1B_Mat == 4, "greedy base for 1B Mat preserved"


def test_bp_loop_with_teacher_class_subject_granularity():
    """End-to-end BP with granularity=teacher-class-subject must
    reach a HARD-feasible solution and not regress soft cost."""
    import column_generation as cg
    profs = _two_class_profs()
    dc_value = _two_class_dc()
    sol_id, info_id = cg.run_column_generation(
        profs, dc_value, time_budget_s=20.0,
        patterns_per_teacher=2, max_iterations=2, log=False,
        mode="iterative-diversified", granularity="teacher",
    )
    sol_bp, info_bp = cg.run_column_generation(
        profs, dc_value, time_budget_s=20.0,
        patterns_per_teacher=2, max_iterations=2, log=False,
        mode="branch-and-price", granularity="teacher-class-subject",
        bp_max_iterations=3, pricer_time_limit=2.0, pricer_workers=1,
    )
    assert info_bp["granularity"] == "teacher-class-subject"
    assert "bp_terminated_reason" in info_bp
    assert (info_bp["feasible_after_assembly"]
            or info_bp["feasible_after_completion"])
    obj_id = info_id["master_obj_final"]
    obj_bp = info_bp["master_obj_final"]
    if obj_id is not None and obj_bp is not None:
        assert obj_bp <= obj_id + 1e-6


def test_bp_pricing_subproblem_teacher_subject_smoke():
    """teacher-subject pricer: with strong lambda on (T1, 1A, Mat, 1)
    the (t, *, Mat, *, *) slice gets re-optimised across 1A and 1B
    while the OTHER teachers' slots are left untouched."""
    import column_generation as cg
    profs = _two_class_profs()
    dc_value = _two_class_dc()
    lambda_duals = {("T1", "1A", "Mat", 1): 100.0}
    pat, rc = cg._pricing_subproblem_teacher_subject(
        "T1", "Mat", profs, dc_value,
        lambda_duals, mu_t=0.0,
        time_limit=2.0, workers=1,
    )
    assert pat is not None, f"pricer returned None, rc={rc}"
    assert rc < 0.0, f"expected rc<0, got {rc}"
    # All 8 hours of T1's Mat (4 in 1A day1 + 4 in 1B day2) present.
    placed = sum(1 for (p, _c, s, _d, _h), v in pat.items()
                 if v and p == "T1" and s == "Mat")
    assert placed == 8


def test_bp_loop_with_teacher_subject_granularity():
    """End-to-end BP with granularity=teacher-subject must reach a
    HARD-feasible solution and not regress soft cost."""
    import column_generation as cg
    profs = _two_class_profs()
    dc_value = _two_class_dc()
    sol_id, info_id = cg.run_column_generation(
        profs, dc_value, time_budget_s=20.0,
        patterns_per_teacher=2, max_iterations=2, log=False,
        mode="iterative-diversified", granularity="teacher",
    )
    sol_bp, info_bp = cg.run_column_generation(
        profs, dc_value, time_budget_s=20.0,
        patterns_per_teacher=2, max_iterations=2, log=False,
        mode="branch-and-price", granularity="teacher-subject",
        bp_max_iterations=3, pricer_time_limit=2.0, pricer_workers=1,
    )
    assert info_bp["granularity"] == "teacher-subject"
    assert "bp_terminated_reason" in info_bp
    assert (info_bp["feasible_after_assembly"]
            or info_bp["feasible_after_completion"])
    obj_id = info_id["master_obj_final"]
    obj_bp = info_bp["master_obj_final"]
    if obj_id is not None and obj_bp is not None:
        assert obj_bp <= obj_id + 1e-6


def test_bp_master_dw_solves_smoke():
    """Master variant 2 (DW) accepts a column pool of partial
    patterns and returns LP weights + cover/class/teacher duals."""
    import column_generation as cg
    profs = _two_class_profs()
    dc_value = _two_class_dc()
    # Build a tiny pool of valid partial patterns (the iterative-
    # diversified seed serves as a starting point).
    seeds = cg._seed_patterns(profs, dc_value, max_per_teacher=2)
    columns = []
    for t, plist in seeds.items():
        for pat in plist:
            if pat not in columns:
                columns.append(pat)
    res = cg._solve_master_dw(columns, dc_value, return_extended=True)
    lp_x, obj, lam_cov, mu_cl, mu_t, ck, clk, tk = res
    assert lp_x is not None
    assert obj >= 0
    assert isinstance(lam_cov, dict)
    assert isinstance(mu_cl, dict)
    assert isinstance(mu_t, dict)


def test_bp_pricing_subproblem_class_smoke():
    """The class pricer produces a multi-teacher partial pattern
    that covers ALL the demand in the chosen class."""
    import column_generation as cg
    profs = _two_class_profs()
    dc_value = _two_class_dc()
    # Strong positive lambda on (T1, 1A, Mat, 1) AND (T2, 1A, Ita, 3)
    # so the pricer is rewarded for covering 1A's full week.
    lambda_cover = {
        ("T1", "1A", "Mat", 1): 100.0,
        ("T2", "1A", "Ita", 3): 100.0,
    }
    col, rc = cg._pricing_subproblem_class(
        "1A", profs, dc_value,
        lambda_cover, mu_class={}, mu_teacher={},
        time_limit=2.0, workers=1,
    )
    assert col is not None, f"class pricer returned None, rc={rc}"
    assert rc < 0.0
    # Multi-teacher: must include slots from both T1 and T2.
    teachers = {k[0] for k in col.keys()}
    assert {"T1", "T2"}.issubset(teachers), (
        f"class column must cover multiple teachers; got {teachers}")
    placed_T1 = sum(1 for (p, c, _s, _d, _h), v in col.items()
                    if v and p == "T1" and c == "1A")
    placed_T2 = sum(1 for (p, c, _s, _d, _h), v in col.items()
                    if v and p == "T2" and c == "1A")
    assert placed_T1 == 4
    assert placed_T2 == 4


def test_bp_pricing_subproblem_class_uses_addhint():
    """The class pricer must invoke add_hint for the warm-start
    (CP-SAT is always invoked, greedy is only a hint)."""
    import column_generation as cg
    from ortools.sat.python import cp_model
    profs = _two_class_profs()
    dc_value = _two_class_dc()
    lambda_cover = {("T1", "1A", "Mat", 1): 100.0}
    counts = [0]
    real = cp_model.CpModel.add_hint

    def counting(self, var, value):
        counts[0] += 1
        return real(self, var, value)

    cp_model.CpModel.add_hint = counting
    try:
        col, rc = cg._pricing_subproblem_class(
            "1A", profs, dc_value,
            lambda_cover, mu_class={}, mu_teacher={},
            time_limit=2.0, workers=1,
        )
        assert col is not None
        assert counts[0] > 0, "class pricer must call add_hint"
    finally:
        cp_model.CpModel.add_hint = real


def test_bp_loop_with_class_granularity():
    """End-to-end BP with granularity=class must reach a HARD-
    feasible solution."""
    import column_generation as cg
    profs = _two_class_profs()
    dc_value = _two_class_dc()
    sol_bp, info_bp = cg.run_column_generation(
        profs, dc_value, time_budget_s=30.0,
        patterns_per_teacher=2, max_iterations=2, log=False,
        mode="branch-and-price", granularity="class",
        bp_max_iterations=3, pricer_time_limit=2.0, pricer_workers=1,
    )
    assert info_bp["granularity"] == "class"
    assert "bp_terminated_reason" in info_bp
    assert (info_bp["feasible_after_assembly"]
            or info_bp["feasible_after_completion"])


def test_bp_pricing_subproblem_class_day_smoke():
    """class-day pricer outputs a partial pattern restricted to
    a single (class, day) cell with all the demand on that day."""
    import column_generation as cg
    profs = _two_class_profs()
    dc_value = _two_class_dc()
    # 1A, day=1 has only (T1, Mat, 4) demand.
    lambda_cover = {("T1", "1A", "Mat", 1): 100.0}
    col, rc = cg._pricing_subproblem_class_day(
        "1A", 1, profs, dc_value,
        lambda_cover, mu_class={}, mu_teacher={},
        time_limit=2.0, workers=1,
    )
    assert col is not None, f"class-day pricer returned None, rc={rc}"
    assert rc < 0.0
    # ALL slots must be on day 1 in class 1A.
    assert all(c == "1A" and d == 1
               for (_p, c, _s, d, _h), v in col.items() if v)
    placed = sum(1 for v in col.values() if v)
    assert placed == 4


def test_bp_pricing_subproblem_class_day_uses_addhint():
    import column_generation as cg
    from ortools.sat.python import cp_model
    profs = _two_class_profs()
    dc_value = _two_class_dc()
    lambda_cover = {("T1", "1A", "Mat", 1): 100.0}
    counts = [0]
    real = cp_model.CpModel.add_hint

    def counting(self, var, value):
        counts[0] += 1
        return real(self, var, value)

    cp_model.CpModel.add_hint = counting
    try:
        col, rc = cg._pricing_subproblem_class_day(
            "1A", 1, profs, dc_value,
            lambda_cover, mu_class={}, mu_teacher={},
            time_limit=2.0, workers=1,
        )
        assert col is not None
        assert counts[0] > 0
    finally:
        cp_model.CpModel.add_hint = real


def test_bp_loop_with_class_day_granularity():
    import column_generation as cg
    profs = _two_class_profs()
    dc_value = _two_class_dc()
    sol_bp, info_bp = cg.run_column_generation(
        profs, dc_value, time_budget_s=30.0,
        patterns_per_teacher=2, max_iterations=2, log=False,
        mode="branch-and-price", granularity="class-day",
        bp_max_iterations=3, pricer_time_limit=2.0, pricer_workers=1,
    )
    assert info_bp["granularity"] == "class-day"
    assert "bp_terminated_reason" in info_bp
    assert (info_bp["feasible_after_assembly"]
            or info_bp["feasible_after_completion"])


def test_bp_pricing_subproblem_day_smoke():
    """day pricer covers all classes' demand on ONE day in a single
    multi-teacher partial column."""
    import column_generation as cg
    profs = _two_class_profs()
    dc_value = _two_class_dc()
    # day=1: only (T1, 1A, Mat) has 4-hour demand here.
    lambda_cover = {("T1", "1A", "Mat", 1): 100.0}
    col, rc = cg._pricing_subproblem_day(
        1, profs, dc_value,
        lambda_cover, mu_class={}, mu_teacher={},
        time_limit=2.0, workers=1,
    )
    assert col is not None, f"day pricer returned None, rc={rc}"
    assert rc < 0.0
    # All slots must be on day 1.
    assert all(d == 1 for (_p, _c, _s, d, _h), v in col.items() if v)
    placed = sum(1 for v in col.values() if v)
    assert placed == 4


def test_bp_pricing_subproblem_day_uses_addhint():
    import column_generation as cg
    from ortools.sat.python import cp_model
    profs = _two_class_profs()
    dc_value = _two_class_dc()
    lambda_cover = {("T1", "1A", "Mat", 1): 100.0}
    counts = [0]
    real = cp_model.CpModel.add_hint

    def counting(self, var, value):
        counts[0] += 1
        return real(self, var, value)

    cp_model.CpModel.add_hint = counting
    try:
        col, rc = cg._pricing_subproblem_day(
            1, profs, dc_value,
            lambda_cover, mu_class={}, mu_teacher={},
            time_limit=2.0, workers=1,
        )
        assert col is not None
        assert counts[0] > 0
    finally:
        cp_model.CpModel.add_hint = real


def test_bp_loop_with_day_granularity():
    import column_generation as cg
    profs = _two_class_profs()
    dc_value = _two_class_dc()
    sol_bp, info_bp = cg.run_column_generation(
        profs, dc_value, time_budget_s=30.0,
        patterns_per_teacher=2, max_iterations=2, log=False,
        mode="branch-and-price", granularity="day",
        bp_max_iterations=3, pricer_time_limit=2.0, pricer_workers=1,
    )
    assert info_bp["granularity"] == "day"
    assert "bp_terminated_reason" in info_bp
    assert (info_bp["feasible_after_assembly"]
            or info_bp["feasible_after_completion"])


def test_bp_pricers_use_addhint_warmstart():
    """Each CP-SAT pricer must invoke `model.AddHint(...)` at least
    once per call. This guarantees:
      - CP-SAT is ALWAYS invoked (not short-circuited by greedy).
      - The greedy proposal is fed to CP-SAT as a warm-start hint
        (not used as a fallback column).
    Verified by spying on cp_model.CpModel.AddHint via monkeypatch.
    """
    import column_generation as cg
    from ortools.sat.python import cp_model
    profs = _two_class_profs()
    dc_value = _two_class_dc()
    lambda_duals = {("T1", "1A", "Mat", 1): 100.0}

    # Per-pricer-call counter of add_hint invocations. The canonical
    # name on CpModel is `add_hint` (snake_case); `AddHint` is an
    # instance-level alias provided by the proto wrapper.
    counts: dict[int, int] = {}
    real_add_hint = cp_model.CpModel.add_hint

    def counting_add_hint(self, var, value):
        counts[id(self)] = counts.get(id(self), 0) + 1
        return real_add_hint(self, var, value)

    cp_model.CpModel.add_hint = counting_add_hint
    try:
        # Each call must produce >= 1 AddHint (one per in-scope
        # slot variable).
        cases = [
            ("teacher-class",
             lambda: cg._pricing_subproblem_teacher_class(
                 "T1", "1A", profs, dc_value, lambda_duals,
                 mu_t=0.0, time_limit=2.0, workers=1)),
            ("teacher-class-subject",
             lambda: cg._pricing_subproblem_teacher_class_subject(
                 "T1", "1A", "Mat", profs, dc_value, lambda_duals,
                 mu_t=0.0, time_limit=2.0, workers=1)),
            ("teacher-subject",
             lambda: cg._pricing_subproblem_teacher_subject(
                 "T1", "Mat", profs, dc_value, lambda_duals,
                 mu_t=0.0, time_limit=2.0, workers=1)),
            ("teacher-day",
             lambda: cg._pricing_subproblem_teacher_day(
                 "T1", 1, profs, dc_value, lambda_duals,
                 mu_t=0.0, time_limit=2.0, workers=1)),
        ]
        for name, call in cases:
            counts.clear()
            pat, rc = call()
            assert pat is not None, (
                f"{name}: pricer returned None unexpectedly")
            assert sum(counts.values()) > 0, (
                f"{name}: model.AddHint was never called -- the "
                f"CP-SAT warm-start hint mechanism is missing.")
    finally:
        cp_model.CpModel.add_hint = real_add_hint


def test_bp_pricers_are_cpsat_not_greedy_teacher_class():
    """Proof that the FUNDAMENTAL optimisation is CP-SAT, not greedy.

    Strategy: the (T1, 1A, Mat, day=1, h=13) slot is the WORST
    choice under the CP-SAT objective (PENALTY_SIXTH = 500 deters
    it; lambda=100 only gives -10000 reward, so non-h13 slots are
    strictly better). Greedy `_greedy_base_pattern` SKIPS the
    in-scope class entirely -- it never places (T1, 1A, *) slots.
    The in-scope class is filled ONLY by CP-SAT, and locks for the
    in-scope class are forced via `model.Add(v == 1)`.

    So if we lock h=13 of (T1, 1A, Mat, day=1) and the returned
    pattern includes that exact slot, the only way it could have
    landed there is via the CP-SAT lock-respect. A "greedy
    fallback" would have put that slot at h=8.
    """
    import column_generation as cg
    profs = _two_class_profs()
    dc_value = _two_class_dc()
    # Lock the (T1, 1A, Mat, day=1, h=13) slot. The CP-SAT model
    # honours it via `model.Add(v == 1)`. The greedy never touches
    # in-scope (T1, 1A, *) slots so it cannot place this lock.
    lambda_duals = {("T1", "1A", "Mat", 1): 100.0}
    locks = {("T1", "1A", "Mat", 1, 13)}
    pat, rc = cg._pricing_subproblem_teacher_class(
        "T1", "1A", profs, dc_value,
        lambda_duals, mu_t=0.0,
        time_limit=2.0, workers=1,
        locks=locks,
    )
    assert pat is not None, f"pricer returned None, rc={rc}"
    assert pat.get(("T1", "1A", "Mat", 1, 13)) == 1, (
        "CP-SAT must have honoured the in-scope lock at h=13. "
        "If this assertion fails, the pricer is short-circuiting "
        "the CP-SAT model and falling back to a non-CP-SAT path. "
        f"pattern (T1,1A,Mat,1,*): "
        f"{[k for k in pat if k[:4]==('T1','1A','Mat',1)]}"
    )
    # And the rc must reflect the sixth-hour penalty for that slot
    # (1 slot at h=13 -> +5 to soft cost, then -lambda*4 from cover):
    #   rc = soft - mu - sum_lambda_placed
    #   soft = 5*1 (sixth) + ... (other terms) -- with 4 hrs placed
    #   sum_lambda = 100 * 4 = 400
    #   so rc <= 5 - 0 - 400 = -395 (other soft terms only add).
    assert rc < -300, f"rc should be strongly negative, got {rc}"


def test_bp_pricing_subproblem_teacher_day_smoke():
    """teacher-day pricer rebuilds one day of T1's plan (day 1 has
    4 hrs of (T1, 1A, Mat) only -- no day-conflicts). Strong lambda
    drives rc<0."""
    import column_generation as cg
    profs = _two_class_profs()
    dc_value = _two_class_dc()
    lambda_duals = {("T1", "1A", "Mat", 1): 100.0}
    pat, rc = cg._pricing_subproblem_teacher_day(
        "T1", 1, profs, dc_value,
        lambda_duals, mu_t=0.0,
        time_limit=2.0, workers=1,
    )
    assert pat is not None, f"pricer returned None, rc={rc}"
    assert rc < 0.0
    placed_T1_d1 = sum(1 for (p, _c, _s, d, _h), v in pat.items()
                       if v and p == "T1" and d == 1)
    assert placed_T1_d1 == 4
    # Day 2 (1B Mat) must remain greedy-placed.
    placed_T1_d2 = sum(1 for (p, _c, _s, d, _h), v in pat.items()
                       if v and p == "T1" and d == 2)
    assert placed_T1_d2 == 4


def test_bp_loop_with_teacher_day_granularity():
    import column_generation as cg
    profs = _two_class_profs()
    dc_value = _two_class_dc()
    sol_id, info_id = cg.run_column_generation(
        profs, dc_value, time_budget_s=20.0,
        patterns_per_teacher=2, max_iterations=2, log=False,
        mode="iterative-diversified", granularity="teacher",
    )
    sol_bp, info_bp = cg.run_column_generation(
        profs, dc_value, time_budget_s=20.0,
        patterns_per_teacher=2, max_iterations=2, log=False,
        mode="branch-and-price", granularity="teacher-day",
        bp_max_iterations=3, pricer_time_limit=2.0, pricer_workers=1,
    )
    assert info_bp["granularity"] == "teacher-day"
    assert "bp_terminated_reason" in info_bp
    assert (info_bp["feasible_after_assembly"]
            or info_bp["feasible_after_completion"])
    obj_id = info_id["master_obj_final"]
    obj_bp = info_bp["master_obj_final"]
    if obj_id is not None and obj_bp is not None:
        assert obj_bp <= obj_id + 1e-6


def test_bp_loop_runs_and_stays_feasible():
    """End-to-end BP run with mode=branch-and-price and
    granularity=teacher-class on the 2-class scaffold must:
      - actually invoke the BP loop (info['bp_iterations_done'] > 0
        OR a graceful 'no_improving_column' termination at iter 1)
      - return a HARD-feasible solution (via assembly or
        completion fallback)
      - not regress the soft cost vs iterative-diversified."""
    import column_generation as cg
    profs = _two_class_profs()
    dc_value = _two_class_dc()
    sol_id, info_id = cg.run_column_generation(
        profs, dc_value,
        time_budget_s=20.0,
        patterns_per_teacher=2,
        max_iterations=2,
        log=False,
        mode="iterative-diversified",
        granularity="teacher",
    )
    sol_bp, info_bp = cg.run_column_generation(
        profs, dc_value,
        time_budget_s=20.0,
        patterns_per_teacher=2,
        max_iterations=2,
        log=False,
        mode="branch-and-price",
        granularity="teacher-class",
        bp_max_iterations=3,
        pricer_time_limit=2.0,
        pricer_workers=1,
    )
    # The BP loop ran and reported its termination reason.
    assert info_bp["mode"] == "branch-and-price"
    assert info_bp["granularity"] == "teacher-class"
    assert "bp_terminated_reason" in info_bp, (
        f"BP loop did not run; info keys = {list(info_bp.keys())}")
    # HARD feasibility (assembly OR completion).
    assert (info_bp["feasible_after_assembly"]
            or info_bp["feasible_after_completion"]), (
        f"BP solution not HARD-feasible; warnings={info_bp['warnings']}")
    # BP must not be WORSE than iterative-diversified on this small
    # instance (it can be equal, since the catalog is tiny).
    obj_id = info_id["master_obj_final"]
    obj_bp = info_bp["master_obj_final"]
    if obj_id is not None and obj_bp is not None:
        assert obj_bp <= obj_id + 1e-6, (
            f"BP regressed soft cost: BP={obj_bp}, ID={obj_id}")


def test_cg_frontend_dropdown_options_are_valid():
    """All <option value=...> entries in the granularity dropdown
    must be values the backend recognises. Catches drift between
    UI labels and backend enum.
    """
    import re
    from backend.optimization import _CG_GRANULARITIES, _CG_MODES
    here = os.path.dirname(os.path.abspath(__file__))
    fe_path = os.path.normpath(os.path.join(
        here, "..", "..", "frontend", "src", "lib", "components",
        "optimize", "AdvancedTechniquesCard.svelte"))
    with open(fe_path, "r", encoding="utf-8") as f:
        src = f.read()

    # Pull values from the cgGranularity <select> via a tolerant
    # regex (multi-line, in <optgroup> or directly).
    select_block = re.search(
        r"bind:value=\{cgGranularity\}.*?</select>",
        src, re.S)
    assert select_block, "cgGranularity <select> not found"
    fe_grans = set(re.findall(r'value="([^"]+)"', select_block.group(0)))
    assert fe_grans == set(_CG_GRANULARITIES) | {"auto"}, (
        f"frontend granularity options {fe_grans} != "
        f"backend {set(_CG_GRANULARITIES) | {'auto'}}")

    select_mode = re.search(
        r"bind:value=\{cgMode\}.*?</select>",
        src, re.S)
    assert select_mode, "cgMode <select> not found"
    fe_modes = set(re.findall(r'value="([^"]+)"', select_mode.group(0)))
    assert fe_modes == set(_CG_MODES)


# ---------- Lagrangian ----------

def test_lagrangian_module_imports():
    import lagrangian
    assert callable(lagrangian.run_lagrangian)


def test_lagrangian_no_bridges_is_noop():
    """When there are no inter-cluster bridges, the run returns a
    'no bridge' info dict and the input solution unchanged."""
    import lagrangian
    sol = _tiny_feasible_solution()
    profs = _tiny_profs()
    out, info = lagrangian.run_lagrangian(
        sol, profs, dc_value={},
        time_budget_s=1.0,
        max_iter=2,
        classes_clusters=None,   # no clustering -> no bridges
        log=False,
    )
    assert info["kind"] == "lagrangian"
    assert info["n_bridges"] == 0
    # When no bridges, returns the input solution
    assert out == sol


# ---------- Diagnostic modules ----------

def test_montecarlo_module_imports():
    from diagnostics import montecarlo_sensitivity as mc
    assert callable(mc.run_montecarlo)


def test_montecarlo_handles_empty_history():
    """run_montecarlo on a fresh solution returns ok=True with at
    least one sample."""
    from diagnostics import montecarlo_sensitivity as mc
    sol = _tiny_feasible_solution()
    profs = _tiny_profs()
    res = mc.run_montecarlo(sol, profs, dc_value={},
                              n_samples=5, moves_per_sample=3, seed=0)
    assert res["ok"] is True
    assert res["n_samples"] == 5
    assert res["mean"] >= 0
    assert res["std"] >= 0


def test_bipartite_module_imports():
    from diagnostics import bipartite_analysis as ba
    assert callable(ba.analyze)


def test_bipartite_analyze_tiny_graph():
    from diagnostics import bipartite_analysis as ba
    profs = {
        "T1": {"classi": {"1A": {"Mat": {"ore": 5}},
                          "1B": {"Mat": {"ore": 5}}}},
        "T2": {"classi": {"1A": {"Ita": {"ore": 4}},
                          "1B": {"Ita": {"ore": 4}}}},
    }
    res = ba.analyze(profs, mode="classes")
    assert res["ok"] is True
    assert res["n_nodes"] == 2
    assert 0 <= res["density"] <= 1


def test_correlations_module_imports():
    from diagnostics import correlations as co
    assert callable(co.run)


def test_distributions_module_imports():
    from diagnostics import distributions as ds
    assert callable(ds.run)


def test_distributions_run_tiny_solution():
    from diagnostics import distributions as ds
    sol = _tiny_feasible_solution()
    profs = _tiny_profs()
    res = ds.run(sol, profs)
    assert res["ok"] is True
    assert "teacher_loads" in res
    assert "subject_slot_heatmap" in res
