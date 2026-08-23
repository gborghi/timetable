"""teacher disposizione hours + school-wide policy

Revision ID: e7f8a9b0c1d2
Revises: c8d9e0f1a2b3
Create Date: 2026-08-23

Standby (disposizione) hours for substitutions:

* ``teachers.disposizione_hours`` — per-teacher weekly quota
* ``school_disposizione_config`` — school cap, eligibility, slot weights

Placed hours reuse ``lessons`` with ``class_name='__disposizione__'``
so coverage / move-lesson stay on the existing substitutions path.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, Sequence[str], None] = "c8d9e0f1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("teachers") as batch:
        batch.add_column(sa.Column(
            "disposizione_hours", sa.Integer(),
            nullable=False, server_default="0",
        ))
    op.create_table(
        "school_disposizione_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False,
                  server_default="1", index=True),
        sa.Column("max_total_hours", sa.Integer(), nullable=True),
        sa.Column("eligibility", sa.String(24), nullable=False,
                  server_default="all"),
        sa.Column("slot_priorities_json", sa.Text(), nullable=True),
        sa.UniqueConstraint("tenant_id",
                            name="uq_disposizione_config_tenant"),
    )


def downgrade() -> None:
    op.drop_table("school_disposizione_config")
    with op.batch_alter_table("teachers") as batch:
        batch.drop_column("disposizione_hours")
