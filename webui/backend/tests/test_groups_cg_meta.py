"""Task C3 follow-up #4 -- CG + metaheuristics + Lagrangian
support for group_assignments.

These tests stress the column_generation module and the
metaheuristics atomic-moves to make sure group lessons are
preserved (or correctly re-scheduled) when the algorithms run.
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


def _profs_basic():
    classes = ["1A", "1B", "2A", "2B"]
    return {
        "ProfMat": {
            "classi": {c: {"Matematica": {"ore": 4}} for c in classes},
            "glibero": [6, 5, 4],
        },
        "ProfIta": {
            "classi": {c: {"Italiano": {"ore": 4}} for c in classes},
            "glibero": [6, 5, 4],
        },
        "ProfSto": {
            "classi": {c: {"Storia": {"ore": 3}} for c in classes},
            "glibero": [6, 5, 4],
        },
        "ProfMot": {
            "classi": {c: {"Scienzemotorie": {"ore": 2}} for c in classes},
            "glibero": [6, 5, 4],
        },
    }


def _solve_phase_b(profs, *, group_assignments=None,
                   coteach_groups=None, support_assignments=None,
                   time_a=8, time_b=8):
    """Run Phase A + per-day Phase B and return (dc, full_solution)."""
    import cpsat_v2_timetable as cv2  # type: ignore
    classes_v, triples, class_profs = cv2.build_indices(profs)
    dc = cv2.solve_phase_a(
        profs, classes_v, triples, class_profs,
        time_limit=time_a, workers=2, log=False,
        coteach_groups=coteach_groups,
        support_assignments=support_assignments,
        group_assignments=group_assignments,
    )
    full = {}
    for d in cv2.DAYS:
        out, _ = cv2.solve_phase_b_for_day(
            d, profs, classes_v, triples, class_profs, dc,
            time_limit=time_b, workers=2, log=False,
            coteach_groups=coteach_groups,
            support_assignments=support_assignments,
            group_assignments=group_assignments,
        )
        if out:
            full.update(out)
    return dc, full


@pytest.mark.slow
def test_cg_seed_patterns_includes_group():
    """_seed_patterns must produce at least one pattern for a
    group teacher (whose profs.classi is empty)."""
    import column_generation as cg  # type: ignore
    profs = _profs_basic()
    profs["ProfSpa"] = {"classi": {}, "glibero": [6, 5, 4]}
    ga = [{"teacher_name": "ProfSpa", "group_id": 1,
            "group_name": "_GruppoSpa_", "subject": "Spagnolo",
            "n_hours": 2, "home_class_names": ["1A", "1B"]}]
    dc, _ = _solve_phase_b(profs, group_assignments=ga)
    patterns = cg._seed_patterns(profs, dc, max_per_teacher=2,
                                  group_assignments=ga)
    assert "ProfSpa" in patterns
    assert len(patterns["ProfSpa"]) > 0, (
        "ProfSpa must have at least one pattern"
    )
    # Each pattern should contain the 2 group hours
    for pat in patterns["ProfSpa"]:
        n_grp = sum(1 for k, v in pat.items()
                    if k[0] == "ProfSpa" and v == 1)
        assert n_grp == 2, (
            f"pattern must contain 2 group hours, got {n_grp}: {pat}")


@pytest.mark.slow
def test_cg_completion_solver_preserves_groups():
    """When CG falls back to the completion solver, the resulting
    schedule must still contain the n_hours of group lessons."""
    import column_generation as cg  # type: ignore
    profs = _profs_basic()
    profs["ProfSpa"] = {"classi": {}, "glibero": [6, 5, 4]}
    ga = [{"teacher_name": "ProfSpa", "group_id": 1,
            "group_name": "_GruppoSpa_", "subject": "Spagnolo",
            "n_hours": 2, "home_class_names": ["1A", "1B"]}]
    dc, _ = _solve_phase_b(profs, group_assignments=ga)
    completed = cg._completion_solver(
        {}, profs, dc, time_limit=10, workers=2,
        group_assignments=ga,
    )
    assert completed is not None
    n_grp = sum(1 for k, v in completed.items()
                if k[0] == "ProfSpa" and v == 1)
    assert n_grp == 2


@pytest.mark.slow
def test_lns_preserves_groups():
    """Run LNS for a few seconds on a feasible solution that
    includes group lessons; the resulting solution must still have
    n_hours of group lessons."""
    import metaheuristics as meta  # type: ignore
    profs = _profs_basic()
    profs["ProfSpa"] = {"classi": {}, "glibero": [6, 5, 4]}
    ga = [{"teacher_name": "ProfSpa", "group_id": 1,
            "group_name": "_GruppoSpa_", "subject": "Spagnolo",
            "n_hours": 2, "home_class_names": ["1A", "1B"]}]
    dc, sol = _solve_phase_b(profs, group_assignments=ga,
                              time_a=8, time_b=8)
    n_grp_before = sum(1 for k, v in sol.items()
                        if k[0] == "ProfSpa" and v == 1)
    assert n_grp_before == 2
    new_sol, _ = meta.run_lns(
        sol, profs, dc, time_budget_s=4.0,
        log=False, workers=2, group_assignments=ga,
    )
    n_grp_after = sum(1 for k, v in new_sol.items()
                       if k[0] == "ProfSpa" and v == 1)
    assert n_grp_after == 2, (
        f"LNS lost group hours: before={n_grp_before}, "
        f"after={n_grp_after}")


@pytest.mark.slow
def test_sa_preserves_groups():
    """Same shape as test_lns_preserves_groups but with SA, which
    uses atomic moves + is_hard_feasible (extended for C3)."""
    import metaheuristics as meta  # type: ignore
    profs = _profs_basic()
    profs["ProfSpa"] = {"classi": {}, "glibero": [6, 5, 4]}
    ga = [{"teacher_name": "ProfSpa", "group_id": 1,
            "group_name": "_GruppoSpa_", "subject": "Spagnolo",
            "n_hours": 2, "home_class_names": ["1A", "1B"]}]
    dc, sol = _solve_phase_b(profs, group_assignments=ga)
    new_sol = meta.run_sa(
        sol, profs, dc, time_budget_s=3.0,
        log=False, group_assignments=ga,
    )
    n_grp = sum(1 for k, v in new_sol.items()
                if k[0] == "ProfSpa" and v == 1)
    assert n_grp == 2, (
        f"SA must preserve group hours; got {n_grp}")


@pytest.mark.slow
def test_alns_preserves_groups():
    """ALNS with destroy + CP-SAT repair must keep group lessons."""
    import alns as alns_mod  # type: ignore
    profs = _profs_basic()
    profs["ProfSpa"] = {"classi": {}, "glibero": [6, 5, 4]}
    ga = [{"teacher_name": "ProfSpa", "group_id": 1,
            "group_name": "_GruppoSpa_", "subject": "Spagnolo",
            "n_hours": 2, "home_class_names": ["1A", "1B"]}]
    dc, sol = _solve_phase_b(profs, group_assignments=ga)
    new_sol, _ = alns_mod.run_alns(
        sol, profs, dc, time_budget_s=10.0,
        log=False, workers=2,
        group_assignments=ga,
    )
    n_grp = sum(1 for k, v in new_sol.items()
                if k[0] == "ProfSpa" and v == 1)
    assert n_grp == 2


@pytest.mark.slow
def test_vns_preserves_groups():
    """VNS with k neighbourhoods must keep group lessons."""
    import vns as vns_mod  # type: ignore
    profs = _profs_basic()
    profs["ProfSpa"] = {"classi": {}, "glibero": [6, 5, 4]}
    ga = [{"teacher_name": "ProfSpa", "group_id": 1,
            "group_name": "_GruppoSpa_", "subject": "Spagnolo",
            "n_hours": 2, "home_class_names": ["1A", "1B"]}]
    dc, sol = _solve_phase_b(profs, group_assignments=ga)
    new_sol, _ = vns_mod.run_vns(
        sol, profs, dc, time_budget_s=4.0,
        log=False, group_assignments=ga,
    )
    n_grp = sum(1 for k, v in new_sol.items()
                if k[0] == "ProfSpa" and v == 1)
    assert n_grp == 2


@pytest.mark.slow
def test_lagrangian_preserves_groups():
    """Lagrangian wraps run_sa; the C3 params must propagate."""
    import lagrangian as lag_mod  # type: ignore
    profs = _profs_basic()
    profs["ProfSpa"] = {"classi": {}, "glibero": [6, 5, 4]}
    ga = [{"teacher_name": "ProfSpa", "group_id": 1,
            "group_name": "_GruppoSpa_", "subject": "Spagnolo",
            "n_hours": 2, "home_class_names": ["1A", "1B"]}]
    dc, sol = _solve_phase_b(profs, group_assignments=ga)
    # Lagrangian needs `classes_clusters` to identify bridges; without
    # it the relaxation is trivial and the function returns sol as-is.
    classes_clusters = {0: {"1A", "1B"}, 1: {"2A", "2B"}}
    new_sol, _ = lag_mod.run_lagrangian(
        sol, profs, dc, time_budget_s=8.0,
        classes_clusters=classes_clusters,
        max_iter=2, log=False,
        group_assignments=ga,
    )
    n_grp = sum(1 for k, v in new_sol.items()
                if k[0] == "ProfSpa" and v == 1)
    assert n_grp == 2


@pytest.mark.slow
def test_cg_full_with_group():
    """End-to-end run_column_generation with group_assignments.
    The returned solution must contain the group's n_hours."""
    import column_generation as cg  # type: ignore
    profs = _profs_basic()
    profs["ProfSpa"] = {"classi": {}, "glibero": [6, 5, 4]}
    ga = [{"teacher_name": "ProfSpa", "group_id": 1,
            "group_name": "_GruppoSpa_", "subject": "Spagnolo",
            "n_hours": 2, "home_class_names": ["1A", "1B"]}]
    dc, _ = _solve_phase_b(profs, group_assignments=ga)
    new_sol, info = cg.run_column_generation(
        profs, dc,
        time_budget_s=20.0, patterns_per_teacher=2,
        max_iterations=2,
        completion_time_limit=15.0,
        completion_workers=2,
        log=False,
        group_assignments=ga,
    )
    assert new_sol is not None, f"CG failed: {info}"
    n_grp = sum(1 for k, v in new_sol.items()
                if k[0] == "ProfSpa" and v == 1)
    assert n_grp == 2, (
        f"CG result should have 2 group hours, got {n_grp}; "
        f"info={info}")
