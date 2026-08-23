"""materialise integrity CHECKs on existing DBs (audit 2026-08-23)

Revision ID: c8d9e0f1a2b3
Revises: b7f1c0d2e3a4
Create Date: 2026-08-23

``models.py`` already declares three CHECKs:

* ``ck_assign_class_group_xor``
* ``ck_coteach_class_group_xor``
* ``ck_csp_required_matches_state``

They land on *fresh* DBs via ``create_all``. Existing DBs never got
them. This revision:

1. auto-fixes the derived ``required`` flag (not independent data);
2. audits XOR violators and **refuses** to continue if any remain
   (they are not auto-deleted);
3. adds the three CHECKs via ``batch_alter_table`` (SQLite table
   rebuild). Idempotent: a DB that already has the named CHECK
   (fresh ``create_all`` + stamp) is a no-op.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "c8d9e0f1a2b3"
down_revision: Union[str, Sequence[str], None] = "b7f1c0d2e3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from backend.integrity_checks import (
        ASSIGN_XOR_NAME,
        ASSIGN_XOR_SQL,
        COTEACH_XOR_NAME,
        COTEACH_XOR_SQL,
        CSP_REQUIRED_NAME,
        CSP_REQUIRED_SQL,
        audit_integrity,
        fix_derived_required,
        has_check,
        raise_if_xor_dirty,
    )

    bind = op.get_bind()
    fix_derived_required(bind)
    report = audit_integrity(bind)
    raise_if_xor_dirty(report)

    if not has_check(bind, "assignments", ASSIGN_XOR_NAME):
        with op.batch_alter_table("assignments") as batch:
            batch.create_check_constraint(ASSIGN_XOR_NAME, ASSIGN_XOR_SQL)

    if not has_check(bind, "coteach_groups", COTEACH_XOR_NAME):
        with op.batch_alter_table("coteach_groups") as batch:
            batch.create_check_constraint(COTEACH_XOR_NAME, COTEACH_XOR_SQL)

    if not has_check(bind, "classroom_subject_preferences", CSP_REQUIRED_NAME):
        with op.batch_alter_table("classroom_subject_preferences") as batch:
            batch.create_check_constraint(CSP_REQUIRED_NAME, CSP_REQUIRED_SQL)


def downgrade() -> None:
    from backend.integrity_checks import (
        ASSIGN_XOR_NAME,
        COTEACH_XOR_NAME,
        CSP_REQUIRED_NAME,
        has_check,
    )

    bind = op.get_bind()
    if has_check(bind, "assignments", ASSIGN_XOR_NAME):
        with op.batch_alter_table("assignments") as batch:
            batch.drop_constraint(ASSIGN_XOR_NAME, type_="check")
    if has_check(bind, "coteach_groups", COTEACH_XOR_NAME):
        with op.batch_alter_table("coteach_groups") as batch:
            batch.drop_constraint(COTEACH_XOR_NAME, type_="check")
    if has_check(bind, "classroom_subject_preferences", CSP_REQUIRED_NAME):
        with op.batch_alter_table("classroom_subject_preferences") as batch:
            batch.drop_constraint(CSP_REQUIRED_NAME, type_="check")
