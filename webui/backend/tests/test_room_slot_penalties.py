"""λ on over-subscribed (day, hour) cells after the room step."""
from __future__ import annotations

from backend.pipeline.rooms import _room_slot_penalties


def test_room_slot_penalties_empty_when_all_placed():
    lessons = [
        {"class": "1A", "subject": "Mat", "day": 1, "hour": 8},
        {"class": "1B", "subject": "Ita", "day": 1, "hour": 8},
    ]
    result = {
        ("1A", "Mat", 1, 8): "Aula1",
        ("1B", "Ita", 1, 8): "Aula2",
    }
    assert _room_slot_penalties(lessons, result) == {}


def test_room_slot_penalties_accumulate_per_unplaced_slot():
    lessons = [
        {"class": "1A", "subject": "Mat", "day": 1, "hour": 8},
        {"class": "1B", "subject": "Ita", "day": 1, "hour": 8},
        {"class": "1C", "subject": "Sto", "day": 2, "hour": 9},
    ]
    result = {("1A", "Mat", 1, 8): "Aula1"}
    out = _room_slot_penalties(lessons, result, weight=80)
    assert out[(1, 8)] == 80
    assert out[(2, 9)] == 80
    assert (1, 9) not in out


def test_room_slot_penalties_none_result_penalises_every_lesson():
    lessons = [
        {"class": "1A", "subject": "Mat", "day": 1, "hour": 8},
        {"class": "1B", "subject": "Ita", "day": 1, "hour": 8},
    ]
    out = _room_slot_penalties(lessons, None, weight=10)
    assert out == {(1, 8): 20}