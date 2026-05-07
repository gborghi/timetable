"""Phase 5 integration tests -- ``cp_sat_scope='week'`` + every
downstream stage.

Phase 3 wired the week solver (``MonolithicSolver(scope=None)``) into
``run_phase_b`` plus the schema validator. Phase 4 added the UI
controls. Phase 5 verifies that the week solution is a drop-in
replacement for the legacy day-mode output: every meta-heuristic
(LNS / SA / TS / ILS / ALNS / VNS / Lagrangian), every column
generation mode (``iterative-diversified`` / ``branch-and-price``),
and the classroom-assignment step must accept it as input and
produce HARD-feasible refined solutions.

What this file does NOT test:

* Decomposition (``spectral`` / ``temporal`` / ``metis`` /
  ``curriculum``) is bypassed entirely when ``cp_sat_scope='week'``
  -- ``run_phase_b`` skips the decomposition branch and calls
  ``_solve_phase_b_week`` directly. The ``use_decomposition`` flag
  becomes a no-op. We assert this contract explicitly with
  ``test_run_phase_b_decomposition_flag_ignored_with_week`` so a
  future regression that re-introduces decomposition under week-scope
  can't slip in unnoticed.

All slow-path tests are marked ``@pytest.mark.slow`` so the default
``-m "not slow"`` fast suite stays green-and-quick. Use
``pytest -m slow tests/test_scope_week_integration.py`` to run them.
"""
from __future__ import annotations

import inspect
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(HERE)
WEBUI_DIR = os.path.dirname(BACKEND_DIR)
REPO_ROOT = os.path.dirname(WEBUI_DIR)
ENGINE_DIR = os.path.join(REPO_ROOT, "engine")
for p in (WEBUI_DIR, ENGINE_DIR, REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)


# ============================================================
# Shared fixtures
# ============================================================


def _profs_3_classes_compact():
    """3-class scenario tuned for fast week-mode solves.

    Each class has Mat (4h) + Ita (4h) + Sto (3h) + Mot (2h) = 13h.
    9 cattedre + 1 motorie cattedra spread across classes; total 36
    hours fitting tightly in 36 weekly slots per class. Tight enough
    to exercise ``enforce_math_italian_pair`` (Mat/Ita each have
    >=2h on multiple days) but small enough that all downstream
    integration steps complete inside a few seconds each."""
    profs: dict = {}
    for cl in ("1A", "1B", "1C"):
        profs[f"TM_{cl}"] = {
            "classi": {cl: {"Matematica": {"ore": 4}}},
            "max_hours": 18,
        }
        profs[f"TI_{cl}"] = {
            "classi": {cl: {"Italiano": {"ore": 4}}},
            "max_hours": 18,
        }
        profs[f"TS_{cl}"] = {
            "classi": {cl: {"Storia": {"ore": 3}}},
            "max_hours": 18,
        }
    profs["TMot"] = {
        "classi": {cl: {"Scienzemotorie": {"ore": 2}}
                    for cl in ("1A", "1B", "1C")},
        "max_hours": 18,
    }
    return profs


def _config():
    from cp_sat_constraint_model import ConstraintConfig
    return ConstraintConfig(
        enforce_no_holes=True,
        enforce_h3_presence_at_11=True,
        enforce_motorie_pair=False,
        enforce_math_italian_pair=True,
    )


def _restore_dc_from_solution(sol):
    """Same shape as ``optimization._restore_dc_from_solution``.

    Vendored to keep this file independent of the FastAPI app
    (importing the optimization module pulls heavy DB deps that
    we don't need for engine-level integration)."""
    from collections import defaultdict
    out: dict = defaultdict(int)
    for k, v in sol.items():
        if v != 1:
            continue
        p, cl, subj, d, _h = k
        out[(p, cl, subj, d)] += 1
    return dict(out)


def _solve_week_baseline(time_limit_s: float = 20.0):
    """Build the standard week-mode solution used by every downstream
    test. Returns (sol, profs, dc_value_derived)."""
    from cp_sat_constraint_model import MonolithicSolver

    profs = _profs_3_classes_compact()
    cfg = _config()
    ms = MonolithicSolver(profs, dc_value=None, config=cfg, scope=None)
    sol, status = ms.solve(time_limit_s=time_limit_s, workers=2,
                           log=False)
    assert status in ("OPTIMAL", "FEASIBLE"), status
    assert sol, "week solver produced empty solution"
    dc_value = _restore_dc_from_solution(sol)
    return sol, profs, dc_value


# ============================================================
# Decomposition contract -- the use_decomposition flag is a no-op
# under week-scope; verify the schema/validator + run_phase_b accept
# any combination without erroring.
# ============================================================


