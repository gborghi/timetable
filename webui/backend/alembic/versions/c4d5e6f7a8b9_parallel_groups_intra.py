"""parallel_group_id on assignments (Task C2)

Revision ID: c4d5e6f7a8b9
Revises: b91a4e2c1f00
Create Date: 2026-05-04 22:00:00

Task C2: Assignments with the same parallel_group_id and same
class_id are taught in parallel. Use case: religione + alternativa
in 3B (different teachers, same slot, class counts as busy ONCE).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "b91a4e2c1f00"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("assignments") as batch:
        batch.add_column(sa.Column(
            "parallel_group_id", sa.Integer(), nullable=True))
    with op.batch_alter_table("assignments") as batch:
        batch.create_index("ix_assignments_parallel_group_id",
                            ["parallel_group_id"])


def downgrade() -> None:
    with op.batch_alter_table("assignments") as batch:
        batch.drop_index("ix_assignments_parallel_group_id")
        batch.drop_column("parallel_group_id")
