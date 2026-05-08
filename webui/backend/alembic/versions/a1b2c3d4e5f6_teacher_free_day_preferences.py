"""teacher_free_day_preferences table

Revision ID: a1b2c3d4e5f6
Revises: fadcd08c545f
Create Date: 2026-05-09

Dedicated relational table for the new 3-priority free-day preference
semantics. The HARD "every teacher must have >=1 free day per week" is
universal and emitted by the constraint translator without consulting
this table; rows here drive only the SOFT penalty (priority 1 -> 30,
priority 2 -> 20, priority 3 -> 10) when the chosen free day differs
from the teacher's preference.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "fadcd08c545f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "teacher_free_day_preferences" in insp.get_table_names():
        return
    op.create_table(
        "teacher_free_day_preferences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Integer(), nullable=False,
                  comment="1..6 Lun..Sab"),
        sa.Column("priority", sa.Integer(), nullable=False,
                  comment="1 (top) .. 3 (low). "
                          "Penalty = 40 - 10*priority."),
        sa.ForeignKeyConstraint(
            ["teacher_id"], ["teachers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "teacher_id", "priority", name="uq_tfdp_priority"),
        sa.UniqueConstraint(
            "teacher_id", "day", name="uq_tfdp_day"),
    )
    op.create_index(
        "ix_teacher_free_day_preferences_teacher_id",
        "teacher_free_day_preferences", ["teacher_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "teacher_free_day_preferences" in insp.get_table_names():
        op.drop_index(
            "ix_teacher_free_day_preferences_teacher_id",
            table_name="teacher_free_day_preferences",
        )
        op.drop_table("teacher_free_day_preferences")
