"""Task C1 — shared coteaching constraint in CP-SAT.

Tests that solve_phase_a + solve_phase_b_for_day, given a HARD
shared coteaching group, place the n_hours of overlap such that
the k member teachers share the same slot.
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


def _profs_with_coteach():
    """A 4-prof, 1-class school. Convention: members[0] of a coteach
    group is the PRINCIPAL (full hours); members[1:] are CO-TEACHERS
    whose cattedra hours are exactly the n_hours of compresenza.

    ProfA (principal): 4h Chimica, all real lessons.
    ProfB (codoc): 2h Chimica, all in compresenza with ProfA.
    ProfC: 4h Italiano (no compresenza).
    ProfD: 4h Storia.

    cl_day_load(3B) sees Chim 4 + Ita 4 + Sto 4 = 12 (codoc 2h NOT
    counted; they're already in the principal's 4). 12 hours =
    6+6 across two days, valid.
    """
    return {
        "ProfA": {
            "classi": {"3B": {"Chimica": {"ore": 4}}},
            "glibero": [6, 5, 4],
        },
        "ProfB": {
            "classi": {"3B": {"Chimica": {"ore": 2}}},
            "glibero": [6, 5, 4],
        },
        "ProfC": {
            "classi": {"3B": {"Italiano": {"ore": 4}}},
            "glibero": [6, 5, 4],
        },
        "ProfD": {
            "classi": {"3B": {"Storia": {"ore": 4}}},
            "glibero": [6, 5, 4],
        },
    }


def _solve(profs, coteach_groups, *, time_a=2, time_b=2):
    import cpsat_v2_timetable as cv2  # type: ignore
    classes_v, triples, class_profs = cv2.build_indices(profs)
    dc = cv2.solve_phase_a(
        profs, classes_v, triples, class_profs,
        time_limit=time_a, workers=2, log=False,
        coteach_groups=coteach_groups,
    )
    full = {}
    for d in cv2.DAYS:
        out, _ = cv2.solve_phase_b_for_day(
            d, profs, classes_v, triples, class_profs, dc,
            time_limit=time_b, workers=2, log=False,
            coteach_groups=coteach_groups,
        )
        if out:
            full.update(out)
    return dc, full


def test_shared_coteach_hard_two_teachers():
    """ProfA (principal, 4h) & ProfB (codoc, 2h) share Chimica for
    2 hours. ProfA places all 4 of his hours; ProfB's 2 hours all
    coincide with 2 of ProfA's slots."""
    profs = _profs_with_coteach()
    coteach_groups = [{
        "group_id": 1, "class_name": "3B", "subject": "Chimica",
        "n_hours": 2, "required": True, "weight": 100.0,
        "teachers": ["ProfA", "ProfB"],   # ProfA = principal
    }]
    dc, sol = _solve(profs, coteach_groups)

    # ProfA has 4 hours of Chimica; ProfB has 2 hours.
    n_a = sum(v for (pp, c, s, _, _), v in sol.items()
              if pp == "ProfA" and c == "3B" and s == "Chimica")
    n_b = sum(v for (pp, c, s, _, _), v in sol.items()
              if pp == "ProfB" and c == "3B" and s == "Chimica")
    assert n_a == 4, f"ProfA: expected 4h Chim, got {n_a}"
    assert n_b == 2, f"ProfB: expected 2h Chim, got {n_b}"

    # All ProfB's slots must coincide with ProfA's.
    co_slots = []
    for d in (1, 2, 3, 4, 5, 6):
        for h in (8, 9, 10, 11, 12, 13):
            a = sol.get(("ProfA", "3B", "Chimica", d, h), 0)
            b = sol.get(("ProfB", "3B", "Chimica", d, h), 0)
            if b == 1:
                assert a == 1, (
                    f"ProfB at ({d},{h}) but ProfA absent: "
                    f"compresenza violated")
                co_slots.append((d, h))
    assert len(co_slots) == 2, (
        f"expected exactly 2 compresenza slots, got "
        f"{len(co_slots)}: {co_slots}")


