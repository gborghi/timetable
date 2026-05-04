"""Task C2 — parallel groups intra-class.

Tests that two (or more) Assignments sharing a parallel_group_id
on the same class are scheduled in the same slot, count as ONE
class occupation, and respect the n-hours invariant.
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


def _profs_with_parallel():
    """3B: Mat 4 + Ita 4 + Sto 3 + Religione/Alternativa parallel
    (1 hour each). Total weekly hours = 4+4+3+1 = 12 (since the
    parallel hour counts ONCE)."""
    return {
        "ProfA": {"classi": {"3B": {"Mat": {"ore": 4}}},
                   "glibero": [6, 5, 4]},
        "ProfB": {"classi": {"3B": {"Ita": {"ore": 4}}},
                   "glibero": [6, 5, 4]},
        "ProfC": {"classi": {"3B": {"Sto": {"ore": 3}}},
                   "glibero": [6, 5, 4]},
        "ProfRel": {"classi": {"3B": {"Religione": {"ore": 1}}},
                     "glibero": [6, 5, 4]},
        "ProfAlt": {"classi": {"3B": {"Alternativa": {"ore": 1}}},
                     "glibero": [6, 5, 4]},
    }


def _solve(profs, parallel_groups=None, *, time_a=2, time_b=2):
    import cpsat_v2_timetable as cv2  # type: ignore
    classes_v, triples, class_profs = cv2.build_indices(profs)
    dc = cv2.solve_phase_a(
        profs, classes_v, triples, class_profs,
        time_limit=time_a, workers=2, log=False,
        parallel_groups=parallel_groups,
    )
    full = {}
    for d in cv2.DAYS:
        out, _ = cv2.solve_phase_b_for_day(
            d, profs, classes_v, triples, class_profs, dc,
            time_limit=time_b, workers=2, log=False,
            parallel_groups=parallel_groups,
        )
        if out:
            full.update(out)
    return dc, full


def test_parallel_religione_alternativa_share_slot():
    """ProfRel and ProfAlt teach 1 hour each in 3B in parallel.
    Their slots must coincide; the class counts as busy ONCE."""
    profs = _profs_with_parallel()
    pg = [{"group_id": 99, "class_name": "3B",
            "members": [
                {"teacher_name": "ProfRel", "subject": "Religione",
                 "hours": 1},
                {"teacher_name": "ProfAlt", "subject": "Alternativa",
                 "hours": 1},
            ]}]
    dc, sol = _solve(profs, parallel_groups=pg)
    rel_slots = [k for k, v in sol.items()
                 if k[0] == "ProfRel" and v == 1]
    alt_slots = [k for k, v in sol.items()
                 if k[0] == "ProfAlt" and v == 1]
    assert len(rel_slots) == 1, len(rel_slots)
    assert len(alt_slots) == 1, len(alt_slots)
    rel_dh = (rel_slots[0][3], rel_slots[0][4])
    alt_dh = (alt_slots[0][3], alt_slots[0][4])
    assert rel_dh == alt_dh, (
        f"parallel slots must coincide: rel={rel_dh} alt={alt_dh}")


def test_parallel_class_busy_counts_once():
    """3B has 4+4+3+1 = 12 weekly hours (the parallel hour is one
    class slot). Distinct (day, hour) entries in sol for 3B class
    must be 12, not 13."""
    profs = _profs_with_parallel()
    pg = [{"group_id": 99, "class_name": "3B",
            "members": [
                {"teacher_name": "ProfRel", "subject": "Religione",
                 "hours": 1},
                {"teacher_name": "ProfAlt", "subject": "Alternativa",
                 "hours": 1},
            ]}]
    dc, sol = _solve(profs, parallel_groups=pg)
    distinct_slots = {(k[3], k[4]) for k, v in sol.items()
                      if k[1] == "3B" and v == 1}
    assert len(distinct_slots) == 12, (
        f"expected 12 distinct slots, got {len(distinct_slots)}")


def test_parallel_three_assignments():
    """Religione + Alternativa + IRC opzionale (3 paralleli)."""
    profs = _profs_with_parallel()
    profs["ProfIrc"] = {"classi": {"3B": {"IRC": {"ore": 1}}},
                        "glibero": [6, 5, 4]}
    pg = [{"group_id": 99, "class_name": "3B",
            "members": [
                {"teacher_name": "ProfRel", "subject": "Religione",
                 "hours": 1},
                {"teacher_name": "ProfAlt", "subject": "Alternativa",
                 "hours": 1},
                {"teacher_name": "ProfIrc", "subject": "IRC",
                 "hours": 1},
            ]}]
    dc, sol = _solve(profs, parallel_groups=pg)
    rel_slots = {k[3:5] for k, v in sol.items()
                 if k[0] == "ProfRel" and v == 1}
    alt_slots = {k[3:5] for k, v in sol.items()
                 if k[0] == "ProfAlt" and v == 1}
    irc_slots = {k[3:5] for k, v in sol.items()
                 if k[0] == "ProfIrc" and v == 1}
    assert rel_slots == alt_slots == irc_slots, (
        f"3 parallel slots must coincide: rel={rel_slots} "
        f"alt={alt_slots} irc={irc_slots}")


def test_parallel_infeasible_member_hours_mismatch():
    """If two parallel members have different hours, the day_count
    equality constraint can't be satisfied -> Phase A infeasible.

    This is an upstream-data issue: the schema doesn't enforce
    matching hours across parallel members. We expect a clear
    INFEASIBLE message."""
    profs = _profs_with_parallel()
    profs["ProfAlt"]["classi"]["3B"]["Alternativa"]["ore"] = 2
    pg = [{"group_id": 99, "class_name": "3B",
            "members": [
                {"teacher_name": "ProfRel", "subject": "Religione",
                 "hours": 1},
                {"teacher_name": "ProfAlt", "subject": "Alternativa",
                 "hours": 2},
            ]}]
    with pytest.raises(RuntimeError):
        _solve(profs, parallel_groups=pg)
