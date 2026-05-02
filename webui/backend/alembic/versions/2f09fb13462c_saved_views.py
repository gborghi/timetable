"""saved views

Revision ID: 2f09fb13462c
Revises: ef8f1d8fbeff
Create Date: 2026-05-02

Adds the saved_views table: a named (entity, dsl_query, sort_levels)
combination that the user can recall from the SortableQueryableList
toolbar.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2f09fb13462c"
down_revision: Union[str, Sequence[str], None] = "ef8f1d8fbeff"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "saved_views" not in set(insp.get_table_names()):
        op.create_table(
            "saved_views",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("entity", sa.String(length=40), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("dsl_query", sa.Text(), nullable=True),
            sa.Column("sort_levels_json", sa.Text(), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("entity", "name", name="uq_saved_view"),
        )
        op.create_index(
            "ix_saved_views_entity",
            "saved_views", ["entity"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "saved_views" in set(insp.get_table_names()):
        op.drop_index("ix_saved_views_entity", table_name="saved_views")
        op.drop_table("saved_views")
