"""Task C1 — potenziamento (Legge 107) constraint in CP-SAT.

Tests that solve_phase_a accepts a list of potenziamento
assignments (class-less rows with is_potenziamento=True) and
distributes their hours across days respecting the per-day cap
on the total prof hours (cattedra + potenziamento).

The MVP only handles Phase A scheduling (per-day distribution).
Phase B / Lesson generation for potenziamento hours is left as
follow-up work.
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


def _profs_simple():
    return {
        "ProfA": {
            "classi": {"3B": {"Mat": {"ore": 4}},
                        "3C": {"Mat": {"ore": 4}}},
            "glibero": [6, 5, 4],
        },
        "ProfB": {
            "classi": {"3B": {"Ita": {"ore": 4}},
                        "3C": {"Ita": {"ore": 4}}},
            "glibero": [6, 5, 4],
        },
        "ProfC": {
            "classi": {"3B": {"Sto": {"ore": 4}},
                        "3C": {"Sto": {"ore": 4}}},
            "glibero": [6, 5, 4],
        },
    }


def _solve_phase_a(profs, potenziamento_assignments=None):
    import cpsat_v2_timetable as cv2  # type: ignore
    classes_v, triples, class_profs = cv2.build_indices(profs)
    return cv2.solve_phase_a(
        profs, classes_v, triples, class_profs,
        time_limit=2, workers=2, log=False,
        potenziamento_assignments=potenziamento_assignments,
    )


def test_potenziamento_distributed_correctly():
    """ProfRossi has 4 hours of potenziamento (no cattedra here).
    Phase A must distribute them so sum_d == 4."""
    profs = _profs_simple()
    profs["ProfRossi"] = {
        "classi": {},  # no cattedra normale
        "glibero": [6, 5, 4],
    }
    pot = [{"teacher_name": "ProfRossi", "subject": "Potenziamento",
            "n_hours": 4}]
    dc = _solve_phase_a(profs, potenziamento_assignments=pot)
    pot_total = sum(v for k, v in dc.items()
                    if isinstance(k, tuple) and len(k) == 3
                    and k[0] == "__pot__" and k[1] == "ProfRossi")
    assert pot_total == 4, (
        f"ProfRossi potenziamento total: expected 4, got {pot_total}")


def test_potenziamento_respects_max_per_day_cap():
    """ProfA has 8 cattedra hours; with 6 potenziamento extra he
    would need 14 hours / 6 days. MAX_PROF_HOURS_PER_DAY=5 caps
    cattedra+pot at 5 per day. The solver must respect that and
    return INFEASIBLE if total would exceed 5*6 = 30."""
    profs = _profs_simple()
    pot = [{"teacher_name": "ProfA", "subject": "Potenziamento",
            "n_hours": 8}]   # 8 cattedra + 8 pot = 16 hours; cap 30 -> ok
    dc = _solve_phase_a(profs, potenziamento_assignments=pot)
    # Per-day check: cattedra + pot <= 5 each day.
    for d in (1, 2, 3, 4, 5, 6):
        cat_d = sum(v for k, v in dc.items()
                    if isinstance(k, tuple) and len(k) == 4
                    and k[0] == "ProfA" and k[3] == d)
        pot_d = dc.get(("__pot__", "ProfA", d), 0)
        assert cat_d + pot_d <= 5, (
            f"day {d}: cattedra {cat_d} + pot {pot_d} > 5")


def test_potenziamento_infeasible_when_exceeding_total_cap():
    """ProfRossi has 31 hours of potenziamento; cap is 30 (5/day *
    6 days). Phase A must surface infeasibility."""
    profs = _profs_simple()
    profs["ProfRossi"] = {"classi": {}, "glibero": [6, 5, 4]}
    pot = [{"teacher_name": "ProfRossi", "subject": "Potenziamento",
            "n_hours": 31}]
    with pytest.raises(RuntimeError):
        _solve_phase_a(profs, potenziamento_assignments=pot)
