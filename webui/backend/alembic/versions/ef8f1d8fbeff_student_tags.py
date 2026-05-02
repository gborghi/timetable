"""student tags

Revision ID: ef8f1d8fbeff
Revises: fadcd08c545f
Create Date: 2026-05-02

Adds student_tags + student_tag_assignments (many-to-many tag system
on Student, parallel to ClassroomTag).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "ef8f1d8fbeff"
down_revision: Union[str, Sequence[str], None] = "fadcd08c545f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "student_tags" not in tables:
        op.create_table(
            "student_tags",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=64), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name"),
        )
        op.create_index(
            "ix_student_tags_name",
            "student_tags", ["name"], unique=True,
        )

    if "student_tag_assignments" not in tables:
        op.create_table(
            "student_tag_assignments",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("student_id", sa.Integer(), nullable=False),
            sa.Column("tag_id", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(
                ["student_id"], ["students.id"], ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["tag_id"], ["student_tags.id"], ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "student_id", "tag_id", name="uq_student_tag",
            ),
        )
        op.create_index(
            "ix_student_tag_assignments_student_id",
            "student_tag_assignments", ["student_id"],
        )
        op.create_index(
            "ix_student_tag_assignments_tag_id",
            "student_tag_assignments", ["tag_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    if "student_tag_assignments" in tables:
        op.drop_index(
            "ix_student_tag_assignments_tag_id",
            table_name="student_tag_assignments",
        )
        op.drop_index(
            "ix_student_tag_assignments_student_id",
            table_name="student_tag_assignments",
        )
        op.drop_table("student_tag_assignments")
    if "student_tags" in tables:
        op.drop_index(
            "ix_student_tags_name", table_name="student_tags",
        )
        op.drop_table("student_tags")
