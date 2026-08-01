"""Finding 38: a 'preferibile' (soft) coteach group is NOT silently
dropped -- it is emitted as a weighted SOFT DSL rule that the DSL-engaged
solvers (notably the weekly scope) fold into the objective. The native
per-day path still skips it, which is why run_phase_b advises the weekly
preset for a guaranteed soft coteach.
"""
import dsl_translator as dt

from backend import models


def _seed_soft_coteach(Session, *, required, weight=70.0):
    with Session() as db:
        cls = models.SchoolClass(name="3B", n_students=20)
        ta = models.Teacher(name="ProfA")
        tb = models.Teacher(name="ProfB")
        db.add_all([cls, ta, tb])
        db.flush()
        g = models.CoteachGroup(class_id=cls.id, subject="Chimica",
                                n_hours=2, required=required, weight=weight)
        db.add(g)
        db.flush()
        db.add(models.Assignment(teacher_id=ta.id, class_id=cls.id,
                                 subject="Chimica", hours=4,
                                 coteach_group_id=g.id))
        db.add(models.Assignment(teacher_id=tb.id, class_id=cls.id,
                                 subject="Chimica", hours=4,
                                 coteach_group_id=g.id))
        db.commit()


def test_soft_coteach_is_a_weighted_soft_rule(app_with_temp_db):
    _app, Session = app_with_temp_db
    _seed_soft_coteach(Session, required=False, weight=70.0)
    with Session() as db:
        soft = [r for r in dt.load_all_dsl_constraints(db, include_soft=True)
                if r.get("source") == "coteach_group"]
        assert soft, "soft coteach produced no DSL rule"
        assert all(r["is_hard"] is False for r in soft)
        assert all(int(r["weight"]) == 70 for r in soft)
        # hard-only load drops it (it is a preference, not a HARD rule)
        hard = [r for r in dt.load_all_dsl_constraints(db, include_soft=False)
                if r.get("source") == "coteach_group"]
        assert hard == []


def test_required_coteach_is_hard(app_with_temp_db):
    _app, Session = app_with_temp_db
    _seed_soft_coteach(Session, required=True)
    with Session() as db:
        rules = [r for r in dt.load_all_dsl_constraints(db, include_soft=True)
                 if r.get("source") == "coteach_group"]
        assert rules and all(r["is_hard"] is True for r in rules)
