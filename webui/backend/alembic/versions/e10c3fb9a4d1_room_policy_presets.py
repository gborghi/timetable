"""Room-assignment presets: school_classes.room_policy +
classroom_class_preferences.state.

Revision ID: e10c3fb9a4d1
Revises: d10b2ea8d390
Create Date: 2026-07-30

``room_policy`` decides how hard the class' home room binds:
``fissa`` (HARD, with automatic derogation for subjects carrying a
``Subject.required_kind``), ``ibrida`` (SOFT bonus -- the historical
behaviour) or ``libera`` (no home-room constraint at all).

``classroom_class_preferences.state`` lifts that table to the same
4-state taxonomy as the other preference tables, so the fully manual
case ("this class is pinned to / banned from that specific room") is
expressible row by row.

Both columns are backfilled to the value that reproduces today's
behaviour exactly -- ``ibrida`` and ``preferred``. An existing school
must not become infeasible at the classroom step just because it ran
the migration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e10c3fb9a4d1"
down_revision: Union[str, Sequence[str], None] = "d10b2ea8d390"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(insp, table: str, column: str) -> bool:
    if not insp.has_table(table):
        return False
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if insp.has_table("school_classes") and not _has_column(
            insp, "school_classes", "room_policy"):
        op.add_column(
            "school_classes",
            sa.Column("room_policy", sa.String(length=8),
                      nullable=False, server_default="ibrida"),
        )
    if insp.has_table("classroom_class_preferences") and not _has_column(
            insp, "classroom_class_preferences", "state"):
        op.add_column(
            "classroom_class_preferences",
            sa.Column("state", sa.String(length=16),
                      nullable=False, server_default="preferred"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if _has_column(insp, "classroom_class_preferences", "state"):
        with op.batch_alter_table("classroom_class_preferences") as batch_op:
            batch_op.drop_column("state")
    if _has_column(insp, "school_classes", "room_policy"):
        with op.batch_alter_table("school_classes") as batch_op:
            batch_op.drop_column("room_policy")
