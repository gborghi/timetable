"""Task C3 - parallel groups inter-class (StudyGroup-driven).

Tests that group_assignments (Assignments with group_id != NULL)
are scheduled correctly:
  - group hours are placed in valid slots (no clash with the group
    teacher's other classes);
  - home classes (the classes containing group members) are marked
    busy in slots where the group meets, so they cannot have a
    regular lesson at the same slot;
  - the n-hours invariant holds (group meets exactly n_hours/week).
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


def _profs_two_classes_24h_each():
    """2A + 2B, 24h each (4*6 = 24, distributable as {0,4,5,6}).
    ProfMat: Mat 4h each in 2A and 2B (8h total).
    ProfIta: Ita 4h each (8h total).
    ProfSto: Sto 3h each (6h total).
    ProfMot: Scienzemotorie 2h each (4h total).
    """
    return {
        "ProfMat": {
            "classi": {
                "2A": {"Matematica": {"ore": 4}},
                "2B": {"Matematica": {"ore": 4}},
            },
            "glibero": [6, 5, 4],
        },
        "ProfIta": {
            "classi": {
                "2A": {"Italiano": {"ore": 4}},
                "2B": {"Italiano": {"ore": 4}},
            },
            "glibero": [6, 5, 4],
        },
        "ProfSto": {
            "classi": {
                "2A": {"Storia": {"ore": 3}},
                "2B": {"Storia": {"ore": 3}},
            },
            "glibero": [6, 5, 4],
        },
        "ProfMot": {
            "classi": {
                "2A": {"Scienzemotorie": {"ore": 2}},
                "2B": {"Scienzemotorie": {"ore": 2}},
            },
            "glibero": [6, 5, 4],
        },
    }


def _solve(profs, *, group_assignments=None,
           coteach_groups=None, support_assignments=None,
           potenziamento_assignments=None,
           time_a=3, time_b=3):
    import cpsat_v2_timetable as cv2  # type: ignore
    classes_v, triples, class_profs = cv2.build_indices(profs)
    dc = cv2.solve_phase_a(
        profs, classes_v, triples, class_profs,
        time_limit=time_a, workers=2, log=False,
        coteach_groups=coteach_groups,
        support_assignments=support_assignments,
        potenziamento_assignments=potenziamento_assignments,
        group_assignments=group_assignments,
    )
    full = {}
    for d in cv2.DAYS:
        out, status = cv2.solve_phase_b_for_day(
            d, profs, classes_v, triples, class_profs, dc,
            time_limit=time_b, workers=2, log=False,
            coteach_groups=coteach_groups,
            support_assignments=support_assignments,
            group_assignments=group_assignments,
        )
        if out:
            full.update(out)
    return dc, full


def test_group_basic_cross_class():
    """Gruppo Spagnolo: 3h/week, members from 2A and 2B.
    The solver schedules 3 group_slots, and 2A/2B are marked busy
    in those slots (they cannot have regular lessons there).
    """
    profs = _profs_two_classes_24h_each()
    # Group teacher: empty classi (group hours come ONLY via
    # group_assignments). glibero needed for the giorno-libero logic.
    profs["ProfSpa"] = {"classi": {}, "glibero": [6, 5, 4]}
    group_assignments = [{
        "teacher_name": "ProfSpa",
        "group_id": 1,
        "group_name": "_GruppoSpa_",
        "subject": "Spagnolo",
        "n_hours": 3,
        "home_class_names": ["2A", "2B"],
    }]
    dc, sol = _solve(profs, group_assignments=group_assignments)
    grp_slots = [k for k, v in sol.items()
                 if k[0] == "ProfSpa" and v == 1]
    assert len(grp_slots) == 3, f"expected 3 group slots, got {len(grp_slots)}"
    # Each group slot must NOT collide with a 2A regular lesson
    grp_dh = {(k[3], k[4]) for k in grp_slots}
    for k, v in sol.items():
        if v != 1:
            continue
        if k[1] == "2A" and (k[3], k[4]) in grp_dh:
            assert False, (
                f"2A regular lesson {k} clashes with group slot at "
                f"({k[3]},{k[4]})")
        if k[1] == "2B" and (k[3], k[4]) in grp_dh:
            assert False, (
                f"2B regular lesson {k} clashes with group slot at "
                f"({k[3]},{k[4]})")


def test_group_teacher_no_overlap():
    """ProfSpa teaches the group AND has a 2h class in 2A.
    The 2h class cannot run in the same slot as the group.
    """
    profs = _profs_two_classes_24h_each()
    profs["ProfSpa"] = {
        "classi": {
            "2A": {"OpzioneSpa": {"ore": 2}},
        },
        "glibero": [6, 5, 4],
    }
    # 2A curriculum: original 13 + 2 OpzioneSpa = 15. Move 2 from
    # OpzioneSpa onto a 2A subject; total stays {0,4,5,6}-feasible.
    profs["ProfSto"]["classi"]["2A"]["Storia"]["ore"] = 1
    group_assignments = [{
        "teacher_name": "ProfSpa",
        "group_id": 1,
        "group_name": "_GruppoSpa_",
        "subject": "Spagnolo",
        "n_hours": 3,
        "home_class_names": ["2A", "2B"],
    }]
    dc, sol = _solve(profs, group_assignments=group_assignments)
    spa_slots = [(k[3], k[4]) for k, v in sol.items()
                 if k[0] == "ProfSpa" and v == 1]
    distinct_dh = {dh for dh in spa_slots}
    assert len(spa_slots) == 5, (
        f"ProfSpa should teach 3 group + 2 class = 5 hours, got "
        f"{len(spa_slots)}")
    assert len(distinct_dh) == 5, (
        f"ProfSpa slots must be distinct (no overlap), got "
        f"{len(distinct_dh)}: {distinct_dh}")


def test_group_n_hours_invariant():
    """The group meets exactly n_hours per week."""
    profs = _profs_two_classes_24h_each()
    profs["ProfTed"] = {"classi": {}, "glibero": [6, 5, 4]}
    group_assignments = [{
        "teacher_name": "ProfTed",
        "group_id": 2,
        "group_name": "_GruppoTed_",
        "subject": "Tedesco",
        "n_hours": 4,
        "home_class_names": ["2A"],
    }]
    dc, sol = _solve(profs, group_assignments=group_assignments)
    n_grp_hours = sum(1 for k, v in sol.items()
                      if k[0] == "ProfTed" and v == 1)
    assert n_grp_hours == 4, (
        f"expected 4 weekly group hours, got {n_grp_hours}")


def test_group_propagates_class_busy_to_home():
    """If gruppo Spagnolo is at 2A+2B and meets at slot (d,h), then
    NO regular lesson can run in 2A or 2B at that slot.

    Verified by checking no 2A/2B (d,h) slot coincides with a
    group slot.
    """
    profs = _profs_two_classes_24h_each()
    profs["ProfSpa"] = {"classi": {}, "glibero": [6, 5, 4]}
    group_assignments = [{
        "teacher_name": "ProfSpa",
        "group_id": 1,
        "group_name": "_GruppoSpa_",
        "subject": "Spagnolo",
        "n_hours": 2,
        "home_class_names": ["2A", "2B"],
    }]
    dc, sol = _solve(profs, group_assignments=group_assignments)
    grp_dh = {(k[3], k[4]) for k, v in sol.items()
              if k[0] == "ProfSpa" and v == 1}
    busy_2a = {(k[3], k[4]) for k, v in sol.items()
               if k[1] == "2A" and v == 1
               and not k[1].startswith("_")}
    busy_2b = {(k[3], k[4]) for k, v in sol.items()
               if k[1] == "2B" and v == 1
               and not k[1].startswith("_")}
    overlap_2a = grp_dh & busy_2a
    overlap_2b = grp_dh & busy_2b
    assert not overlap_2a, (
        f"2A has a regular lesson clashing with group at {overlap_2a}")
    assert not overlap_2b, (
        f"2B has a regular lesson clashing with group at {overlap_2b}")


def test_group_only_one_home_class():
    """Edge case: gruppo with ONE home class only.
    Should still work: group slots and class slots don't collide."""
    profs = _profs_two_classes_24h_each()
    profs["ProfRec"] = {"classi": {}, "glibero": [6, 5, 4]}
    group_assignments = [{
        "teacher_name": "ProfRec",
        "group_id": 3,
        "group_name": "_GruppoRec_",
        "subject": "Recupero",
        "n_hours": 2,
        "home_class_names": ["2A"],
    }]
    dc, sol = _solve(profs, group_assignments=group_assignments)
    grp_dh = {(k[3], k[4]) for k, v in sol.items()
              if k[0] == "ProfRec" and v == 1}
    assert len(grp_dh) == 2
    busy_2a = {(k[3], k[4]) for k, v in sol.items()
               if k[1] == "2A" and v == 1}
    assert not (grp_dh & busy_2a)
    busy_2b = {(k[3], k[4]) for k, v in sol.items()
               if k[1] == "2B" and v == 1}
    # Group not on 2B's home list -> 2B may have a class lesson at a
    # group slot. Don't assert non-overlap.