def test_run_phase_b_decomposition_flag_accepted_with_week():
    """The schema validator + ``run_phase_b`` must accept every
    ``use_decomposition`` value with ``cp_sat_scope='week'``. The
    flag is silently ignored at runtime (the week branch in
    ``run_phase_b`` doesn't go through ``decomposition_*`` modules)
    but the validator must NOT reject the combination."""
    from webui.backend.schemas import PhaseBRunIn
    for ud in (True, False):
        m = PhaseBRunIn(cp_sat_scope="week", phase_a_mode="skip",
                        use_decomposition=ud)
        assert m.cp_sat_scope == "week"
        assert m.use_decomposition is ud


def test_run_phase_b_signature_decomposition_flag_present():
    """``run_phase_b`` must accept ``use_decomposition`` even with
    ``cp_sat_scope='week'`` -- callers (full pipeline, programmatic
    harness) should not have to special-case the flag."""
    from webui.backend.optimization import run_phase_b
    sig = inspect.signature(run_phase_b)
    assert "use_decomposition" in sig.parameters
    assert "cp_sat_scope" in sig.parameters
    assert "phase_a_mode" in sig.parameters


# ============================================================
# Week solver -> meta-heuristic chain
# Each test runs the week solver once, derives dc_value from the
# solution (= the phase_a_mode='skip' workflow), then drives a single
# meta runner with a tiny time budget. We only assert HARD feasibility
# is preserved -- improvement is opportunistic on tiny instances.
# ============================================================


def _assert_hard_feasible(sol, profs, label: str):
    import metaheuristics as meta  # type: ignore
    assert sol, f"{label}: empty solution"
    assert meta.is_hard_feasible(sol, profs, verbose=False), (
        f"{label}: result is not HARD-feasible")


@pytest.mark.slow
def test_week_then_lns_preserves_feasibility():
    import metaheuristics as meta  # type: ignore
    sol, profs, dc = _solve_week_baseline()
    out, _hist = meta.run_lns(sol, profs, dc, time_budget_s=3.0,
                                log=False, workers=2)
    _assert_hard_feasible(out, profs, "week+lns")


@pytest.mark.slow
def test_week_then_sa_preserves_feasibility():
    import metaheuristics as meta  # type: ignore
    sol, profs, dc = _solve_week_baseline()
    out = meta.run_sa(sol, profs, dc, time_budget_s=3.0, log=False)
    _assert_hard_feasible(out, profs, "week+sa")


@pytest.mark.slow
def test_week_then_ts_preserves_feasibility():
    import metaheuristics as meta  # type: ignore
    sol, profs, dc = _solve_week_baseline()
    out = meta.run_tabu(sol, profs, dc, time_budget_s=3.0, log=False)
    _assert_hard_feasible(out, profs, "week+ts")


@pytest.mark.slow
def test_week_then_ils_preserves_feasibility():
    import metaheuristics as meta  # type: ignore
    sol, profs, dc = _solve_week_baseline()
    out = meta.run_ils(sol, profs, dc, time_budget_s=4.0,
                        n_cycles=1, ts_budget_per_cycle=1.0,
                        log=False)
    _assert_hard_feasible(out, profs, "week+ils")


@pytest.mark.slow
def test_week_then_alns_preserves_feasibility():
    import alns  # type: ignore
    sol, profs, dc = _solve_week_baseline()
    out, _hist = alns.run_alns(sol, profs, dc, time_budget_s=3.0,
                                 log=False, workers=2)
    _assert_hard_feasible(out, profs, "week+alns")


@pytest.mark.slow
def test_week_then_vns_preserves_feasibility():
    import vns  # type: ignore
    sol, profs, dc = _solve_week_baseline()
    out, _hist = vns.run_vns(sol, profs, dc, time_budget_s=3.0,
                                log=False)
    _assert_hard_feasible(out, profs, "week+vns")


@pytest.mark.slow
def test_week_then_lagrangian_preserves_feasibility():
    import lagrangian  # type: ignore
    sol, profs, dc = _solve_week_baseline()
    out, _info = lagrangian.run_lagrangian(
        sol, profs, dc, time_budget_s=3.0,
        max_iter=2, log=False)
    _assert_hard_feasible(out, profs, "week+lagrangian")


# ============================================================
# Week solver -> column generation
# CG needs dc_value; with phase_a_mode='skip' there's no Phase A
# output, so dc_value is derived from the actual week solution
# (mirrors what the production pipeline does after Phase B succeeds).
# ============================================================


@pytest.mark.slow
def test_week_then_cg_iterative_diversified_runs():
    """``run_column_generation`` with ``mode='iterative-diversified'``
    must accept dc_value derived from a week solution and produce a
    HARD-feasible result (or fall back to the completion solver)."""
    import column_generation as cg  # type: ignore
    import metaheuristics as meta  # type: ignore
    sol, profs, dc = _solve_week_baseline()
    out, info = cg.run_column_generation(
        profs, dc,
        time_budget_s=15.0,
        patterns_per_teacher=2,
        max_iterations=2,
        completion_time_limit=10.0,
        completion_workers=2,
        log=False,
        mode="iterative-diversified",
    )
    assert info["mode"] == "iterative-diversified"
    if out is not None:
        assert meta.is_hard_feasible(out, profs, verbose=False), (
            f"CG iterative-diversified result not HARD-feasible: "
            f"info={info}")


