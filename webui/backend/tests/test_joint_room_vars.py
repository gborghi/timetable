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


# --- _add_joint_rooms wiring (cell_occ from slot vars) ----------------
from backend.optimization import _add_joint_rooms, _norm_joint_vars  # noqa: E402


def _gym_ctx():
    return {
        "classrooms": [
            {"name": "Palestra", "kind": "palestra",
             "multi_class": True, "multi_class_max": 1, "multi_class_pref": 1},
            {"name": "A1", "kind": "standard"},
            {"name": "A2", "kind": "standard"},
        ],
        "required_kind_by_subj": {"Scienze motorie": "palestra"},
        "home_by_class": {}, "forbidden_by_class": {},
        "shares": lambda t, d, h: False,
    }


def test_add_joint_rooms_couples_schedule_and_rooms():
    """End-to-end wiring: a fake week `slot` where two classes each take PE
    in one of two hours; the single gym must push them into different hours
    through the joint room coupling."""
    m = cp_model.CpModel()
    slot = {}
    for cl in ("1A", "1B"):
        hv = []
        for h in (8, 9):
            v = m.NewBoolVar(f"{cl}_{h}")
            slot[(f"T{cl}", cl, "Scienze motorie", 1, h)] = v
            hv.append(v)
        m.Add(sum(hv) == 1)
    jv = _norm_joint_vars({"enabled": True})
    x, obj_terms, info = _add_joint_rooms(m, slot, _gym_ctx(), jv)
    if obj_terms:
        m.Minimize(sum(obj_terms))
    s = cp_model.CpSolver()
    assert s.Solve(m) in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    def hour_of(cl):
        return 8 if s.Value(slot[(f"T{cl}", cl, "Scienze motorie", 1, 8)]) \
            else 9
    assert hour_of("1A") != hour_of("1B")
    assert info["n_room_vars"] > 0


def test_add_joint_rooms_coteacher_or_indicator():
    """Two co-teachers on the same cell share ONE room (the occupancy OR
    indicator collapses them into a single room request)."""
    m = cp_model.CpModel()
    v = m.NewBoolVar("placed")
    slot = {
        ("Titolare", "1A", "Matematica", 1, 8): v,
        ("Codoc", "1A", "Matematica", 1, 8): v,   # same cell, co-teacher
    }
    m.Add(v == 1)
    jv = _norm_joint_vars({"enabled": True})
    x, obj_terms, info = _add_joint_rooms(m, slot, _gym_ctx(), jv)
    s = cp_model.CpSolver()
    assert s.Solve(m) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    chosen = [rn for (cell, rn), var in x.items() if s.Value(var) == 1]
    assert len(chosen) == 1  # exactly one room for the shared cell


# --- room continuity (Stage 3) ----------------------------------------
def _mk_cell_x(m, cells_rooms):
    """Build joint-style x vars: {(cell,room)->BoolVar} with exactly-one
    room per cell. cells_rooms: {cell -> [room names]}."""
    x = {}
    for cell, rooms in cells_rooms.items():
        vs = []
        for rn in rooms:
            v = m.NewBoolVar(f"x_{cell}_{rn}")
            x[(cell, rn)] = v
            vs.append(v)
        m.Add(sum(vs) == 1)
    return x


def test_continuity_day_forces_same_room():
    """Same room within a day (HARD): cell2 can only use B, so cell1 (which
    could use A or B) is dragged to B too."""
    m = cp_model.CpModel()
    c1 = ("1A", "Matematica", 1, 8)
    c2 = ("1A", "Storia", 1, 9)
    x = _mk_cell_x(m, {c1: ["A", "B"], c2: ["B"]})
    meta = {c1: {"required_kind": ""}, c2: {"required_kind": ""}}
    obj = ca.add_room_continuity_constraints(m, x, meta, {"1A": "day"})
    assert obj == []  # HARD -> no soft terms
    s = cp_model.CpSolver()
    assert s.Solve(m) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert s.Value(x[(c1, "B")]) == 1 and s.Value(x[(c1, "A")]) == 0


