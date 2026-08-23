"""Integrity CHECK audit + Alembic materialisation (audit 2026-08-23)."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from backend import models
from backend.db import Base
from backend.integrity_checks import (
    ASSIGN_XOR_NAME,
    COTEACH_XOR_NAME,
    CSP_REQUIRED_NAME,
    audit_integrity,
    fix_derived_required,
    has_check,
    raise_if_xor_dirty,
    summarize,
)


def _engine(tmp_path):
    url = f"sqlite:///{tmp_path / 'integrity.db'}"
    eng = create_engine(url, future=True)
    Base.metadata.create_all(bind=eng)
    return eng


def test_fresh_db_already_has_named_checks(tmp_path):
    eng = _engine(tmp_path)
    with eng.connect() as conn:
        assert has_check(conn, "assignments", ASSIGN_XOR_NAME)
        assert has_check(conn, "coteach_groups", COTEACH_XOR_NAME)
        assert has_check(conn, "classroom_subject_preferences", CSP_REQUIRED_NAME)
        report = audit_integrity(conn)
        assert summarize(report)["clean"] is True
    eng.dispose()


def test_audit_finds_assignment_xor_via_core(tmp_path):
    """ORM flush is already blocked by the CHECK; Core + no CHECK
    simulates a pre-revision DB. We drop the CHECK by rebuilding a
    bare table is overkill: insert through text after disabling
    enforcement is not possible on SQLite. Instead we audit the
    predicate against rows we sneak in with PRAGMA ignore_check_
    constraints.
    """
    eng = _engine(tmp_path)
    Session = sessionmaker(bind=eng, future=True)
    with Session() as db:
        t = models.Teacher(name="ProfXor")
        cl = models.SchoolClass(name="1Z")
        g = models.StudyGroup(name="Gxor", kind="other")
        db.add_all([t, cl, g])
        db.flush()
        tid, cid, gid = t.id, cl.id, g.id
        db.commit()

    with eng.begin() as conn:
        conn.execute(text("PRAGMA ignore_check_constraints = 1"))
        conn.execute(
            text(
                "INSERT INTO assignments "
                "(teacher_id, class_id, group_id, subject, hours, "
                " locked, is_support, is_potenziamento) "
                "VALUES (:t, :c, :g, 'X', 2, 0, 0, 0)"
            ),
            {"t": tid, "c": cid, "g": gid},
        )
        conn.execute(text("PRAGMA ignore_check_constraints = 0"))
        report = audit_integrity(conn)
        assert report["assignment_xor"], report
        with pytest.raises(RuntimeError, match="ck_assign_class_group_xor"):
            raise_if_xor_dirty(report)
    eng.dispose()


def test_fix_derived_required(tmp_path):
    eng = _engine(tmp_path)
    Session = sessionmaker(bind=eng, future=True)
    with Session() as db:
        room = models.Classroom(name="A1", kind="standard")
        db.add(room)
        db.flush()
        rid = room.id
        db.commit()

    with eng.begin() as conn:
        conn.execute(text("PRAGMA ignore_check_constraints = 1"))
        conn.execute(
            text(
                "INSERT INTO classroom_subject_preferences "
                "(classroom_id, subject, state, weight, required) "
                "VALUES (:r, 'Mate', 'enforced', 10, 0)"
            ),
            {"r": rid},
        )
        conn.execute(text("PRAGMA ignore_check_constraints = 0"))
        drifted = audit_integrity(conn)
        assert drifted["csp_required"], drifted
        n = fix_derived_required(conn)
        assert n == 1
        clean = audit_integrity(conn)
        assert clean["csp_required"] == []
    eng.dispose()


def test_orm_still_rejects_both_set_assignment(tmp_path):
    eng = _engine(tmp_path)
    Session = sessionmaker(bind=eng, future=True)
    with Session() as db:
        t = models.Teacher(name="ProfOk")
        cl = models.SchoolClass(name="2Z")
        g = models.StudyGroup(name="Gok", kind="other")
        db.add_all([t, cl, g])
        db.flush()
        db.add(models.Assignment(
            teacher_id=t.id, class_id=cl.id, group_id=g.id,
            subject="X", hours=2,
        ))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
    eng.dispose()
