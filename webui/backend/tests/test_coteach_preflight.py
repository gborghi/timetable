"""Pre-flight validation for Task C1 schema additions."""
from __future__ import annotations


def _seed_minimum(SessionLocal):
    from backend import models
    s = SessionLocal()
    try:
        teaA = models.Teacher(name="ProfA")
        teaB = models.Teacher(name="ProfB")
        cls = models.SchoolClass(name="3B", n_students=20)
        s.add_all([teaA, teaB, cls])
        s.flush()
        s.commit()
        return teaA.id, teaB.id, cls.id
    finally:
        s.close()


def test_preflight_passes_on_clean_db(app_with_temp_db):
    _, SessionLocal = app_with_temp_db
    s = SessionLocal()
    try:
        from backend.optimization import (
            validate_coteach_sostegno_potenziamento)
        assert validate_coteach_sostegno_potenziamento(s) == []
    finally:
        s.close()


def test_preflight_flags_n_hours_exceeds_principal(app_with_temp_db):
    _, SessionLocal = app_with_temp_db
    aid, bid, clid = _seed_minimum(SessionLocal)
    from backend import models
    s = SessionLocal()
    try:
        # Group requires 5 hours but the principal (max-hours
        # member) has only 4 -> structurally infeasible.
        g = models.CoteachGroup(
            class_id=clid, subject="Chimica",
            n_hours=5, required=True,
        )
        s.add(g)
        s.flush()
        s.add(models.Assignment(
            teacher_id=aid, class_id=clid, subject="Chimica",
            hours=4, coteach_group_id=g.id,
        ))
        s.add(models.Assignment(
            teacher_id=bid, class_id=clid, subject="Chimica",
            hours=2, coteach_group_id=g.id,
        ))
        s.commit()
        from backend.optimization import (
            validate_coteach_sostegno_potenziamento)
        violations = validate_coteach_sostegno_potenziamento(s)
        msg = " ".join(violations)
        # Principal is ProfA (4 hours, > ProfB's 2). n_hours=5 > 4.
        assert "n_hours=5" in msg
        assert "principale" in msg.lower()
    finally:
        s.close()


def test_preflight_flags_codoc_hours_mismatch(app_with_temp_db):
    _, SessionLocal = app_with_temp_db
    aid, bid, clid = _seed_minimum(SessionLocal)
    from backend import models
    s = SessionLocal()
    try:
        g = models.CoteachGroup(
            class_id=clid, subject="Sci", n_hours=2, required=True,
        )
        s.add(g)
        s.flush()
        s.add(models.Assignment(
            teacher_id=aid, class_id=clid, subject="Sci",
            hours=4, coteach_group_id=g.id,
        ))
        # Codoc with 3 hours but group says 2 -> mismatch.
        s.add(models.Assignment(
            teacher_id=bid, class_id=clid, subject="Sci",
            hours=3, coteach_group_id=g.id,
        ))
        s.commit()
        from backend.optimization import (
            validate_coteach_sostegno_potenziamento)
        violations = validate_coteach_sostegno_potenziamento(s)
        msg = " ".join(violations)
        assert "codoc" in msg.lower()
    finally:
        s.close()


def test_preflight_flags_potenziamento_with_class(app_with_temp_db):
    _, SessionLocal = app_with_temp_db
    aid, _, clid = _seed_minimum(SessionLocal)
    from backend import models
    s = SessionLocal()
    try:
        s.add(models.Assignment(
            teacher_id=aid, class_id=clid, subject="Pot",
            hours=4, is_potenziamento=True,    # malformed
        ))
        s.commit()
        from backend.optimization import (
            validate_coteach_sostegno_potenziamento)
        violations = validate_coteach_sostegno_potenziamento(s)
        msg = " ".join(violations)
        assert "potenziamento" in msg.lower()
    finally:
        s.close()


def test_preflight_flags_potenziamento_over_cap(app_with_temp_db):
    _, SessionLocal = app_with_temp_db
    aid, _, _ = _seed_minimum(SessionLocal)
    from backend import models
    s = SessionLocal()
    try:
        s.add(models.Assignment(
            teacher_id=aid, class_id=None, subject="Potenziamento",
            hours=31, is_potenziamento=True,
        ))
        s.commit()
        from backend.optimization import (
            validate_coteach_sostegno_potenziamento)
        violations = validate_coteach_sostegno_potenziamento(s)
        msg = " ".join(violations)
        assert "30" in msg
    finally:
        s.close()
