"""subjects.required_kind for special-room HARD enforcement.

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-05-08

Adds the optional ``Subject.required_kind`` column. NULL keeps the
historical "any room" behaviour. A value such as ``palestra`` or
``lab_fisica`` makes ``classroom_assignment`` reject any non-matching
room when placing a lesson of that subject.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, Sequence[str], None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(insp, table: str, column: str) -> bool:
    if not insp.has_table(table):
        return False
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if insp.has_table("subjects") and not _has_column(
            insp, "subjects", "required_kind"):
        op.add_column(
            "subjects",
            sa.Column("required_kind", sa.String(length=32),
                      nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if insp.has_table("subjects") and _has_column(
            insp, "subjects", "required_kind"):
        with op.batch_alter_table("subjects") as batch_op:
            batch_op.drop_column("required_kind")
