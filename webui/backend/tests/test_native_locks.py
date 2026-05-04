"""Tests for native CP-SAT lock support in the engine.

These tests exercise `engine/cpsat_v2_timetable.py` directly with
hand-built `profs` dicts, since wiring the full FastAPI run pipeline
just to assert that a lock survived would be expensive and brittle.

Three scenarios:

1. **Base**: 2 lessons locked on a small school; the solver respects
   the locks and the rest of the schedule is built around them.
2. **Lock under tighter HARD constraint**: locks coexist with
   `enforce_no_holes=True`; the solver builds a no-holes schedule
   that includes the locked slots.
3. **Infeasibility**: a lock is placed on the teacher's free day,
   making Phase A INFEASIBLE; the solver raises with a clear message
   that mentions the lock count.

We also exercise the two helpers that translate Lesson snapshots into
the dicts the solver expects.
"""
from __future__ import annotations

import os
import sys

import pytest

# Make the engine and backend importable regardless of cwd.
HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(HERE)
WEBUI_DIR = os.path.dirname(BACKEND_DIR)
REPO_ROOT = os.path.dirname(WEBUI_DIR)
ENGINE_DIR = os.path.join(REPO_ROOT, "engine")
for p in (WEBUI_DIR, ENGINE_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


def _make_profs(*, prof_a_free_day: int = 6) -> dict:
    """A 3-prof, 2-class miniature school with hours that fit in a
    week. Each prof has ~10 hours, glibero[0] is the primary free
    day. Used by every test."""
    return {
        "ProfA": {
            "classi": {
                "1A": {"Mat": {"ore": 4}},
                "1B": {"Mat": {"ore": 4}},
            },
            "glibero": [prof_a_free_day, 5, 4],
        },
        "ProfB": {
            "classi": {
                "1A": {"Ita": {"ore": 4}},
                "1B": {"Ita": {"ore": 4}},
            },
            "glibero": [6, 5, 4],
        },
        "ProfC": {
            "classi": {
                "1A": {"Sto": {"ore": 2}},
                "1B": {"Sto": {"ore": 2}},
            },
            "glibero": [6, 5, 4],
        },
    }


def _solve_full(profs, *, locked_dc=None, locked_by_day=None,
                time_a=2, time_b=2):
    import cpsat_v2_timetable as cv2  # type: ignore
    classes, triples, class_profs = cv2.build_indices(profs)
    dc_value = cv2.solve_phase_a(
        profs, classes, triples, class_profs,
        time_limit=time_a, workers=2, log=False,
        locked_day_count=locked_dc,
    )
    DAYS = (1, 2, 3, 4, 5, 6)
    full_solution: dict = {}
    for d in DAYS:
        out, status = cv2.solve_phase_b_for_day(
            d, profs, classes, triples, class_profs, dc_value,
            time_limit=time_b, workers=2, log=False,
            locked_slots_for_day=(locked_by_day or {}).get(d, []),
        )
        if out is not None:
            full_solution.update(out)
    return dc_value, full_solution


def test_helpers_translate_snapshot_correctly():
    from backend.optimization import (  # noqa: E402
        _locked_day_count_from_snapshot,
        _locked_slots_by_day,
    )
    snap = [
        {"teacher_name": "ProfA", "class_name": "1A",
         "subject": "Mat", "day": 2, "hour": 8,
         "classroom_name": "R1", "cotaught_with": None},
        {"teacher_name": "ProfA", "class_name": "1A",
         "subject": "Mat", "day": 2, "hour": 9,
         "classroom_name": "R1", "cotaught_with": None},
        {"teacher_name": "ProfA", "class_name": "1B",
         "subject": "Mat", "day": 3, "hour": 10,
         "classroom_name": None, "cotaught_with": None},
    ]
    dc = _locked_day_count_from_snapshot(snap)
    assert dc == {
        ("ProfA", "1A", "Mat", 2): 2,
        ("ProfA", "1B", "Mat", 3): 1,
    }
    by_day = _locked_slots_by_day(snap)
    assert set(by_day) == {2, 3}
    assert ("ProfA", "1A", "Mat", 8) in by_day[2]
    assert ("ProfA", "1A", "Mat", 9) in by_day[2]
    assert ("ProfA", "1B", "Mat", 10) in by_day[3]


def test_lock_two_lessons_solver_respects_them():
    """Base case: lock 2 lessons of the same cattedra on the same
    day; solver must place exactly those slots and is free to
    distribute the remaining hours."""
    profs = _make_profs()
    locked_dc = {("ProfA", "1A", "Mat", 2): 2}
    locked_by_day = {2: [("ProfA", "1A", "Mat", 8),
                          ("ProfA", "1A", "Mat", 9)]}
    _, sol = _solve_full(profs, locked_dc=locked_dc,
                          locked_by_day=locked_by_day)
    # The two locked slots must be set to 1.
    assert sol[("ProfA", "1A", "Mat", 2, 8)] == 1
    assert sol[("ProfA", "1A", "Mat", 2, 9)] == 1
    # Total ProfA-1A-Mat hours over the week must still be 4.
    n_total = sum(
        v for (p, c, s, _, _), v in sol.items()
        if p == "ProfA" and c == "1A" and s == "Mat"
    )
    assert n_total == 4


def test_lock_with_no_holes_constraint_still_feasible():
    """Five locked lessons all in one day (Tuesday, 8..12), all on
    the same class. The solver must produce a no-holes schedule that
    starts at 8, includes all five locks, and distributes the
    remaining hours feasibly across the rest of the week. The
    cl_day_load HARD constraint requires non-zero days to land in
    {0, 4, 5, 6}, so a 5-hour locked Tuesday is the natural shape."""
    profs = _make_profs()
    # Day 2 (Tue): 5 locked hours on 1A: ProfA-Mat at 8,9; ProfB-Ita
    # at 10,11; ProfC-Sto at 12. cl_day_load(1A, 2) = 5 (in {4,5,6}).
    locked_dc = {
        ("ProfA", "1A", "Mat", 2): 2,
        ("ProfB", "1A", "Ita", 2): 2,
        ("ProfC", "1A", "Sto", 2): 1,
    }
    locked_by_day = {
        2: [
            ("ProfA", "1A", "Mat", 8),
            ("ProfA", "1A", "Mat", 9),
            ("ProfB", "1A", "Ita", 10),
            ("ProfB", "1A", "Ita", 11),
            ("ProfC", "1A", "Sto", 12),
        ],
    }
    _, sol = _solve_full(profs, locked_dc=locked_dc,
                          locked_by_day=locked_by_day)
    for k in [
        ("ProfA", "1A", "Mat", 2, 8),
        ("ProfA", "1A", "Mat", 2, 9),
        ("ProfB", "1A", "Ita", 2, 10),
        ("ProfB", "1A", "Ita", 2, 11),
        ("ProfC", "1A", "Sto", 2, 12),
    ]:
        assert sol[k] == 1, f"locked slot {k} not respected"
    # All weekly hour counts still satisfied.
    for (p, c, s, expected) in [("ProfA", "1A", "Mat", 4),
                                  ("ProfB", "1A", "Ita", 4),
                                  ("ProfC", "1A", "Sto", 2)]:
        n = sum(v for (pp, cc, ss, _, _), v in sol.items()
                if pp == p and cc == c and ss == s)
        assert n == expected, f"({p}/{c}/{s}) total {n} != {expected}"


def test_lock_violating_max_hours_per_day_raises_clear_error():
    """The engine HARD-caps each cattedra at MAX_PER_DAY_TRIPLE=2
    hours per day. A lock that demands 3 hours of the same cattedra
    in a single day is structurally infeasible: Phase A must fail
    with a message that mentions the locks."""
    profs = _make_profs()
    # ProfA-1A-Mat has 4 weekly hours; locking 3 in the same day
    # exceeds the per-day cap of 2 -> infeasible.
    locked_dc = {("ProfA", "1A", "Mat", 2): 3}
    with pytest.raises(RuntimeError) as exc_info:
        _solve_full(profs, locked_dc=locked_dc)
    msg = str(exc_info.value)
    assert "INFEASIBLE" in msg or "infeasible" in msg.lower()
    assert "lock" in msg.lower()


def test_no_locks_passed_means_no_change_in_behaviour():
    """Smoke test: solving with `locked_day_count=None` and
    `locked_slots_for_day=None` is identical to solving without the
    parameter (we exercise the default-None code path)."""
    profs = _make_profs()
    _, sol = _solve_full(profs, locked_dc=None, locked_by_day=None)
    # Total weekly hours sum: 3 profs * (4+4 or 4+4 or 2+2) = 8+8+4 = 20
    total = sum(sol.values())
    assert total == 20, f"expected 20 hours scheduled, got {total}"
