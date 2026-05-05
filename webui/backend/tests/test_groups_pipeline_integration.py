"""Task C3 — integration tests across decomposed pipelines.

Verifies that group_assignments are honored when the orchestrator
goes through:
  - decomposition_temporal (parallel days, fully C3-aware solver)
  - decomposition_loop / curriculum / metis / spectral (force mono
    per-day path when groups are present)

Tests are SLOW (3-10s each); marked with `pytest.mark.slow` so the
fast suite skips them by default if the marker filter is applied.
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


def _profs_for_pipeline_test():
    """4 classes, 4 profs, ~13h/class. Small enough that ProfMat's
    16h fit within MAX_PROF_HOURS_PER_DAY=5 cap (16/4=4 days), and
    big enough to exercise spectral / metis cluster pipelines."""
    profs: dict = {}
    classes = ["1A", "1B", "2A", "2B"]
    profs["ProfMat"] = {
        "classi": {c: {"Matematica": {"ore": 4}} for c in classes},
        "glibero": [6, 5, 4],
    }
    profs["ProfIta"] = {
        "classi": {c: {"Italiano": {"ore": 4}} for c in classes},
        "glibero": [6, 5, 4],
    }
    profs["ProfSto"] = {
        "classi": {c: {"Storia": {"ore": 3}} for c in classes},
        "glibero": [6, 5, 4],
    }
    profs["ProfMot"] = {
        "classi": {c: {"Scienzemotorie": {"ore": 2}} for c in classes},
        "glibero": [6, 5, 4],
    }
    return profs, classes


def _run_phase_a(profs, group_assignments=None):
    import cpsat_v2_timetable as cv2  # type: ignore
    classes_v, triples, class_profs = cv2.build_indices(profs)
    dc = cv2.solve_phase_a(
        profs, classes_v, triples, class_profs,
        time_limit=10, workers=2, log=False,
        group_assignments=group_assignments,
    )
    return dc, triples


@pytest.mark.slow
def test_groups_through_temporal_pipeline():
    """`run_temporal_pipeline` schedules group hours correctly."""
    profs, classes = _profs_for_pipeline_test()
    profs["ProfSpa"] = {"classi": {}, "glibero": [6, 5, 4]}
    ga = [{"teacher_name": "ProfSpa", "group_id": 1,
            "group_name": "_Spa_", "subject": "Spagnolo",
            "n_hours": 2, "home_class_names": ["1A", "1B"]}]
    import decomposition_temporal as dec_t  # type: ignore
    import pickle
    import tempfile
    with tempfile.NamedTemporaryFile(
            suffix=".pkl", delete=False) as f:
        pickle.dump(profs, f)
        profs_path = f.name
    try:
        result = dec_t.run_temporal_pipeline(
            profs_path,
            parallel=False,           # sequential is faster for tests
            time_a=10, time_day=8,
            day_timeout=120,
            log_progress=False,
            group_assignments=ga,
        )
        sol = result["full_solution"]
        spa_n = sum(1 for k, v in sol.items()
                    if k[0] == "ProfSpa" and v == 1)
        assert spa_n == 2, (
            f"temporal: expected 2 group hours, got {spa_n}; "
            f"failed_days={result['failed_days']}")
    finally:
        os.unlink(profs_path)


@pytest.mark.slow
def test_groups_through_loop_pipeline():
    """`run_partitioned_pipeline` (used by curriculum + metis +
    spectral fallback) schedules group hours correctly via the
    forced monolithic per-day path."""
    profs, classes = _profs_for_pipeline_test()
    profs["ProfSpa"] = {"classi": {}, "glibero": [6, 5, 4]}
    ga = [{"teacher_name": "ProfSpa", "group_id": 1,
            "group_name": "_Spa_", "subject": "Spagnolo",
            "n_hours": 2, "home_class_names": ["2A", "2B"]}]

    import cpsat_v2_timetable as cv2  # type: ignore
    import decomposition_loop as dl   # type: ignore
    import decomposition_spectral_v2 as dec_s  # type: ignore
    classes_v, triples, class_profs = cv2.build_indices(profs)
    dc = cv2.solve_phase_a(
        profs, classes_v, triples, class_profs,
        time_limit=10, workers=2, log=False,
        group_assignments=ga,
    )

    # Build a trivial 2-cluster partition (1A/1B/2A/2B vs the rest)
    # so the partitioned pipeline has actual clusters to cycle through.
    M, classes_for_M, _ = dec_s.build_adjacency(profs)
    import numpy as np
    labels = np.array([0 if c in {"1A", "1B", "2A", "2B"} else 1
                       for c in classes_for_M], dtype=np.int64)
    bridges = dec_s.find_bridges(profs, classes_for_M, labels)
    bridges_set = set(bridges[0].keys()) if isinstance(bridges, tuple) \
        else set(bridges.keys()) if hasattr(bridges, "keys") \
        else set(bridges)

    result = dl.run_partitioned_pipeline(
        profs, labels, classes_for_M, bridges_set,
        time_a=10, time_bridges=8, time_cluster=8,
        time_ricucitura=20, time_mono=20,
        workers=2, log=False,
        dc_value=dc,
        group_assignments=ga,
    )
    sol = result["full_solution"]
    spa_n = sum(1 for k, v in sol.items()
                if k[0] == "ProfSpa" and v == 1)
    assert spa_n == 2, (
        f"loop: expected 2 group hours, got {spa_n}; "
        f"failed_days={result['failed_days']}")


@pytest.mark.slow
def test_groups_through_curriculum_pipeline():
    """End-to-end curriculum pipeline with groups."""
    profs, classes = _profs_for_pipeline_test()
    profs["ProfSpa"] = {"classi": {}, "glibero": [6, 5, 4]}
    ga = [{"teacher_name": "ProfSpa", "group_id": 1,
            "group_name": "_Spa_", "subject": "Spagnolo",
            "n_hours": 2, "home_class_names": ["1A", "2A"]}]
    # Map each class to a curriculum (1/2 = liceo, 3/4 = different)
    cls_to_curr = {"1A": "L", "1B": "L", "2A": "S", "2B": "S"}
    import decomposition_curriculum as dec_c  # type: ignore
    result = dec_c.solve_with_curriculum_decomposition(
        profs, cls_to_curr,
        time_a=10, time_bridges=8, time_per_cluster=8,
        time_ricucitura=20, time_mono=20,
        workers=2, log=False,
        group_assignments=ga,
    )
    sol = result["full_solution"]
    spa_n = sum(1 for k, v in sol.items()
                if k[0] == "ProfSpa" and v == 1)
    assert spa_n == 2, (
        f"curriculum: expected 2 group hours, got {spa_n}; "
        f"failed_days={result['failed_days']}")


@pytest.mark.slow
def test_groups_through_metis_pipeline():
    """End-to-end metis pipeline with groups (uses internal
    fallback if pymetis is not installed)."""
    profs, classes = _profs_for_pipeline_test()
    profs["ProfSpa"] = {"classi": {}, "glibero": [6, 5, 4]}
    ga = [{"teacher_name": "ProfSpa", "group_id": 1,
            "group_name": "_Spa_", "subject": "Spagnolo",
            "n_hours": 2, "home_class_names": ["1A", "1B"]}]
    import decomposition_metis as dec_m  # type: ignore
    result = dec_m.solve_with_metis_decomposition(
        profs, k=2,
        time_a=10, time_bridges=8, time_per_cluster=8,
        time_ricucitura=20, time_mono=20,
        workers=2, log=False,
        group_assignments=ga,
    )
    sol = result["full_solution"]
    spa_n = sum(1 for k, v in sol.items()
                if k[0] == "ProfSpa" and v == 1)
    assert spa_n == 2, (
        f"metis: expected 2 group hours, got {spa_n}; "
        f"failed_days={result['failed_days']}")
