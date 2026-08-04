"""F4: the scheduler must not put more concurrent classes into a slot than
there are rooms. ``add_general_room_capacity_phase_b`` caps the distinct
classes in session per (day, hour) at the total room count -- the general
twin of the special-room (gym/lab) cap. These exercise it on a hand-built
CP-SAT model (no solver-heavy Phase B), the same style as
test_special_room_capacity.
"""
from ortools.sat.python import cp_model

import cpsat_v2_timetable as pb


def _solve(build, n_rooms):
    m = cp_model.CpModel()
    slot = {}

    def var(teacher, cl, h):
        v = m.NewBoolVar(f"{teacher}_{cl}_{h}")
        slot[(teacher, cl, "X", 0, h)] = v
        return v

    build(m, var)
    n = pb.add_general_room_capacity_phase_b(m, slot, n_rooms, day=0)
    return cp_model.CpSolver().Solve(m), n


def test_three_classes_one_slot_two_rooms_is_infeasible():
    def build(m, var):
        for cl in ("1A", "1B", "1C"):
            m.Add(var("T", cl, 8) == 1)   # all three want the 8:00 slot
    status, n = _solve(build, n_rooms=2)
    assert n == 1
    assert status == cp_model.INFEASIBLE


def test_three_classes_one_slot_three_rooms_is_feasible():
    def build(m, var):
        for cl in ("1A", "1B", "1C"):
            m.Add(var("T", cl, 8) == 1)
    status, n = _solve(build, n_rooms=3)
    assert n == 0            # within capacity -> no constraint emitted
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_coteach_same_class_is_one_room():
    # Two co-teachers on the SAME class in the same slot occupy ONE room.
    def build(m, var):
        for teacher in ("T1", "T2"):
            m.Add(var(teacher, "1A", 8) == 1)
    # cap 1 room, one class (two teachers) -> must be feasible (not counted 2)
    status, n = _solve(build, n_rooms=1)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_zero_capacity_disables_the_constraint():
    def build(m, var):
        for cl in ("1A", "1B", "1C"):
            m.Add(var("T", cl, 8) == 1)
    status, n = _solve(build, n_rooms=0)
    assert n == 0
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
