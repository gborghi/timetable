"""Finding 34: Phase B must not schedule more classes into a required-kind
room (gym/lab) in one slot than there are such rooms. These tests exercise
the constraint on a hand-built CP-SAT model (no solver-heavy Phase B run),
the same 'constructed negative control' approach used for the plessi work.
"""
from ortools.sat.python import cp_model

import cpsat_v2_timetable as pb


CTX = ({"Scienze motorie": "palestra"}, {"palestra": 2})  # 2 gyms


def _solve(build):
    m = cp_model.CpModel()
    slot = {}

    def var(teacher, cl, h):
        v = m.NewBoolVar(f"{teacher}_{cl}_{h}")
        slot[(teacher, cl, "Scienze motorie", 0, h)] = v
        return v

    kind_cap = build(m, var)
    n = pb.add_special_room_capacity_phase_b(m, slot, CTX, day=0)
    s = cp_model.CpSolver()
    return s.Solve(m), n


def test_three_classes_one_slot_two_gyms_is_infeasible():
    def build(m, var):
        for cl in ("1A", "1B", "1C"):
            m.Add(var("T", cl, 8) == 1)   # all three want PE at hour 8
    status, n = _solve(build)
    assert n == 1
    assert status == cp_model.INFEASIBLE


def test_two_classes_one_slot_two_gyms_is_feasible():
    def build(m, var):
        for cl in ("1A", "1B"):
            m.Add(var("T", cl, 8) == 1)
    status, n = _solve(build)
    assert n == 0            # within capacity -> no constraint emitted
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_coteach_same_class_is_not_double_counted():
    # One class, two co-teachers in the SAME PE slot occupy ONE gym.
    ctx = ({"Scienze motorie": "palestra"}, {"palestra": 1})  # 1 gym

    def build_and_check(classes):
        m = cp_model.CpModel()
        slot = {}
        for cl in classes:
            for teacher in ("T1", "T2"):   # coteach: two teachers, one cell
                v = m.NewBoolVar(f"{teacher}_{cl}")
                slot[(teacher, cl, "Scienze motorie", 0, 8)] = v
                m.Add(v == 1)
        n = pb.add_special_room_capacity_phase_b(m, slot, ctx, day=0)
        return cp_model.CpSolver().Solve(m), n

    # one class, cap 1: two co-teachers must NOT count as 2 -> feasible
    status1, _ = build_and_check(["1A"])
    assert status1 in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    # two classes, cap 1: genuinely over capacity -> infeasible
    status2, n2 = build_and_check(["1A", "1B"])
    assert n2 == 1 and status2 == cp_model.INFEASIBLE


def test_weekly_capacity_preflight_flags_gross_oversubscription(
        app_with_temp_db):
    """The structural hall-check catches PE hours that no gym schedule
    could ever hold (finding 34, the non-distributional half)."""
    from backend import models
    _app, Session = app_with_temp_db
    with Session() as db:
        # One gym (multi_class_max=1) => weekly capacity 1*6*6 = 36h.
        db.add(models.Classroom(name="Palestra", kind="palestra",
                                multi_class_max=1))
        db.add(models.Subject(name="Scienze motorie", required_kind="palestra"))
        # 20 classes x 2h PE = 40h > 36h capacity.
        for i in range(20):
            c = models.SchoolClass(name=f"{i}X")
            db.add(c)
            db.flush()
            db.add(models.ClassSubject(class_id=c.id,
                                       subject="Scienze motorie",
                                       hours_per_week=2))
        db.commit()
    from diagnostics import hall_check as hc
    with Session() as db:
        res = hc.hall_check_from_db(db, n_samples=8)
    assert res["ok"] is False
    assert any(v["kind"] == "special_room_capacity"
               for v in res["violations"])
