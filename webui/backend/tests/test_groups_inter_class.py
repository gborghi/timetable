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


def test_group_two_groups_distinct_slots():
    """Two distinct groups in the same school, different home classes,
    must be schedulable independently. Each group_slot count matches
    its declared n_hours."""
    profs = _profs_two_classes_24h_each()
    profs["ProfSpa"] = {"classi": {}, "glibero": [6, 5, 4]}
    profs["ProfTed"] = {"classi": {}, "glibero": [6, 5, 4]}
    group_assignments = [
        {"teacher_name": "ProfSpa", "group_id": 1,
         "group_name": "_GruppoSpa_", "subject": "Spagnolo",
         "n_hours": 2, "home_class_names": ["2A"]},
        {"teacher_name": "ProfTed", "group_id": 2,
         "group_name": "_GruppoTed_", "subject": "Tedesco",
         "n_hours": 2, "home_class_names": ["2B"]},
    ]
    dc, sol = _solve(profs, group_assignments=group_assignments)
    spa_n = sum(1 for k, v in sol.items()
                if k[0] == "ProfSpa" and v == 1)
    ted_n = sum(1 for k, v in sol.items()
                if k[0] == "ProfTed" and v == 1)
    assert spa_n == 2, f"Spagnolo: expected 2, got {spa_n}"
    assert ted_n == 2, f"Tedesco: expected 2, got {ted_n}"


def test_group_high_hours_distributed_across_days():
    """5h group must distribute across multiple days (no day exceeds
    MAX_PER_DAY_TRIPLE=2)."""
    profs = _profs_two_classes_24h_each()
    profs["ProfRec"] = {"classi": {}, "glibero": [6, 5, 4]}
    group_assignments = [{
        "teacher_name": "ProfRec",
        "group_id": 5, "group_name": "_GruppoRec_",
        "subject": "Recupero",
        "n_hours": 5, "home_class_names": ["2A"],
    }]
    dc, sol = _solve(profs, group_assignments=group_assignments,
                     time_a=5, time_b=5)
    grp_n = sum(1 for k, v in sol.items()
                if k[0] == "ProfRec" and v == 1)
    assert grp_n == 5, f"expected 5 hours, got {grp_n}"
    # No day with > 2 hours of the group
    by_day: dict[int, int] = {}
    for k, v in sol.items():
        if k[0] == "ProfRec" and v == 1:
            by_day[k[3]] = by_day.get(k[3], 0) + 1
    for d, n in by_day.items():
        assert n <= 2, f"day {d} has {n} group hours (> MAX_PER_DAY_TRIPLE)"


def test_group_with_only_one_home_class_no_2B_busy():
    """When a group's home_class_names is just ['2A'], 2B's
    schedule is NOT affected by the group at all."""
    profs = _profs_two_classes_24h_each()
    profs["ProfRec"] = {"classi": {}, "glibero": [6, 5, 4]}
    group_assignments = [{
        "teacher_name": "ProfRec",
        "group_id": 1, "group_name": "_GruppoRec_",
        "subject": "Recupero", "n_hours": 2,
        "home_class_names": ["2A"],
    }]
    dc, sol = _solve(profs, group_assignments=group_assignments)
    n_2b = sum(1 for k, v in sol.items()
               if k[1] == "2B" and v == 1)
    # 2B's curriculum is 13h -> exactly 13 occupied slots
    assert n_2b == 13, f"2B should have 13 lesson slots, got {n_2b}"


def test_group_zero_hours_skipped():
    """A group_assignment with n_hours=0 produces no group slots
    (the constraint sum_d == 0 forces all day_count to 0)."""
    profs = _profs_two_classes_24h_each()
    profs["ProfX"] = {"classi": {}, "glibero": [6, 5, 4]}
    group_assignments = [{
        "teacher_name": "ProfX",
        "group_id": 9, "group_name": "_GruppoX_",
        "subject": "X", "n_hours": 0,
        "home_class_names": ["2A"],
    }]
    dc, sol = _solve(profs, group_assignments=group_assignments)
    grp_n = sum(1 for k, v in sol.items()
                if k[0] == "ProfX" and v == 1)
    assert grp_n == 0, f"expected 0 group hours, got {grp_n}"


def test_group_hours_stay_within_class_capacity():
    """Group hours plus home_class direct hours must fit within
    6 slots/day. Verified per-day capacity constraint enforces this."""
    profs = _profs_two_classes_24h_each()
    profs["ProfRec"] = {"classi": {}, "glibero": [6, 5, 4]}
    group_assignments = [{
        "teacher_name": "ProfRec",
        "group_id": 1, "group_name": "_GruppoRec_",
        "subject": "Recupero", "n_hours": 2,
        "home_class_names": ["2A"],
    }]
    dc, sol = _solve(profs, group_assignments=group_assignments)
    # For each day, count total slots used by 2A (regular + group)
    by_day_2a: dict[int, set] = {}
    for k, v in sol.items():
        if v != 1:
            continue
        if k[1] == "2A":
            by_day_2a.setdefault(k[3], set()).add(k[4])
        if k[0] == "ProfRec":          # group slot
            by_day_2a.setdefault(k[3], set()).add(k[4])
    for d, slots in by_day_2a.items():
        assert len(slots) <= 6, (
            f"day {d}: 2A has {len(slots)} slots used (> 6)")


