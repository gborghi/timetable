"""Audit residual (findings 33/34): the sequential room step must not go
all-or-nothing INFEASIBLE when a single slot is over-subscribed. With the
``allow_unplaced`` fallback (default), the exact CP-SAT solve stays feasible,
places the MAXIMUM number of lessons in real rooms honouring every HARD
constraint, and leaves only the over-subscribed ones unplaced -- dropped
from the mapping and reported via a ``/UNPLACED:<n>`` status suffix.

The fallback covers over-subscription ONLY. A lesson with no eligible room
anywhere is a configuration error, not a scheduling one, and keeps returning
``NO_ELIGIBLE`` -- see test_no_eligible_room_stays_no_eligible_not_unplaced.

These feed dicts straight to the engine (no DB), matching the other
classroom_assignment unit tests.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "engine"))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)


def _one_gym():
    """A single gym, capacity 1 (multi_class off)."""
    return [
        {"name": "Palestra", "kind": "palestra", "capacity": 30,
         "multi_class": False, "multi_class_max": 1},
    ]


def _pe(cls: str, hour: int) -> dict:
    return {"teacher": "T", "co_teachers": [], "class": cls,
            "subject": "Scienze motorie", "day": 1, "hour": hour,
            "required_kind": "palestra"}


def test_oversubscribed_slot_places_max_and_reports_unplaced():
    """Three classes want the one gym at the same slot. The old model went
    INFEASIBLE for the WHOLE week; now one class gets the gym and the other
    two are left unplaced (not crammed in, capacity is still HARD)."""
    from classroom_assignment import solve_classroom_assignment

    lessons = [_pe("1A", 8), _pe("1B", 8), _pe("1C", 8)]
    out, status = solve_classroom_assignment(
        lessons, _one_gym(), time_limit_s=5.0, workers=1)
    assert out is not None, status
    assert status.endswith("/UNPLACED:2"), status
    # Exactly one class is in the gym; the gym is never over-booked.
    placed = [k for k in out if k in {("1A", "Scienze motorie", 1, 8),
                                      ("1B", "Scienze motorie", 1, 8),
                                      ("1C", "Scienze motorie", 1, 8)}]
    assert len(placed) == 1
    assert all(out[k] == "Palestra" for k in placed)


def test_allow_unplaced_false_recovers_all_or_nothing():
    """With the fallback OFF, the same over-subscription is INFEASIBLE and
    the mapping is None -- the pre-fix behaviour, kept for callers that want
    a hard failure to trigger the greedy path."""
    from classroom_assignment import solve_classroom_assignment

    lessons = [_pe("1A", 8), _pe("1B", 8), _pe("1C", 8)]
    out, status = solve_classroom_assignment(
        lessons, _one_gym(), time_limit_s=5.0, workers=1,
        allow_unplaced=False)
    assert out is None
    assert status == "INFEASIBLE"


def test_no_eligible_room_stays_no_eligible_not_unplaced():
    """The escape valve is for OVER-SUBSCRIPTION only. A lesson with no
    eligible room anywhere (here: needs a palestra, the school has none) is
    a structural configuration error -- rescheduling cannot fix it -- so it
    still returns NO_ELIGIBLE rather than being quietly dropped as unplaced.
    Otherwise a school with no gym would get a timetable silently missing
    every PE lesson, with the problem reported as a capacity shortage."""
    from classroom_assignment import solve_classroom_assignment

    # Only ordinary rooms exist; the PE lesson needs a palestra.
    rooms = [
        {"name": "Aula 1", "kind": "standard", "capacity": 30,
         "multi_class": False, "multi_class_max": 1},
    ]
    lessons = [
        {"teacher": "T", "co_teachers": [], "class": "1A",
         "subject": "Mate", "day": 1, "hour": 8},
        _pe("1A", 9),   # needs palestra, none exists
    ]
    out, status = solve_classroom_assignment(
        lessons, rooms, time_limit_s=5.0, workers=1)
    assert out is None
    assert status.startswith("NO_ELIGIBLE"), status
    # ...and the flag does not change that: it is not what the flag is for.
    out2, status2 = solve_classroom_assignment(
        lessons, rooms, time_limit_s=5.0, workers=1, allow_unplaced=False)
    assert out2 is None
    assert status2.startswith("NO_ELIGIBLE"), status2


def test_within_capacity_has_no_unplaced_suffix():
    """Zero-drift: when everything fits, the status is the plain solver name
    with no suffix and every lesson is placed."""
    from classroom_assignment import solve_classroom_assignment

    lessons = [_pe("1A", 8), _pe("1B", 9)]   # different slots, one gym
    out, status = solve_classroom_assignment(
        lessons, _one_gym(), time_limit_s=5.0, workers=1)
    assert out is not None, status
    assert "/UNPLACED:" not in status
    assert out[("1A", "Scienze motorie", 1, 8)] == "Palestra"
    assert out[("1B", "Scienze motorie", 1, 9)] == "Palestra"
