"""n_students NOT NULL on classes; capacity NOT NULL on classrooms.

Revision ID: b1c2d3e4f5a6
Revises: f7a8b9c0d1e2
Create Date: 2026-05-08

Backfills the columns when missing (older dev DBs predating the model
addition) and tightens the NOT NULL + server-default contract so
the HARD capacity constraint introduced in `engine/classroom_assignment`
can rely on both columns being populated for every row.

Idempotent: uses ``inspector.get_columns`` to skip the ALTER when the
column already exists. Applies the NOT NULL contract with batch_alter
so SQLite gets a table rebuild while Postgres uses native ALTER.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(insp, table: str, column: str) -> bool:
    if not insp.has_table(table):
        return False
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # school_classes.n_students: add if missing, then enforce NOT NULL.
    if insp.has_table("school_classes"):
        if not _has_column(insp, "school_classes", "n_students"):
            op.add_column(
                "school_classes",
                sa.Column("n_students", sa.Integer(),
                          server_default="25", nullable=False),
            )
        else:
            # Backfill any nulls left over from older default=0 imports
            # before tightening the constraint.
            op.execute(
                "UPDATE school_classes SET n_students = 25 "
                "WHERE n_students IS NULL"
            )
            with op.batch_alter_table("school_classes") as batch_op:
                batch_op.alter_column(
                    "n_students",
                    existing_type=sa.Integer(),
                    nullable=False,
                    server_default="25",
                )

    # classrooms.capacity: same treatment.
    if insp.has_table("classrooms"):
        if not _has_column(insp, "classrooms", "capacity"):
            op.add_column(
                "classrooms",
                sa.Column("capacity", sa.Integer(),
                          server_default="30", nullable=False),
            )
        else:
            op.execute(
                "UPDATE classrooms SET capacity = 30 "
                "WHERE capacity IS NULL"
            )
            with op.batch_alter_table("classrooms") as batch_op:
                batch_op.alter_column(
                    "capacity",
                    existing_type=sa.Integer(),
                    nullable=False,
                    server_default="30",
                )


def downgrade() -> None:
    # Relax NOT NULL but keep the columns. Dropping them would lose
    # data; the columns predated this revision on the model so an
    # asymmetric downgrade matches the historic shape.
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if insp.has_table("school_classes"):
        with op.batch_alter_table("school_classes") as batch_op:
            batch_op.alter_column(
                "n_students",
                existing_type=sa.Integer(),
                nullable=True,
                server_default=None,
            )
    if insp.has_table("classrooms"):
        with op.batch_alter_table("classrooms") as batch_op:
            batch_op.alter_column(
                "capacity",
                existing_type=sa.Integer(),
                nullable=True,
                server_default=None,
            )
