"""The room step must SAY WHY a lesson has no eligible room, not just return
a bare NO_ELIGIBLE. Capacity is the silent cause -- a room smaller than the
class is HARD-ineligible (`_can_host`), which cost real debugging on the
90-class bespoke. `_no_room_reason` names the most actionable cause, capacity
first.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "engine"))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)


def _rooms(*specs):
    import classroom_assignment as ca  # type: ignore
    return [ca._normalize_classroom(s) for s in specs]


def _lesson(**kw):
    base = {"class": "3B", "subject": "Matematica", "day": 1, "hour": 8}
    base.update(kw)
    return base


def test_reason_is_capacity_when_rooms_too_small():
    import classroom_assignment as ca  # type: ignore
    rooms = _rooms(
        {"name": "A1", "kind": "standard", "capacity": 26},
        {"name": "A2", "kind": "standard", "capacity": 25},
    )
    L = _lesson(n_students=29)
    # No room can host a 29-pupil class in <=26 seats.
    assert all(not ca._can_host(r, L) for r in rooms)
    reason = ca._no_room_reason(rooms, L)
    assert "capienza" in reason
    assert "29" in reason and "26" in reason   # names the class + biggest room


def test_reason_is_missing_kind_when_no_such_room():
    import classroom_assignment as ca  # type: ignore
    rooms = _rooms({"name": "A1", "kind": "standard", "capacity": 30})
    L = _lesson(subject="Scienze motorie", required_kind="palestra",
                n_students=25)
    reason = ca._no_room_reason(rooms, L)
    assert "palestra" in reason


def test_capacity_wins_over_kind_ordering_when_both_would_fail():
    """A gym class that also exceeds gym capacity reports CAPACITY (the
    fixable, silent one) since a matching-kind room exists."""
    import classroom_assignment as ca  # type: ignore
    rooms = _rooms({"name": "Pal", "kind": "palestra", "capacity": 20})
    L = _lesson(subject="Scienze motorie", required_kind="palestra",
                n_students=29)
    reason = ca._no_room_reason(rooms, L)
    assert "capienza" in reason
