"""run telemetry

Revision ID: a848420325b3
Revises: 2f09fb13462c
Create Date: 2026-05-02

Adds run_telemetry table for time-series objective/HARD/ moves
counts emitted by the solver/metaheuristic modules during a run.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a848420325b3"
down_revision: Union[str, Sequence[str], None] = "2f09fb13462c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "run_telemetry" not in set(insp.get_table_names()):
        op.create_table(
            "run_telemetry",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("run_id", sa.Integer(), nullable=False),
            sa.Column("step", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("timestamp_s", sa.Float(), nullable=False,
                      server_default="0"),
            sa.Column("phase", sa.String(length=32), nullable=False,
                      server_default=""),
            sa.Column("payload_json", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(
                ["run_id"], ["runs.id"], ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("run_id", "step", "phase",
                                 name="uq_run_telemetry_step"),
        )
        op.create_index("ix_run_telemetry_run_id",
                         "run_telemetry", ["run_id"])
        op.create_index("ix_run_telemetry_phase",
                         "run_telemetry", ["phase"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "run_telemetry" in set(insp.get_table_names()):
        op.drop_index("ix_run_telemetry_phase", table_name="run_telemetry")
        op.drop_index("ix_run_telemetry_run_id", table_name="run_telemetry")
        op.drop_table("run_telemetry")
