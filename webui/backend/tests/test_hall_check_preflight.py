"""Preflight: per-teacher per-day arithmetic feasibility (findings 14/18/30).

The aggregate demand/supply Hall check used to answer ``ok`` to a school
that was infeasible for individual teachers (an 18h cattedra on ONE class
cannot fit under the per-day caps once a day is kept free). These tests
pin that the pre-check now catches it *by name*, before any solve.
"""
from backend import models


def _seed_teacher_cattedra(Session, *, hours, min_free_days,
                           subject="Sostegno"):
    # The lightweight migrations already seed the 6 default working days
    # (lun-sab), so the preflight sees working_days=6 here.
    with Session() as db:
        cl = models.SchoolClass(name="1C")
        db.add(cl)
        t = models.Teacher(name="Palumbo Camilla", min_free_days=min_free_days)
        db.add(t)
        db.flush()
        db.add(models.Assignment(
            teacher_id=t.id, class_id=cl.id, subject=subject, hours=hours,
        ))
        db.commit()


def test_18h_single_class_with_free_day_is_flagged(app_with_temp_db):
    _app, Session = app_with_temp_db
    _seed_teacher_cattedra(Session, hours=18, min_free_days=1)
    from diagnostics import hall_check as hc
    with Session() as db:
        res = hc.hall_check_from_db(db, n_samples=8)
    assert res["ok"] is False
    kinds = {v["kind"] for v in res["violations"]}
    assert "per_day_capacity" in kinds
    v = next(v for v in res["violations"] if v["kind"] == "per_day_capacity")
    assert v["teacher"] == "Palumbo Camilla"
    assert v["class"] == "1C"
    assert v["demand"] == 18 and v["supply"] == 15   # 3 * (6 - 1)


def test_18h_single_class_all_six_days_is_feasible(app_with_temp_db):
    """min_free_days=0 (correct modelling of a full-time support teacher)
    makes the same cattedra fit: 3 * 6 = 18. No engine special-case."""
    _app, Session = app_with_temp_db
    _seed_teacher_cattedra(Session, hours=18, min_free_days=0)
    from diagnostics import hall_check as hc
    with Session() as db:
        res = hc.hall_check_from_db(db, n_samples=8)
    kinds = {v["kind"] for v in res["violations"]}
    assert "per_day_capacity" not in kinds