def test_shared_coteach_three_teachers():
    """Lab/musica with principal + 2 codocs in compresenza for 1h."""
    profs = _profs_with_coteach()
    # Both ProfB and ProfE are codocs with 1h each (in compresenza).
    profs["ProfB"]["classi"]["3B"]["Chimica"]["ore"] = 1
    profs["ProfE"] = {
        "classi": {"3B": {"Chimica": {"ore": 1}}},
        "glibero": [6, 5, 4],
    }
    coteach_groups = [{
        "group_id": 1, "class_name": "3B", "subject": "Chimica",
        "n_hours": 1, "required": True, "weight": 100.0,
        "teachers": ["ProfA", "ProfB", "ProfE"],   # ProfA = principal
    }]
    dc, sol = _solve(profs, coteach_groups)

    # The single overlap slot has all 3 teachers active.
    for d in (1, 2, 3, 4, 5, 6):
        for h in (8, 9, 10, 11, 12, 13):
            a = sol.get(("ProfA", "3B", "Chimica", d, h), 0)
            b = sol.get(("ProfB", "3B", "Chimica", d, h), 0)
            e = sol.get(("ProfE", "3B", "Chimica", d, h), 0)
            if a == 1 and b == 1 and e == 1:
                return  # found the common slot
    pytest.fail("no slot has all 3 coteachers active")


def test_shared_coteach_class_busy_counts_once():
    """The class-busy aggregator must count the simultaneous
    presence of the k coteachers as ONE class occupation. Without
    the OR aggregation, the class-busy constraint
    (sum subj_busy_vars <= 1) would fail because two teachers'
    slots for the same (class, subject) sum to 2 in compresenza
    hours."""
    profs = _profs_with_coteach()
    coteach_groups = [{
        "group_id": 1, "class_name": "3B", "subject": "Chimica",
        "n_hours": 2, "required": True, "weight": 100.0,
        "teachers": ["ProfA", "ProfB"],   # ProfA principal
    }]
    dc, sol = _solve(profs, coteach_groups)
    # 3B has 12 weekly class hours (4+4+4, codoc 2h NOT counted).
    # Distinct class slots: 12 (because compresenza counts as one
    # class occupation even though both ProfA and ProfB have a
    # slot var at 1 for the same (class, subj, day, hour)).
    distinct_slots = {(k[3], k[4]) for k, v in sol.items()
                      if k[1] == "3B" and v == 1}
    assert len(distinct_slots) == 12, (
        f"expected 12 distinct class slots, got "
        f"{len(distinct_slots)}: {distinct_slots}")


def test_shared_coteach_infeasible_disjoint_free_days():
    """ProfA's free_day candidates are {6,5,4}; ProfB's are {1,2,3}.
    No overlap day available for compresenza -> the solver must
    surface infeasibility (Phase A returns nothing usable).

    Note: the engine's free_day is a 3-way choice with one of three
    candidates becoming the actual free day. With 6 days total and
    3 candidates each, ProfA can pick any of 6,5,4 and ProfB any of
    1,2,3 -- they CAN coexist. To force infeasibility we make the
    glibero choices forbid common days entirely AND force the
    coteach into a tight spot. Using `required_free_days_count`
    semantics is out of scope for this unit test; instead we use a
    n_hours that can't be satisfied: n_hours=5 of Chimica with each
    teacher having only 4 weekly hours -> Phase A INFEASIBLE."""
    profs = _profs_with_coteach()
    coteach_groups = [{
        "group_id": 1, "class_name": "3B", "subject": "Chimica",
        "n_hours": 5,                # > 4 weekly, infeasible
        "required": True, "weight": 100.0,
        "teachers": ["ProfA", "ProfB"],
    }]
    with pytest.raises(RuntimeError):
        _solve(profs, coteach_groups)
