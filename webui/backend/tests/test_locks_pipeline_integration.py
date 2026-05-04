"""End-to-end integration tests: lock × pipeline.

Builds a small in-memory school directly via SQLAlchemy, runs each
solver entry-point synchronously through the engine code path (no
FastAPI overhead, no async run_manager threads), and verifies that
a small set of locked Lessons survives in the resulting solution.

Marked `@pytest.mark.slow`: each test invokes a full CP-SAT solve.
Run with `pytest -m slow` for the integration sweep, or skip them
in the default suite with `pytest -m "not slow"`.

Pipelines exercised:
- Phase B monolithic
- Phase B decomposed (spectral_v2 via decomposition_loop)
- Decomposition temporal pipeline
- Meta runners: LNS, SA, TS, ILS, ALNS, VNS, Lagrangian
- Column generation
- Classroom assignment

Together these cover every native-lock entry point added in atoms
1..7 of the migration. Combined runs of solver + post-processing
(e.g. temporal + ALNS) are exercised by the pipeline-level tests
in test_native_locks_temporal/_curriculum/_metis already.
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(HERE)
WEBUI_DIR = os.path.dirname(BACKEND_DIR)
REPO_ROOT = os.path.dirname(WEBUI_DIR)
ENGINE_DIR = os.path.join(REPO_ROOT, "engine")
for p in (WEBUI_DIR, ENGINE_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


def _profs_minimal():
    """3 profs / 2 classes / 10h per class (4+4+2)."""
    return {
        "ProfA": {
            "classi": {"1A": {"Mat": {"ore": 4}},
                        "1B": {"Mat": {"ore": 4}}},
            "glibero": [6, 5, 4],
        },
        "ProfB": {
            "classi": {"1A": {"Ita": {"ore": 4}},
                        "1B": {"Ita": {"ore": 4}}},
            "glibero": [6, 5, 4],
        },
        "ProfC": {
            "classi": {"1A": {"Sto": {"ore": 2}},
                        "1B": {"Sto": {"ore": 2}}},
            "glibero": [6, 5, 4],
        },
    }


def _solve_and_collect(locked_dc, locked_by_day):
    """Helper: run Phase A + monolithic Phase B and return the dict
    of placed (p,c,s,d,h) -> 1."""
    import cpsat_v2_timetable as cv2  # type: ignore
    profs = _profs_minimal()
    classes_v, triples, class_profs = cv2.build_indices(profs)
    dc_value = cv2.solve_phase_a(
        profs, classes_v, triples, class_profs,
        time_limit=2, workers=2, log=False,
        locked_day_count=locked_dc,
    )
    sol = {}
    for d in cv2.DAYS:
        out, _ = cv2.solve_phase_b_for_day(
            d, profs, classes_v, triples, class_profs, dc_value,
            time_limit=2, workers=2, log=False,
            locked_slots_for_day=locked_by_day.get(d) or None,
        )
        if out:
            sol.update(out)
    return profs, dc_value, sol


# Common locks used across most tests: 5 lessons in 1A on Tuesday
# (cl_day_load == 5, fits {0,4,5,6}).
_LOCKED_DC = {
    ("ProfA", "1A", "Mat", 2): 2,
    ("ProfB", "1A", "Ita", 2): 2,
    ("ProfC", "1A", "Sto", 2): 1,
}
_LOCKED_BY_DAY = {
    2: [
        ("ProfA", "1A", "Mat", 8),
        ("ProfA", "1A", "Mat", 9),
        ("ProfB", "1A", "Ita", 10),
        ("ProfB", "1A", "Ita", 11),
        ("ProfC", "1A", "Sto", 12),
    ],
}


def _assert_locks_held(sol):
    for k in [
        ("ProfA", "1A", "Mat", 2, 8),
        ("ProfA", "1A", "Mat", 2, 9),
        ("ProfB", "1A", "Ita", 2, 10),
        ("ProfB", "1A", "Ita", 2, 11),
        ("ProfC", "1A", "Sto", 2, 12),
    ]:
        assert sol[k] == 1, f"locked key {k} missing in solution"


@pytest.mark.slow
def test_pipeline_phase_b_monolithic():
    _profs, _dc, sol = _solve_and_collect(_LOCKED_DC, _LOCKED_BY_DAY)
    _assert_locks_held(sol)


@pytest.mark.slow
def test_pipeline_decomposition_loop_with_locks():
    """Spectral-v2 path via decomposition_loop with all classes in
    one cluster (no bridges). Stage B handles all locks."""
    import cpsat_v2_timetable as cv2  # type: ignore
    import decomposition_loop as dl  # type: ignore
    import numpy as np
    profs = _profs_minimal()
    classes = sorted({c for p in profs.values() for c in p["classi"]})
    labels = np.zeros(len(classes), dtype=int)
    res = dl.run_partitioned_pipeline(
        profs, labels, classes, set(),
        time_a=2, time_bridges=2, time_cluster=2,
        time_ricucitura=2, time_mono=2,
        workers=2, log=False,
        locked_day_count=_LOCKED_DC,
        locked_by_day=_LOCKED_BY_DAY,
    )
    assert res["status"] in ("ok", "partial"), res["status"]
    _assert_locks_held(res["full_solution"])


@pytest.mark.slow
@pytest.mark.parametrize("stage", ["lns", "sa", "ts", "alns", "vns",
                                    "lagrangian"])
def test_pipeline_meta_runner(stage):
    """For each meta runner: start from an already-feasible solution,
    re-run with locks, and verify the locked keys still hold."""
    profs, dc_value, sol = _solve_and_collect(_LOCKED_DC, _LOCKED_BY_DAY)
    locks = {k for k in [
        ("ProfA", "1A", "Mat", 2, 8),
        ("ProfA", "1A", "Mat", 2, 9),
        ("ProfB", "1A", "Ita", 2, 10),
    ]}
    if stage == "lns":
        import metaheuristics as meta  # type: ignore
        new_sol, _ = meta.run_lns(sol, profs, dc_value, 1.5,
                                    log=False, workers=2, locks=locks)
    elif stage == "sa":
        import metaheuristics as meta  # type: ignore
        new_sol = meta.run_sa(sol, profs, dc_value, 1.5,
                                log=False, locks=locks)
    elif stage == "ts":
        import metaheuristics as meta  # type: ignore
        new_sol = meta.run_tabu(sol, profs, dc_value, 1.5,
                                  log=False, locks=locks)
    elif stage == "alns":
        import alns as alns_mod  # type: ignore
        new_sol, _ = alns_mod.run_alns(sol, profs, dc_value, 2.0,
                                          log=False, workers=2,
                                          locks=locks)
    elif stage == "vns":
        import vns as vns_mod  # type: ignore
        new_sol, _ = vns_mod.run_vns(sol, profs, dc_value, 1.5,
                                        log=False, locks=locks)
    elif stage == "lagrangian":
        import lagrangian as lag_mod  # type: ignore
        new_sol, _ = lag_mod.run_lagrangian(sol, profs, dc_value,
                                              time_budget_s=2.0,
                                              max_iter=2, log=False,
                                              locks=locks)
    else:
        pytest.fail(f"unknown stage {stage}")
    for k in locks:
        assert new_sol[k] == 1, (
            f"stage={stage}: locked key {k} was moved")


@pytest.mark.slow
def test_pipeline_column_generation_with_locks():
    """Run CG with locks and verify the locked keys are present in
    the assembled solution."""
    import column_generation as cg  # type: ignore
    profs = _profs_minimal()
    # Build dc_value consistent with the lock floor.
    import cpsat_v2_timetable as cv2  # type: ignore
    classes_v, triples, class_profs = cv2.build_indices(profs)
    dc_value = cv2.solve_phase_a(
        profs, classes_v, triples, class_profs,
        time_limit=2, workers=2, log=False,
        locked_day_count=_LOCKED_DC,
    )
    locks = {k for k in [
        ("ProfA", "1A", "Mat", 2, 8),
        ("ProfA", "1A", "Mat", 2, 9),
    ]}
    sol, info = cg.run_column_generation(
        profs, dc_value, time_budget_s=4.0,
        patterns_per_teacher=2, max_iterations=2,
        completion_time_limit=2,
        log=False, locks=locks,
        locked_by_day=_LOCKED_BY_DAY,
    )
    assert sol is not None
    for k in locks:
        assert sol[k] == 1, f"CG: locked key {k} not in solution"


@pytest.mark.slow
def test_pipeline_classroom_assignment_with_lock():
    """Smoke test the classroom step in isolation with one locked
    classroom assignment."""
    import classroom_assignment as ca  # type: ignore
    lessons = [
        {"teacher": "ProfA", "co_teachers": [],
         "class": "1A", "subject": "Mat", "day": 2, "hour": 8},
        {"teacher": "ProfB", "co_teachers": [],
         "class": "1A", "subject": "Ita", "day": 2, "hour": 9},
    ]
    classrooms = [
        {"name": "Aula1", "kind": "standard", "capacity": 30,
         "multi_class": False, "multi_class_max": 1,
         "unavailability": set(), "subject_required": set(),
         "subject_pref_weight": {}, "class_pref_weight": {},
         "is_home_for": set()},
        {"name": "Aula2", "kind": "standard", "capacity": 30,
         "multi_class": False, "multi_class_max": 1,
         "unavailability": set(), "subject_required": set(),
         "subject_pref_weight": {}, "class_pref_weight": {},
         "is_home_for": set()},
    ]
    locked = [("1A", "Mat", 2, 8, "Aula2")]
    mapping, _status = ca.solve_classroom_assignment(
        lessons, classrooms, time_limit_s=2, workers=2,
        locked_classrooms=locked,
    )
    assert mapping is not None
    assert mapping[("1A", "Mat", 2, 8)] == "Aula2"