def test_group_n_hours_too_many_infeasible():
    """If group n_hours alone exceeds 6 days * MAX_PER_DAY_TRIPLE = 12,
    Phase A is infeasible (too many hours to fit in a week)."""
    profs = _profs_two_classes_24h_each()
    profs["ProfX"] = {"classi": {}, "glibero": [6, 5, 4]}
    group_assignments = [{
        "teacher_name": "ProfX",
        "group_id": 1, "group_name": "_GruppoX_",
        "subject": "X", "n_hours": 13,
        "home_class_names": ["2A"],
    }]
    with pytest.raises(RuntimeError):
        _solve(profs, group_assignments=group_assignments)


def test_group_overload_home_class_infeasible():
    """A group whose home_class is already at full curriculum
    capacity (6h every day) cannot fit -- INFEASIBLE."""
    # 2A at 6h/day for 6 days = 36h; group hours have nowhere to go.
    profs = {
        f"Prof{c}": {"classi": {"2A": {f"S{c}": {"ore": 6}}},
                      "glibero": [6, 5, 4]}
        for c in "ABCDEF"
    }
    profs["ProfX"] = {"classi": {}, "glibero": [6, 5, 4]}
    # 2A is fully booked (36h every day=6) -- adding any group hour
    # exceeds the per-day capacity of 6 slots.
    group_assignments = [{
        "teacher_name": "ProfX",
        "group_id": 1, "group_name": "_GruppoX_",
        "subject": "X", "n_hours": 1,
        "home_class_names": ["2A"],
    }]
    with pytest.raises(RuntimeError):
        _solve(profs, group_assignments=group_assignments)


def test_group_three_home_classes():
    """Group with 3 home_classes: 2A + 2B + 2C. The hour at which
    the group runs sees all three home classes "occupied"."""
    profs = _profs_two_classes_24h_each()
    # Add a 3rd class 2C with same curriculum
    profs["ProfMat"]["classi"]["2C"] = {"Matematica": {"ore": 4}}
    profs["ProfIta"]["classi"]["2C"] = {"Italiano": {"ore": 4}}
    profs["ProfSto"]["classi"]["2C"] = {"Storia": {"ore": 3}}
    profs["ProfMot"]["classi"]["2C"] = {"Scienzemotorie": {"ore": 2}}
    profs["ProfSpa"] = {"classi": {}, "glibero": [6, 5, 4]}
    group_assignments = [{
        "teacher_name": "ProfSpa",
        "group_id": 1, "group_name": "_GruppoSpa_",
        "subject": "Spagnolo", "n_hours": 2,
        "home_class_names": ["2A", "2B", "2C"],
    }]
    dc, sol = _solve(profs, group_assignments=group_assignments,
                     time_a=5, time_b=5)
    grp_dh = {(k[3], k[4]) for k, v in sol.items()
              if k[0] == "ProfSpa" and v == 1}
    assert len(grp_dh) == 2
    for cl in ("2A", "2B", "2C"):
        busy = {(k[3], k[4]) for k, v in sol.items()
                if k[1] == cl and v == 1}
        assert not (grp_dh & busy), (
            f"{cl} has a regular lesson clashing with group at "
            f"{grp_dh & busy}")


def test_group_with_potenziamento_combined():
    """Group + potenziamento for the same teacher works: ProfX has
    2h group + 3h potenziamento. Potenziamento is class-less; group
    has home class 2A. Both are scheduled correctly."""
    profs = _profs_two_classes_24h_each()
    profs["ProfX"] = {"classi": {}, "glibero": [6, 5, 4]}
    group_assignments = [{
        "teacher_name": "ProfX",
        "group_id": 1, "group_name": "_GruppoX_",
        "subject": "Spagnolo", "n_hours": 2,
        "home_class_names": ["2A"],
    }]
    pot_assignments = [{
        "teacher_name": "ProfX",
        "subject": "Potenziamento", "n_hours": 3,
    }]
    dc, sol = _solve(
        profs, group_assignments=group_assignments,
        potenziamento_assignments=pot_assignments,
        time_a=5, time_b=5,
    )
    n_grp = sum(1 for k, v in sol.items()
                if k[0] == "ProfX" and k[1] == "_GruppoX_" and v == 1)
    assert n_grp == 2, f"expected 2 group slots, got {n_grp}"
    # potenziamento is in dc_value via __pot__ namespacing
    pot_total = sum(v for k, v in dc.items()
                    if isinstance(k, tuple) and len(k) == 3
                    and k[0] == "__pot__" and k[1] == "ProfX")
    assert pot_total == 3, f"expected 3 pot hours, got {pot_total}"
