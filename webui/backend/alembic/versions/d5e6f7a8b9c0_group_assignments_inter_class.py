"""group_id on assignments + coteach_groups, group_name on lessons (Task C3)

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-05-04 23:30:00

Task C3 (Opzione B): an Assignment / CoteachGroup / Lesson can
target either a SchoolClass (class_id / class_name) or a StudyGroup
(group_id / group_name). XOR invariant enforced at the application
layer (a CHECK constraint would be ideal but SQLite's CHECK support
in batch_alter_table is limited; the validation in
optimization._preflight_lock_check / routers ensures consistency).

Schema changes:
- assignments.group_id (nullable FK to study_groups)
- coteach_groups.class_id is now nullable
- coteach_groups.group_id (nullable FK to study_groups)
- lessons.group_name (nullable VARCHAR)

No data backfill: existing rows already have class_id / class_name
set; new rows will have group_id / group_name when targeting groups.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("assignments") as batch:
        batch.add_column(sa.Column(
            "group_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_assignments_group_id",
            "study_groups", ["group_id"], ["id"], ondelete="CASCADE")
    with op.batch_alter_table("assignments") as batch:
        batch.create_index(
            "ix_assignments_group_id", ["group_id"])

    with op.batch_alter_table("coteach_groups") as batch:
        batch.alter_column("class_id", nullable=True)
        batch.add_column(sa.Column(
            "group_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_coteach_groups_group_id",
            "study_groups", ["group_id"], ["id"], ondelete="CASCADE")
    with op.batch_alter_table("coteach_groups") as batch:
        batch.create_index(
            "ix_coteach_groups_group_id", ["group_id"])
        batch.create_unique_constraint(
            "uq_coteach_group_g_subj", ["group_id", "subject"])

    with op.batch_alter_table("lessons") as batch:
        batch.add_column(sa.Column(
            "group_name", sa.String(120), nullable=True))
    with op.batch_alter_table("lessons") as batch:
        batch.create_index(
            "ix_lessons_group_name", ["group_name"])


def downgrade() -> None:
    with op.batch_alter_table("lessons") as batch:
        batch.drop_index("ix_lessons_group_name")
        batch.drop_column("group_name")

    with op.batch_alter_table("coteach_groups") as batch:
        batch.drop_constraint("uq_coteach_group_g_subj", type_="unique")
        batch.drop_index("ix_coteach_groups_group_id")
        batch.drop_constraint(
            "fk_coteach_groups_group_id", type_="foreignkey")
        batch.drop_column("group_id")
        batch.alter_column("class_id", nullable=False)

    with op.batch_alter_table("assignments") as batch:
        batch.drop_index("ix_assignments_group_id")
        batch.drop_constraint(
            "fk_assignments_group_id", type_="foreignkey")
        batch.drop_column("group_id")
