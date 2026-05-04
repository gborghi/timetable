"""Task C3 - pre-flight validation for group_id assignments.

Tests that validate_coteach_sostegno_potenziamento() catches
malformed group_assignment rows before they reach the solver:
  - XOR violation (both class_id and group_id set)
  - non-existent group_id
  - empty group (no students)
  - members without home class
  - n_hours <= 0
"""
from __future__ import annotations


def test_group_xor_class_id_set_violates(client):
    from backend import models
    from backend.optimization import (
        validate_coteach_sostegno_potenziamento,
    )
    db = next(client.app.dependency_overrides[
        next(iter(client.app.dependency_overrides))]())
    try:
        t = models.Teacher(name="ProfX")
        cl = models.SchoolClass(name="2A")
        g = models.StudyGroup(name="_GR_", kind="other")
        db.add_all([t, cl, g])
        db.flush()
        s = models.Student(first_name="Anna", last_name="Rossi",
                            class_id=cl.id)
        db.add(s)
        db.flush()
        db.add(models.GroupMembership(group_id=g.id, student_id=s.id))
        db.add(models.Assignment(
            teacher_id=t.id, class_id=cl.id, group_id=g.id,
            subject="X", hours=2,
        ))
        db.commit()
        violations = validate_coteach_sostegno_potenziamento(db)
        assert any("XOR" in v for v in violations), (
            f"expected XOR violation, got: {violations}")
    finally:
        db.close()


def test_group_no_students_violates(client):
    from backend import models
    from backend.optimization import (
        validate_coteach_sostegno_potenziamento,
    )
    db = next(client.app.dependency_overrides[
        next(iter(client.app.dependency_overrides))]())
    try:
        t = models.Teacher(name="ProfX")
        g = models.StudyGroup(name="_EmptyGR_", kind="other")
        db.add_all([t, g])
        db.flush()
        # No GroupMembership rows
        db.add(models.Assignment(
            teacher_id=t.id, class_id=None, group_id=g.id,
            subject="X", hours=2,
        ))
        db.commit()
        violations = validate_coteach_sostegno_potenziamento(db)
        assert any("nessuno" in v.lower() or "studente" in v.lower()
                   for v in violations), (
            f"expected no-student violation, got: {violations}")
    finally:
        db.close()


def test_group_invalid_id_violates(client):
    from backend import models
    from backend.optimization import (
        validate_coteach_sostegno_potenziamento,
    )
    db = next(client.app.dependency_overrides[
        next(iter(client.app.dependency_overrides))]())
    try:
        t = models.Teacher(name="ProfX")
        db.add(t)
        db.flush()
        # group_id pointing at non-existent StudyGroup
        db.add(models.Assignment(
            teacher_id=t.id, class_id=None, group_id=999,
            subject="X", hours=2,
        ))
        db.commit()
        violations = validate_coteach_sostegno_potenziamento(db)
        assert any("inesistente" in v for v in violations), (
            f"expected inesistente, got: {violations}")
    finally:
        db.close()


def test_group_zero_hours_violates(client):
    from backend import models
    from backend.optimization import (
        validate_coteach_sostegno_potenziamento,
    )
    db = next(client.app.dependency_overrides[
        next(iter(client.app.dependency_overrides))]())
    try:
        t = models.Teacher(name="ProfX")
        cl = models.SchoolClass(name="2A")
        g = models.StudyGroup(name="_GR_", kind="other")
        db.add_all([t, cl, g])
        db.flush()
        s = models.Student(first_name="Anna", last_name="Rossi",
                            class_id=cl.id)
        db.add(s)
        db.flush()
        db.add(models.GroupMembership(group_id=g.id, student_id=s.id))
        db.add(models.Assignment(
            teacher_id=t.id, class_id=None, group_id=g.id,
            subject="X", hours=0,
        ))
        db.commit()
        violations = validate_coteach_sostegno_potenziamento(db)
        assert any("hours" in v.lower() and "non valido" in v.lower()
                   for v in violations), (
            f"expected hours violation, got: {violations}")
    finally:
        db.close()


def test_group_valid_passes(client):
    from backend import models
    from backend.optimization import (
        validate_coteach_sostegno_potenziamento,
    )
    db = next(client.app.dependency_overrides[
        next(iter(client.app.dependency_overrides))]())
    try:
        t = models.Teacher(name="ProfX")
        cl = models.SchoolClass(name="2A")
        g = models.StudyGroup(name="_OK_GR_", kind="splitting")
        db.add_all([t, cl, g])
        db.flush()
        s = models.Student(first_name="Anna", last_name="Rossi",
                            class_id=cl.id)
        db.add(s)
        db.flush()
        db.add(models.GroupMembership(group_id=g.id, student_id=s.id))
        db.add(models.Assignment(
            teacher_id=t.id, class_id=None, group_id=g.id,
            subject="Spagnolo", hours=2,
        ))
        db.commit()
        violations = validate_coteach_sostegno_potenziamento(db)
        # Filter for group-related violations only
        group_violations = [v for v in violations
                            if "gruppo" in v.lower()]
        assert not group_violations, (
            f"valid group should not trigger: {group_violations}")
    finally:
        db.close()