def test_continuity_special_kind_is_exempt():
    """A required_kind lesson (gym) is NOT tied to the ordinary room: the
    class can be in room A for Matematica and in the gym for PE."""
    m = cp_model.CpModel()
    c1 = ("1A", "Matematica", 1, 8)
    gym = ("1A", "Scienze motorie", 1, 9)
    x = _mk_cell_x(m, {c1: ["A", "B"], gym: ["Palestra"]})
    meta = {c1: {"required_kind": ""}, gym: {"required_kind": "palestra"}}
    obj = ca.add_room_continuity_constraints(m, x, meta, {"1A": "day"})
    s = cp_model.CpSolver()
    assert s.Solve(m) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert s.Value(x[(gym, "Palestra")]) == 1  # gym unaffected


def test_continuity_soft_minimizes_distinct_rooms():
    """SOFT: minimizing distinct rooms puts both lessons in ONE room when
    a shared room is eligible for both."""
    m = cp_model.CpModel()
    c1 = ("1A", "Matematica", 1, 8)
    c2 = ("1A", "Storia", 1, 9)
    x = _mk_cell_x(m, {c1: ["A", "B"], c2: ["A", "B"]})
    meta = {c1: {"required_kind": ""}, c2: {"required_kind": ""}}
    obj = ca.add_room_continuity_constraints(m, x, meta, {"1A": "soft"},
                                             weight=40)
    assert obj  # soft terms exist
    m.Minimize(sum(obj))
    s = cp_model.CpSolver()
    assert s.Solve(m) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    r1 = "A" if s.Value(x[(c1, "A")]) else "B"
    r2 = "A" if s.Value(x[(c2, "A")]) else "B"
    assert r1 == r2  # one distinct room, not two


def test_parse_room_continuity_pragmas():
    """DSL/preset pragmas -> per-class continuity modes, strictest wins."""
    exprs = [
        "class_same_room_per_day(1A)",
        "class_room_changes_min('2B')",
        "class_same_room_per_week( 3C )",
        # 1A named twice: day (strictest) must win over soft
        "class_room_changes_min(1A)",
    ]
    got = engine_io.parse_room_continuity_pragmas(exprs)
    assert got == {"1A": "day", "2B": "soft", "3C": "week"}


# --- eligible-room pruning (Stage 3.5) --------------------------------
def test_candidate_rooms_prune_ordinary_not_special():
    """candidate_rooms restricts an ORDINARY cell to its class pool; a
    special-kind (gym) cell keeps its required-kind rooms; a disjoint pool
    never prunes to empty."""
    m = cp_model.CpModel()
    rooms = [
        {"name": "A1", "kind": "standard"}, {"name": "A2", "kind": "standard"},
        {"name": "A3", "kind": "standard"},
        {"name": "Palestra", "kind": "palestra"},
    ]
    ordinary = ("1A", "Matematica", 1, 8)
    gym = ("1A", "Scienze motorie", 1, 9)
    disjoint = ("1B", "Storia", 1, 8)
    occ = {ordinary: 1, gym: 1, disjoint: 1}
    meta = {
        ordinary: {"class": "1A", "subject": "Matematica", "day": 1,
                   "hour": 8, "required_kind": ""},
        gym: {"class": "1A", "subject": "Scienze motorie", "day": 1,
              "hour": 9, "required_kind": "palestra"},
        disjoint: {"class": "1B", "subject": "Storia", "day": 1,
                   "hour": 8, "required_kind": ""},
    }
    cand = {"1A": ["A1", "A2"], "1B": ["Zzz"]}  # 1B pool disjoint from rooms
    x, _obj, info = ca.add_joint_room_vars(
        m, occ, meta, rooms, candidate_rooms=cand)
    ord_rooms = {rn for (c, rn) in x if c == ordinary}
    gym_rooms = {rn for (c, rn) in x if c == gym}
    dis_rooms = {rn for (c, rn) in x if c == disjoint}
    assert ord_rooms == {"A1", "A2"}          # pruned to pool
    assert gym_rooms == {"Palestra"}          # special: required-kind kept
    # Disjoint pool -> full eligible. NB _can_host lets an ordinary lesson
    # into any room (incl. the gym); the pruning is exactly what keeps a
    # pooled class out of it -- here 1B has no usable pool so it falls back.
    assert dis_rooms == {"A1", "A2", "A3", "Palestra"}
    assert info["no_room_cells"] == []