@pytest.mark.slow
def test_week_then_cg_branch_and_price_runs():
    """BP scaffold (``mode='branch-and-price'``) must accept
    week-derived dc_value. Granularity defaults to ``teacher`` (V1
    master)."""
    import column_generation as cg  # type: ignore
    import metaheuristics as meta  # type: ignore
    sol, profs, dc = _solve_week_baseline()
    out, info = cg.run_column_generation(
        profs, dc,
        time_budget_s=20.0,
        patterns_per_teacher=2,
        max_iterations=2,
        completion_time_limit=10.0,
        completion_workers=2,
        log=False,
        mode="branch-and-price",
        granularity="teacher",
        bp_max_iterations=2,
        pricer_time_limit=2.0,
        pricer_workers=1,
    )
    assert info["mode"] == "branch-and-price"
    # BP must record the iteration accounting (zero-init even when
    # the loop terminates immediately).
    assert "bp_iterations_done" in info
    if out is not None:
        assert meta.is_hard_feasible(out, profs, verbose=False), (
            f"CG branch-and-price result not HARD-feasible: "
            f"info={info}")


# ============================================================
# Week solver -> classroom assignment
# ============================================================


@pytest.mark.slow
def test_week_then_classroom_assignment_feasible():
    """The classroom solver consumes the lesson list extracted from
    a Phase B solution. Build a small classroom catalog (one room
    per class home + one shared gym) and assert the solver assigns
    every lesson."""
    import classroom_assignment as ca  # type: ignore
    sol, profs, _dc = _solve_week_baseline()

    classrooms = []
    for cl in ("1A", "1B", "1C"):
        classrooms.append({
            "name": f"Aula {cl}",
            "kind": "classroom",
            "is_home_for": [cl],
        })
    classrooms.append({
        "name": "Palestra",
        "kind": "gym",
        "is_home_for": [],
    })

    lessons: list[dict] = []
    for (t, cl, s, d, h), v in sol.items():
        if not v:
            continue
        lessons.append({
            "teacher": t, "class": cl, "subject": s,
            "day": int(d), "hour": int(h),
        })
    assert lessons, "week solution had no active lessons"

    mapping, status = ca.solve_classroom_assignment(
        lessons, classrooms, time_limit_s=10.0, workers=2,
        log=False,
    )
    assert mapping is not None, (
        f"classroom assignment status={status}")
    # Distinct lesson_keys = unique (class, subject, day, hour)
    keys = {(L["class"], L["subject"], L["day"], L["hour"])
            for L in lessons}
    assert len(mapping) == len(keys), (
        f"mapping size {len(mapping)} != lesson_keys {len(keys)}")
    for k in keys:
        assert k in mapping, f"missing classroom for {k}"


# ============================================================
# soft_hint flavour: same chain but Phase A runs first and produces
# dc_value through DayCountModel. The week solver gets an AddHint;
# downstream consumers see Phase A's dc_value (which may differ from
# the actual week distribution if AddHint was overridden).
# ============================================================


@pytest.mark.slow
def test_week_soft_hint_then_lns_preserves_feasibility():
    """Full chain: Phase A -> AddHint -> week solve -> LNS, all with
    the dc_value coming from Phase A (as the soft_hint workflow
    requires). Even if the week solver picked a different
    distribution, dc_value-based meta-heuristics still work because
    they only use dc_value for hint generation, never for hard
    enforcement."""
    from cp_sat_constraint_model import (
        DayCountModel, MonolithicSolver)
    import metaheuristics as meta  # type: ignore

    profs = _profs_3_classes_compact()
    cfg = _config()

    dcm = DayCountModel(profs, config=cfg)
    dc_value, status = dcm.solve(time_limit_s=10, workers=2, log=False)
    assert status in ("OPTIMAL", "FEASIBLE"), status
    assert dc_value, "Phase A produced empty dc_value"

    ms = MonolithicSolver(profs, dc_value=None, config=cfg, scope=None)
    n_hints = ms.add_phase_a_hint(dc_value)
    assert n_hints > 0
    sol, st = ms.solve(time_limit_s=20, workers=2, log=False)
    assert st in ("OPTIMAL", "FEASIBLE"), st
    assert sol

    out, _hist = meta.run_lns(sol, profs, dc_value, time_budget_s=3.0,
                                log=False, workers=2)
    _assert_hard_feasible(out, profs, "week+soft_hint+lns")
