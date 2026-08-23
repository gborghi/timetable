"""widen working_days.code / label for named cycle days

Revision ID: d9e0f1a2b3c4
Revises: e7f8a9b0c1d2
Create Date: 2026-08-23

Named days (lun1, Gatto, …) need more than 8 chars and are not ISO
weekday codes. SQLite rebuilds the table via batch_alter.

Linear after the already-shipped disposizione revision so there is
one alembic head.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d9e0f1a2b3c4"
down_revision: Union[str, Sequence[str], None] = "e7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("working_days") as batch:
        batch.alter_column(
            "code",
            existing_type=sa.String(length=8),
            type_=sa.String(length=32),
            existing_nullable=False,
        )
        batch.alter_column(
            "label",
            existing_type=sa.String(length=32),
            type_=sa.String(length=64),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("working_days") as batch:
        batch.alter_column(
            "code",
            existing_type=sa.String(length=32),
            type_=sa.String(length=8),
            existing_nullable=False,
        )
        batch.alter_column(
            "label",
            existing_type=sa.String(length=64),
            type_=sa.String(length=32),
            existing_nullable=False,
        )
