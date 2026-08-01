"""Joint (day, hour, room) CP-SAT primitive: `add_joint_room_vars`.

Unlike the standalone room step (rooms assigned to a FROZEN timetable),
the joint primitive links each room choice to the schedule's occupancy
var, so the solver may MOVE a lesson to another hour to satisfy a
room/capacity rule. These tests exercise it on a hand-built CP-SAT model
(no solver-heavy Phase B run) -- the same 'constructed control' approach
used by the special-room and plessi work.
"""
from ortools.sat.python import cp_model

import classroom_assignment as ca


def _rooms():
    return [
        {"name": "Palestra", "kind": "palestra",
         "multi_class": True, "multi_class_max": 1, "multi_class_pref": 1},
        {"name": "A1", "kind": "standard", "is_home_for": {"1A"}},
        {"name": "A2", "kind": "standard", "is_home_for": {"1B"}},
    ]


def test_eligibility_required_kind_and_home_bonus():
    """A fixed cell with required_kind=palestra must land in the gym;
    a plain cell prefers its home room via the SOFT bonus."""
    m = cp_model.CpModel()
    # Both cells fixed as occupied (occ == 1): pure room choice.
    occ = {
        ("1A", "Scienze motorie", 1, 8): 1,
        ("1A", "Matematica", 1, 9): 1,
    }
    meta = {
        ("1A", "Scienze motorie", 1, 8): {
            "class": "1A", "subject": "Scienze motorie", "day": 1, "hour": 8,
            "required_kind": "palestra", "teacher": "Rossi"},
        ("1A", "Matematica", 1, 9): {
            "class": "1A", "subject": "Matematica", "day": 1, "hour": 9,
            "teacher": "Bianchi"},
    }
    x, obj_terms, info = ca.add_joint_room_vars(m, occ, meta, _rooms())
    m.Minimize(sum(obj_terms))
    s = cp_model.CpSolver()
    assert s.Solve(m) in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    def room_of(cell):
        for (c, rn), v in x.items():
            if c == cell and s.Value(v) == 1:
                return rn
        return None

    assert room_of(("1A", "Scienze motorie", 1, 8)) == "Palestra"
    assert room_of(("1A", "Matematica", 1, 9)) == "A1"  # home bonus
    assert info["no_room_cells"] == []


def test_joint_gym_capacity_forces_different_hours():
    """The JOINT move: two classes both need the (single) gym, each
    schedulable at hour 8 OR 9. Gym capacity=1 per slot must push them
    into DIFFERENT hours -- something the frozen-timetable room step
    could never do."""
    m = cp_model.CpModel()
    occ = {}
    meta = {}
    for cl in ("1A", "1B"):
        hour_vars = []
        for h in (8, 9):
            cell = (cl, "Scienze motorie", 1, h)
            occ[cell] = m.NewBoolVar(f"occ_{cl}_{h}")
            hour_vars.append(occ[cell])
            meta[cell] = {
                "class": cl, "subject": "Scienze motorie",
                "day": 1, "hour": h, "required_kind": "palestra",
                "teacher": f"T{cl}"}
        # scheduler: each class gets exactly one hour of PE this day
        m.Add(sum(hour_vars) == 1)

    x, obj_terms, info = ca.add_joint_room_vars(m, occ, meta, _rooms())
    if obj_terms:
        m.Minimize(sum(obj_terms))
    s = cp_model.CpSolver()
    assert s.Solve(m) in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    def hour_of(cl):
        for h in (8, 9):
            if s.Value(occ[(cl, "Scienze motorie", 1, h)]) == 1:
                return h
        return None

    # Gym holds one class per slot -> the two classes cannot share an hour.
    assert hour_of("1A") != hour_of("1B")


def test_no_eligible_room_forbids_placement():
    """A cell requiring a kind with no matching room can never be
    occupied: the joint model forces its occupancy var to 0."""
    m = cp_model.CpModel()
    # Only standard rooms exist; PE requires a gym.
    rooms = [{"name": "A1", "kind": "standard"}]
    cell = ("1A", "Scienze motorie", 1, 8)
    occ = {cell: m.NewBoolVar("occ")}
    meta = {cell: {"class": "1A", "subject": "Scienze motorie",
                   "day": 1, "hour": 8, "required_kind": "palestra",
                   "teacher": "Rossi"}}
    x, obj_terms, info = ca.add_joint_room_vars(m, occ, meta, rooms)
    s = cp_model.CpSolver()
    assert s.Solve(m) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert s.Value(occ[cell]) == 0
    assert cell in info["no_room_cells"]


# --- joint cell builder (rider exclusion) -----------------------------
from backend import engine_io  # noqa: E402


def _ctx(shares_of):
    """ctx with a `shares(teacher,d,h)` predicate driven by a name set."""
    return {
        "classrooms": [],
        "required_kind_by_subj": {"Scienze motorie": "palestra"},
        "home_by_class": {"1A": "A1"},
        "forbidden_by_class": {"1A": {"Lab"}},
        "shares": lambda t, d, h: t in shares_of,
    }


def test_rider_dropped_when_host_present():
    """A sostegno cell (compresenza teacher) in the same class+slot as an
    ordinary lesson is a rider: it inherits the host room, so it must NOT
    get its own room cell."""
    keys = [
        ("Rossi", "1A", "Matematica", 1, 8),      # host
        ("Ada", "1A", "Sostegno", 1, 8),          # rider (Ada shares)
    ]
    cell_to_keys, cell_lessons = engine_io.joint_cells_from_slot_keys(
        keys, _ctx({"Ada"}))
    assert ("1A", "Matematica", 1, 8) in cell_lessons
    assert ("1A", "Sostegno", 1, 8) not in cell_lessons
    assert ("1A", "Sostegno", 1, 8) not in cell_to_keys


def test_rider_keeps_own_room_without_host():
    """No host in the same class+slot -> the sharing teacher books its own
    room (matches compresenza_resolver's caveat)."""
    keys = [("Ada", "1A", "Sostegno", 1, 8)]
    cell_to_keys, cell_lessons = engine_io.joint_cells_from_slot_keys(
        keys, _ctx({"Ada"}))
    assert ("1A", "Sostegno", 1, 8) in cell_lessons


def test_cell_meta_propagates_kind_home_forbidden():
    keys = [("Rossi", "1A", "Scienze motorie", 1, 8)]
    _, cell_lessons = engine_io.joint_cells_from_slot_keys(keys, _ctx(set()))
    meta = cell_lessons[("1A", "Scienze motorie", 1, 8)]
    assert meta["required_kind"] == "palestra"
    assert meta["home_room"] == "A1"
    assert meta["forbidden_rooms"] == {"Lab"}
    assert meta["teacher"] == "Rossi"
