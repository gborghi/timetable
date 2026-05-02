"""classroom tags

Revision ID: fadcd08c545f
Revises: c2bf15b1f730
Create Date: 2026-05-02

Adds the classroom_tags + classroom_tag_assignments tables (Strada B
many-to-many tag system on Classroom). Both tables are created with
guards so re-running on a dev DB where Base.metadata.create_all
already produced them is a no-op.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "fadcd08c545f"
down_revision: Union[str, Sequence[str], None] = "c2bf15b1f730"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "classroom_tags" not in tables:
        op.create_table(
            "classroom_tags",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=64), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name"),
        )
        op.create_index(
            "ix_classroom_tags_name",
            "classroom_tags", ["name"], unique=True,
        )

    if "classroom_tag_assignments" not in tables:
        op.create_table(
            "classroom_tag_assignments",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("classroom_id", sa.Integer(), nullable=False),
            sa.Column("tag_id", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(
                ["classroom_id"], ["classrooms.id"], ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["tag_id"], ["classroom_tags.id"], ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "classroom_id", "tag_id", name="uq_classroom_tag",
            ),
        )
        op.create_index(
            "ix_classroom_tag_assignments_classroom_id",
            "classroom_tag_assignments", ["classroom_id"],
        )
        op.create_index(
            "ix_classroom_tag_assignments_tag_id",
            "classroom_tag_assignments", ["tag_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    if "classroom_tag_assignments" in tables:
        op.drop_index(
            "ix_classroom_tag_assignments_tag_id",
            table_name="classroom_tag_assignments",
        )
        op.drop_index(
            "ix_classroom_tag_assignments_classroom_id",
            table_name="classroom_tag_assignments",
        )
        op.drop_table("classroom_tag_assignments")
    if "classroom_tags" in tables:
        op.drop_index(
            "ix_classroom_tags_name", table_name="classroom_tags",
        )
        op.drop_table("classroom_tags")
