"""Step 3d: zero-drift between the legacy hardcoded HARD path and
the DSL seed.

``dsl_translator.seed_implicit_hardcoded(profs)`` returns a list of
DSL strings that, when compiled onto a ``MonolithicSolver`` with no
other HARD methods invoked, reproduces the same constraints as the
legacy ``add_*`` methods. We verify this by enumerating feasible
solutions on a tiny scenario for each invariant family and checking
the two paths agree.
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


# ----- helpers -----


def _enumerate_feasible(ms, *, max_solutions=1024):
    """Enumerate every feasible solution (no objective) of `ms.model`."""
    from ortools.sat.python import cp_model
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.enumerate_all_solutions = True

    found: set[tuple[tuple[int, int], ...]] = set()

    class _Collector(cp_model.CpSolverSolutionCallback):
        def __init__(self, slot):
            super().__init__()
            self._slot = slot
            self.n = 0

        def on_solution_callback(self):
            picked = tuple(sorted(
                (k[3], k[4]) for k, v in self._slot.items()
                if self.Value(v) == 1
            ))
            found.add(picked)
            self.n += 1
            if self.n >= max_solutions:
                self.StopSearch()

    cb = _Collector(ms.slot)
    solver.parameters.cp_model_presolve = False
    solver.Solve(ms.model, cb)
    return found


def _build_solver_legacy(profs, dc, *,
                          no_holes=True, h11=True,
                          motorie=True, mat_ita=True):
    """Build a MonolithicSolver invoking only the legacy ``add_*``
    methods (no DSL)."""
    from cp_sat_constraint_model import (
        MonolithicSolver, ConstraintConfig)
    cfg = ConstraintConfig(
        enforce_no_holes=no_holes,
        enforce_h3_presence_at_11=h11,
        enforce_motorie_pair=motorie,
        enforce_math_italian_pair=mat_ita,
    )
    ms = MonolithicSolver(profs, dc, cfg)
    ms.add_teacher_no_overlap()
    ms.add_class_no_overlap()
    if no_holes:
        ms.add_class_no_holes()
        if h11:
            ms.add_h3_presence_at_11()
    if motorie:
        ms.add_motorie_pair()
    if mat_ita:
        ms.add_math_italian_pair()
    return ms


def _build_solver_dsl(profs, dc, *,
                       no_holes=True, h11=True,
                       motorie=True, mat_ita=True,
                       cl_day_load=False,
                       max_per_day_triple=False,
                       max_prof_hours_per_day=False):
    """Build a MonolithicSolver loaded purely from the DSL seed."""
    from cp_sat_constraint_model import (
        MonolithicSolver, ConstraintConfig)
    import dsl_translator as dt
    # Disable every hardcoded path; the seed pragmas re-add only the
    # families requested by flags.
    cfg = ConstraintConfig(
        enforce_no_holes=False,
        enforce_h3_presence_at_11=False,
        enforce_motorie_pair=False,
        enforce_math_italian_pair=False,
    )
    ms = MonolithicSolver(profs, dc, cfg)
    ms.add_teacher_no_overlap()
    ms.add_class_no_overlap()
    seeds = dt.seed_implicit_hardcoded(
        profs,
        enforce_no_holes=no_holes,
        enforce_h3_presence=h11,
        enforce_motorie_pair=motorie,
        enforce_math_italian_pair=mat_ita,
        enforce_class_day_load=cl_day_load,
        enforce_max_per_day_triple=max_per_day_triple,
        enforce_max_prof_hours_per_day=max_prof_hours_per_day,
    )
    ms.add_all_dsl_constraints(seeds)
    # Diagnostics should be empty (or only contain non-HARD info)
    return ms


# ============================================================
# Per-invariant zero-drift
# ============================================================


def test_seed_no_holes_zero_drift():
    """no_holes_class via DSL == add_class_no_holes feasibility set."""
    profs = {"T1": {"classi": {"1A": {"Mat": {"ore": 4}}},
                     "max_hours": 18}}
    dc = {("T1", "1A", "Mat", 1): 4}
    legacy = _build_solver_legacy(profs, dc, no_holes=True, h11=False,
                                    motorie=False, mat_ita=False)
    dsl = _build_solver_dsl(profs, dc, no_holes=True, h11=False,
                              motorie=False, mat_ita=False)
    s_l = _enumerate_feasible(legacy)
    s_d = _enumerate_feasible(dsl)
    assert s_l == s_d, (sorted(s_l), sorted(s_d))


def test_seed_h11_zero_drift():
    profs = {"T1": {"classi": {"1A": {"Mat": {"ore": 1}}},
                     "max_hours": 18}}
    dc = {("T1", "1A", "Mat", 1): 1}
    legacy = _build_solver_legacy(profs, dc, no_holes=True, h11=True,
                                    motorie=False, mat_ita=False)
    dsl = _build_solver_dsl(profs, dc, no_holes=True, h11=True,
                              motorie=False, mat_ita=False)
    s_l = _enumerate_feasible(legacy)
    s_d = _enumerate_feasible(dsl)
    assert s_l == s_d


def test_seed_motorie_pair_zero_drift():
    profs = {"T1": {"classi": {"1A": {
        "Scienzemotorie": {"ore": 2}}}, "max_hours": 18}}
    dc = {("T1", "1A", "Scienzemotorie", 1): 2}
    legacy = _build_solver_legacy(profs, dc, no_holes=False, h11=False,
                                    motorie=True, mat_ita=False)
    dsl = _build_solver_dsl(profs, dc, no_holes=False, h11=False,
                              motorie=True, mat_ita=False)
    s_l = _enumerate_feasible(legacy)
    s_d = _enumerate_feasible(dsl)
    # Both must produce same feasible set
    assert s_l == s_d, (sorted(s_l), sorted(s_d))


def test_seed_math_italian_pair_zero_drift():
    """When >= 2 hours/day of Mat or Italian, at least one
    consecutive pair must exist."""
    profs = {"T1": {"classi": {"1A": {
        "Matematica": {"ore": 2}}}, "max_hours": 18}}
    dc = {("T1", "1A", "Matematica", 1): 2}
    legacy = _build_solver_legacy(profs, dc, no_holes=False, h11=False,
                                    motorie=False, mat_ita=True)
    dsl = _build_solver_dsl(profs, dc, no_holes=False, h11=False,
                              motorie=False, mat_ita=True)
    s_l = _enumerate_feasible(legacy)
    s_d = _enumerate_feasible(dsl)
    assert s_l == s_d


def test_seed_combined_no_holes_h11():
    """Composite: no_holes + h11 both via DSL, vs legacy combined."""
    profs = {"T1": {"classi": {"1A": {"Mat": {"ore": 4}}},
                     "max_hours": 18}}
    dc = {("T1", "1A", "Mat", 1): 4}
    legacy = _build_solver_legacy(profs, dc, no_holes=True, h11=True,
                                    motorie=False, mat_ita=False)
    dsl = _build_solver_dsl(profs, dc, no_holes=True, h11=True,
                              motorie=False, mat_ita=False)
    s_l = _enumerate_feasible(legacy)
    s_d = _enumerate_feasible(dsl)
    assert s_l == s_d


# ============================================================
# Seed structural shape
# ============================================================


def test_seed_emits_expected_families():
    """The seed for a 2-class, 1-teacher profs covers all the
    expected DSL pragma families."""
    import dsl_translator as dt
    profs = {"T1": {"classi": {
        "1A": {"Matematica": {"ore": 4},
               "Italiano": {"ore": 4},
               "Scienzemotorie": {"ore": 2}},
        "2A": {"Matematica": {"ore": 4}}},
        "max_hours": 18}}
    seeds = dt.seed_implicit_hardcoded(profs)
    # cattedra_max_per_day for every triple (4 triples)
    assert sum(1 for s in seeds if "cattedra_max_per_day" in s) == 4
    # teacher_max_per_day for every teacher (1)
    assert sum(1 for s in seeds if "teacher_max_per_day" in s) == 1
    # class_day_load_in for every class (2)
    assert sum(1 for s in seeds
                if "class_day_load_in" in s) == 2
    # no_holes_class for every class (2)
    assert sum(1 for s in seeds if "no_holes_class" in s) == 2
    # class_present_at_hour for every class (2)
    assert sum(1 for s in seeds
                if "class_present_at_hour" in s) == 2
    # subject_pair_must for class with Scienzemotorie (1)
    assert sum(1 for s in seeds
                if "subject_pair_must" in s) == 1
    # subject_pair_exists for Mat + Ita per class with them
    # 1A has both Mat + Ita -> 2; 2A has Mat -> 1; total 3
    assert sum(1 for s in seeds
                if "subject_pair_exists" in s) == 3


def test_seed_disabled_flags_emit_nothing():
    """Disabling all flags returns an empty list."""
    import dsl_translator as dt
    profs = {"T1": {"classi": {"1A": {"Mat": {"ore": 4}}},
                     "max_hours": 18}}
    seeds = dt.seed_implicit_hardcoded(
        profs,
        enforce_no_holes=False,
        enforce_h3_presence=False,
        enforce_motorie_pair=False,
        enforce_math_italian_pair=False,
        enforce_class_day_load=False,
        enforce_max_per_day_triple=False,
        enforce_max_prof_hours_per_day=False,
    )
    assert seeds == []


def test_seed_classes_explicit_filter():
    """When ``classes`` is explicitly passed, only those classes
    appear in class-scoped families."""
    import dsl_translator as dt
    profs = {"T1": {"classi": {
        "1A": {"Mat": {"ore": 1}},
        "2A": {"Mat": {"ore": 1}}}, "max_hours": 18}}
    seeds = dt.seed_implicit_hardcoded(profs, classes=["1A"])
    # No 2A in the no_holes/class_day_load rules
    for s in seeds:
        if "no_holes_class" in s or "class_day_load_in" in s \
                or "class_present_at_hour" in s:
            assert '"1A"' in s
            assert '"2A"' not in s


# ============================================================
# Step 3e: MonolithicSolver.solve(via_dsl=True) zero-drift
# ============================================================


def test_monolithic_solver_via_dsl_zero_drift_no_holes():
    """``solve(via_dsl=True)`` produces the same feasible-pattern
    set as the default ``via_dsl=False`` (which uses the legacy
    ``add_*`` methods directly). This is the Step-3e contract:
    flipping the flag is a pipeline switch, not a behaviour change."""
    from cp_sat_constraint_model import (
        MonolithicSolver, ConstraintConfig)
    profs = {"T1": {"classi": {"1A": {
        "Matematica": {"ore": 4}}}, "max_hours": 18}}
    dc = {("T1", "1A", "Matematica", 1): 4}
    cfg_factory = lambda: ConstraintConfig(  # noqa: E731
        enforce_no_holes=True,
        enforce_h3_presence_at_11=True,
        enforce_motorie_pair=True,
        enforce_math_italian_pair=True,
    )
    legacy = MonolithicSolver(profs, dc, cfg_factory())
    legacy.build(via_dsl=False)
    s_l = _enumerate_feasible(legacy)
    dsl = MonolithicSolver(profs, dc, cfg_factory())
    dsl.build(via_dsl=True)
    s_d = _enumerate_feasible(dsl)
    assert s_l == s_d, (sorted(s_l), sorted(s_d))


def test_monolithic_solver_via_dsl_diagnostics_clean():
    """No diagnostic should fire when the seed is loaded onto a
    well-formed model -- the pragma vocabulary is exhaustive for
    every legacy HARD family."""
    from cp_sat_constraint_model import (
        MonolithicSolver, ConstraintConfig)
    profs = {"T1": {"classi": {"1A": {
        "Matematica": {"ore": 2},
        "Italiano": {"ore": 2},
        "Scienzemotorie": {"ore": 2}}},
        "max_hours": 18}}
    dc = {("T1", "1A", "Matematica", 1): 2,
          ("T1", "1A", "Italiano", 2): 2,
          ("T1", "1A", "Scienzemotorie", 3): 2}
    ms = MonolithicSolver(profs, dc, ConstraintConfig(
        enforce_no_holes=True, enforce_h3_presence_at_11=True,
        enforce_motorie_pair=True, enforce_math_italian_pair=True))
    ms.build(via_dsl=True)
    # No hard diagnostic (every seed pragma resolved cleanly)
    bad = [d for d in getattr(ms, "dsl_diagnostics", [])
           if "could not statically reduce" in d
              or "not yet supported" in d]
    assert bad == [], bad
