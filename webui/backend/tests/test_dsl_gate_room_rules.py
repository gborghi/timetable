"""Il gate DSL della Fase B non giudica le regole sulle aule: la soluzione
non ha aule, le controlla il passo aule (Liceo M5, Fase B 0% su small)."""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))), "engine")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

import dsl_cp_gate as gate  # noqa: E402


def test_needs_rooms():
    assert gate.needs_rooms('forall l in lessons where l.subject=="Fisica": l.classroom.kind=="lab_fisica"')
    assert not gate.needs_rooms('forall l in lessons where l.teacher=="X": l.hour>=9')


def test_room_rule_is_neither_violated_nor_unverifiable():
    profs = {"F": {"classi": {"1A": {"Fisica": {"ore": 1}}}}}
    sol = {("F", "1A", "Fisica", 1, 8): 1}
    rule = 'forall l in lessons where l.subject=="Fisica": l.classroom.kind=="lab_fisica"'
    assert gate.screen_dsl_hard(sol, profs, [rule], day=1) == ([], [])
