"""Task C1: engine_io extensions for coteaching, sostegno, potenziamento.

Smoke tests on the temp DB: build a small school with one of each
special-case Assignment shape and verify the helper functions
expose them in the expected schema.
"""
from __future__ import annotations


def _seed_school(SessionLocal):
    from backend import models
    s = SessionLocal()
    try:
        teaA = models.Teacher(name="ProfA")
        teaB = models.Teacher(name="ProfB")
        teaSost = models.Teacher(name="ProfSostegno")
        teaPot = models.Teacher(name="ProfPotenziamento")
        cls3B = models.SchoolClass(name="3B", n_students=20)
        s.add_all([teaA, teaB, teaSost, teaPot, cls3B])
        s.flush()

        # Shared coteaching: ProfA and ProfB on (3B, Chimica), 2 of
        # 4 hours co-taught.
        group = models.CoteachGroup(
            class_id=cls3B.id, subject="Chimica",
            n_hours=2, required=True, weight=100.0,
        )
        s.add(group)
        s.flush()
        a1 = models.Assignment(teacher_id=teaA.id, class_id=cls3B.id,
                                subject="Chimica", hours=4,
                                coteach_group_id=group.id)
        a2 = models.Assignment(teacher_id=teaB.id, class_id=cls3B.id,
                                subject="Chimica", hours=4,
                                coteach_group_id=group.id)

        # Sostegno: ProfSostegno follows 3B for 4 hours.
        a_sost = models.Assignment(
            teacher_id=teaSost.id, class_id=cls3B.id,
            subject="sostegno", hours=4, is_support=True,
        )

        # Potenziamento: ProfPotenziamento has 6h class-less.
        a_pot = models.Assignment(
            teacher_id=teaPot.id, class_id=None,
            subject="Potenziamento", hours=6, is_potenziamento=True,
        )

        s.add_all([a1, a2, a_sost, a_pot])
        s.commit()
    finally:
        s.close()


def test_profs_dict_excludes_potenziamento_and_includes_others(
        app_with_temp_db):
    _, SessionLocal = app_with_temp_db
    _seed_school(SessionLocal)
    s = SessionLocal()
    try:
        from backend import engine_io
        profs = engine_io.profs_dict_from_db(s)
        assert "ProfA" in profs
        assert "ProfB" in profs
        assert "ProfSostegno" in profs
        assert "ProfPotenziamento" not in profs, (
            "potenziamento should be excluded from profs_dict")
        # Both shared coteachers carry the cattedra.
        assert profs["ProfA"]["classi"]["3B"]["Chimica"]["ore"] == 4
        assert profs["ProfB"]["classi"]["3B"]["Chimica"]["ore"] == 4
        # Sostegno is included as a regular triple (the solver
        # adds the shadow constraint separately).
        assert profs["ProfSostegno"]["classi"]["3B"]["sostegno"]["ore"] == 4
    finally:
        s.close()


def test_coteach_groups_for_solver(app_with_temp_db):
    _, SessionLocal = app_with_temp_db
    _seed_school(SessionLocal)
    s = SessionLocal()
    try:
        from backend import engine_io
        groups = engine_io.coteach_groups_for_solver(s)
        assert len(groups) == 1
        g = groups[0]
        assert g["class_name"] == "3B"
        assert g["subject"] == "Chimica"
        assert g["n_hours"] == 2
        assert g["required"] is True
        assert sorted(g["teachers"]) == ["ProfA", "ProfB"]
    finally:
        s.close()


def test_support_assignments_from_db(app_with_temp_db):
    _, SessionLocal = app_with_temp_db
    _seed_school(SessionLocal)
    s = SessionLocal()
    try:
        from backend import engine_io
        sup = engine_io.support_assignments_from_db(s)
        assert len(sup) == 1
        assert sup[0]["teacher_name"] == "ProfSostegno"
        assert sup[0]["class_name"] == "3B"
        assert sup[0]["subject"] == "sostegno"
        assert sup[0]["n_hours"] == 4
    finally:
        s.close()


def test_potenziamento_assignments_from_db(app_with_temp_db):
    _, SessionLocal = app_with_temp_db
    _seed_school(SessionLocal)
    s = SessionLocal()
    try:
        from backend import engine_io
        pot = engine_io.potenziamento_assignments_from_db(s)
        assert len(pot) == 1
        assert pot[0]["teacher_name"] == "ProfPotenziamento"
        assert pot[0]["subject"] == "Potenziamento"
        assert pot[0]["n_hours"] == 6
    finally:
        s.close()
