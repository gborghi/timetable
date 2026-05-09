"""rename Teacher.required_free_days_count -> min_free_days

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-09

Renames the Teacher column to align with the canonical pragma name
``teacher_at_least_n_free_days``: the column carries the floor `n`, so
"min_free_days" is clearer than the overloaded "required" naming
(which suggested an exact-count semantic the engine never enforced).

Idempotent: re-running on a DB where the rename has already happened
or where only one of the two columns exists is a no-op. SchoolClass
keeps its own `required_free_days_count` column -- the semantic is
deliberately distinct on the class side and renaming it is out of
scope here.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(bind, table: str, col: str) -> bool:
    insp = sa.inspect(bind)
    if not insp.has_table(table):
        return False
    return col in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    has_old = _has_column(bind, "teachers", "required_free_days_count")
    has_new = _has_column(bind, "teachers", "min_free_days")

    if has_new and has_old:
        # Both columns exist (e.g. dev DB with the lightweight migration
        # plus an interim manual ADD COLUMN). Backfill the new column
        # from the old, then drop the old. SQLite needs batch_alter.
        op.execute(
            "UPDATE teachers SET min_free_days = "
            "COALESCE(required_free_days_count, 1)")
        with op.batch_alter_table("teachers", schema=None) as batch_op:
            batch_op.drop_column("required_free_days_count")
        return

    if has_new and not has_old:
        return  # already migrated

    # has_old (and not has_new): standard path -- add new, backfill,
    # drop old.
    with op.batch_alter_table("teachers", schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            "min_free_days", sa.Integer(),
            nullable=False, server_default="1",
            comment="HARD: minimum number of free days per week "
                    "(>= N). Default 1 = CCNL italiano.",
        ))
    op.execute(
        "UPDATE teachers SET min_free_days = "
        "COALESCE(required_free_days_count, 1)")
    with op.batch_alter_table("teachers", schema=None) as batch_op:
        batch_op.drop_column("required_free_days_count")


def downgrade() -> None:
    bind = op.get_bind()
    has_old = _has_column(bind, "teachers", "required_free_days_count")
    has_new = _has_column(bind, "teachers", "min_free_days")
    if has_old and not has_new:
        return  # already downgraded
    if not has_new:
        return  # nothing to do
    if not has_old:
        with op.batch_alter_table("teachers", schema=None) as batch_op:
            batch_op.add_column(sa.Column(
                "required_free_days_count", sa.Integer(),
                nullable=False, server_default="1",
            ))
        op.execute(
            "UPDATE teachers SET required_free_days_count = min_free_days")
    with op.batch_alter_table("teachers", schema=None) as batch_op:
        batch_op.drop_column("min_free_days")
