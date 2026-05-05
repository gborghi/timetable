"""Task C3 follow-up #2 -- coteach + sostegno on a StudyGroup.

A `CoteachGroup` with `group_id` (instead of class_id) makes the
two teachers' group hours coincide in the same slot, just like a
class-bound coteach group does for class hours.

A sostegno `Assignment` with `is_support=True` and `group_id` (XOR
class_id) follows the student into the group lessons:
  slot[sost, G, "sostegno", h] <= group_busy[G, h]

These tests stress the solver directly via group_assignments,
coteach_groups, support_assignments dicts (skipping the DB layer).
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
    """4 classes, 4 profs, 13h each. Same as the inter_class fixture."""
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


def _solve(profs, *, group_assignments=None, coteach_groups=None,
           support_assignments=None, time_a=5, time_b=5):
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


def test_coteach_on_group_basic():
    """Two profs co-teach 'Spagnolo' on _GruppoSpa_ for 2 hours.
    Both teachers must be in the same slots."""
    profs = _profs_basic()
    profs["ProfSpa1"] = {"classi": {}, "glibero": [6, 5, 4]}
    profs["ProfSpa2"] = {"classi": {}, "glibero": [6, 5, 4]}
    ga = [
        {"teacher_name": "ProfSpa1", "group_id": 1,
         "group_name": "_GruppoSpa_", "subject": "Spagnolo",
         "n_hours": 2, "home_class_names": ["1A", "1B"]},
        {"teacher_name": "ProfSpa2", "group_id": 1,
         "group_name": "_GruppoSpa_", "subject": "Spagnolo",
         "n_hours": 2, "home_class_names": ["1A", "1B"]},
    ]
    cg = [{
        "group_id": 100, "class_name": "_GruppoSpa_",
        "subject": "Spagnolo", "n_hours": 2,
        "required": True, "weight": 100.0,
        "teachers": ["ProfSpa1", "ProfSpa2"],
    }]
    dc, sol = _solve(profs, group_assignments=ga, coteach_groups=cg)
    spa1_slots = {(k[3], k[4]) for k, v in sol.items()
                  if k[0] == "ProfSpa1" and v == 1}
    spa2_slots = {(k[3], k[4]) for k, v in sol.items()
                  if k[0] == "ProfSpa2" and v == 1}
    assert spa1_slots == spa2_slots, (
        f"coteach on group: slots must coincide; "
        f"spa1={spa1_slots} spa2={spa2_slots}")
    assert len(spa1_slots) == 2


def test_sostegno_on_group_follows_lesson():
    """Sostegno DVA in a group: ProfSost's slots must coincide with
    one of the group's non-support member slots (the prof follows the
    student into the group lessons)."""
    profs = _profs_basic()
    profs["ProfTed"] = {"classi": {}, "glibero": [6, 5, 4]}
    profs["ProfSost"] = {"classi": {}, "glibero": [6, 5, 4]}
    ga = [
        {"teacher_name": "ProfTed", "group_id": 2,
         "group_name": "_GruppoTed_", "subject": "Tedesco",
         "n_hours": 2, "home_class_names": ["2A", "2B"]},
        # Sostegno is also a group_assignment so its day_count vars
        # exist. is_support flag is conveyed via support_assignments.
        {"teacher_name": "ProfSost", "group_id": 2,
         "group_name": "_GruppoTed_", "subject": "sostegno",
         "n_hours": 2, "home_class_names": ["2A", "2B"]},
    ]
    sa = [{
        "teacher_name": "ProfSost", "class_name": "_GruppoTed_",
        "subject": "sostegno", "n_hours": 2,
        "is_group_target": True,
    }]
    dc, sol = _solve(profs, group_assignments=ga,
                     support_assignments=sa)
    ted_slots = {(k[3], k[4]) for k, v in sol.items()
                 if k[0] == "ProfTed" and v == 1}
    sost_slots = {(k[3], k[4]) for k, v in sol.items()
                  if k[0] == "ProfSost" and v == 1}
    assert sost_slots, "sostegno deve essere schedulato"
    # Every sostegno slot must coincide with a group lesson slot
    assert sost_slots <= ted_slots, (
        f"sostegno {sost_slots} must coincide with group lesson "
        f"slots {ted_slots}")


def test_sostegno_on_group_zero_when_no_group_lesson():
    """If the group's hours are 0 (the group has no Tedesco
    member-Assignment), the sostegno can't be placed -- forced to 0
    or n_hours=0 input would short-circuit. Edge case: use a
    standalone sostegno on a group whose only member is itself."""
    profs = _profs_basic()
    profs["ProfSost"] = {"classi": {}, "glibero": [6, 5, 4]}
    # group has only the sostegno triple -- there's no non-support
    # group lesson for the sostegno to follow.
    ga = [{
        "teacher_name": "ProfSost", "group_id": 9,
        "group_name": "_LonelyGr_", "subject": "sostegno",
        "n_hours": 1, "home_class_names": ["1A"],
    }]
    sa = [{
        "teacher_name": "ProfSost", "class_name": "_LonelyGr_",
        "subject": "sostegno", "n_hours": 1,
        "is_group_target": True,
    }]
    # Phase A constraint forces day_count == 0 (no group lessons),
    # but sum_d == 1 -- INFEASIBLE.
    with pytest.raises(RuntimeError):
        _solve(profs, group_assignments=ga, support_assignments=sa)


def test_coteach_on_group_n_hours_invariant():
    """Coteach on group with n_hours=3: the 3 group slots host BOTH
    teachers; total per-prof is exactly 3 (n_hours)."""
    profs = _profs_basic()
    profs["ProfA"] = {"classi": {}, "glibero": [6, 5, 4]}
    profs["ProfB"] = {"classi": {}, "glibero": [6, 5, 4]}
    ga = [
        {"teacher_name": "ProfA", "group_id": 1,
         "group_name": "_G_", "subject": "Lab",
         "n_hours": 3, "home_class_names": ["1A"]},
        {"teacher_name": "ProfB", "group_id": 1,
         "group_name": "_G_", "subject": "Lab",
         "n_hours": 3, "home_class_names": ["1A"]},
    ]
    cg = [{
        "group_id": 100, "class_name": "_G_",
        "subject": "Lab", "n_hours": 3,
        "required": True, "weight": 100.0,
        "teachers": ["ProfA", "ProfB"],
    }]
    dc, sol = _solve(profs, group_assignments=ga,
                     coteach_groups=cg, time_a=8, time_b=8)
    a_n = sum(1 for k, v in sol.items()
              if k[0] == "ProfA" and v == 1)
    b_n = sum(1 for k, v in sol.items()
              if k[0] == "ProfB" and v == 1)
    assert a_n == 3, f"ProfA: expected 3 group hours, got {a_n}"
    assert b_n == 3, f"ProfB: expected 3 group hours, got {b_n}"


def test_mix_group_coteach_sostegno():
    """Combined scenario: gruppo "Recupero" 2A+2B, 2h, with two
    coteachers (ProfX + ProfY) AND a sostegno (ProfS) following
    a student.
    Expected: all 3 profs scheduled in the same 2 slots."""
    profs = _profs_basic()
    profs["ProfX"] = {"classi": {}, "glibero": [6, 5, 4]}
    profs["ProfY"] = {"classi": {}, "glibero": [6, 5, 4]}
    profs["ProfS"] = {"classi": {}, "glibero": [6, 5, 4]}
    ga = [
        {"teacher_name": "ProfX", "group_id": 7,
         "group_name": "_Rec_", "subject": "Recupero",
         "n_hours": 2, "home_class_names": ["2A", "2B"]},
        {"teacher_name": "ProfY", "group_id": 7,
         "group_name": "_Rec_", "subject": "Recupero",
         "n_hours": 2, "home_class_names": ["2A", "2B"]},
        {"teacher_name": "ProfS", "group_id": 7,
         "group_name": "_Rec_", "subject": "sostegno",
         "n_hours": 2, "home_class_names": ["2A", "2B"]},
    ]
    cg = [{
        "group_id": 200, "class_name": "_Rec_",
        "subject": "Recupero", "n_hours": 2,
        "required": True, "weight": 100.0,
        "teachers": ["ProfX", "ProfY"],
    }]
    sa = [{
        "teacher_name": "ProfS", "class_name": "_Rec_",
        "subject": "sostegno", "n_hours": 2,
        "is_group_target": True,
    }]
    dc, sol = _solve(profs, group_assignments=ga,
                     coteach_groups=cg, support_assignments=sa,
                     time_a=8, time_b=8)
    x_slots = {(k[3], k[4]) for k, v in sol.items()
               if k[0] == "ProfX" and v == 1}
    y_slots = {(k[3], k[4]) for k, v in sol.items()
               if k[0] == "ProfY" and v == 1}
    s_slots = {(k[3], k[4]) for k, v in sol.items()
               if k[0] == "ProfS" and v == 1}
    assert x_slots == y_slots, (
        f"coteach: {x_slots} vs {y_slots}")
    assert s_slots <= x_slots, (
        f"sostegno {s_slots} must follow group lesson {x_slots}")
    assert len(x_slots) == 2
    assert len(s_slots) == 2
