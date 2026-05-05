"""PLESSI: school sites + commuting rules + entity policies

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-05-05

Adds the three new tables and the FK column on classrooms:

- ``plessi``: a physical site of an Istituto (Sede Centrale,
  Succursale, Plesso ITT, ...).
- ``classrooms.plesso_id``: nullable FK linking a classroom to its
  plesso. NULL = no plesso constraint (default site).
- ``plesso_commuting_rules``: rules between PAIRS of plessi keyed
  by entity_kind (teacher / class / group), with optional
  per-entity override and priority.
- ``plesso_entity_policies``: per-entity (teacher or class) global
  policies (single_plesso_per_day, single_plesso_total, any).

No data backfill: existing classrooms get plesso_id=NULL (default
site behaviour). The CP-SAT constraints in the engine treat
NULL-plesso classrooms as a single shared site, preserving
backward compatibility for users who don't configure plessi.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "plessi",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column(
            "tenant_id", sa.Integer(),
            nullable=False, server_default="1"),
    )
    op.create_index(
        "ix_plessi_name", "plessi", ["name"], unique=True)
    op.create_index(
        "ix_plessi_code", "plessi", ["code"], unique=True)
    op.create_index(
        "ix_plessi_tenant_id", "plessi", ["tenant_id"], unique=False)

    op.create_table(
        "plesso_commuting_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "from_plesso_id", sa.Integer(),
            sa.ForeignKey("plessi.id", ondelete="CASCADE"),
            nullable=False),
        sa.Column(
            "to_plesso_id", sa.Integer(),
            sa.ForeignKey("plessi.id", ondelete="CASCADE"),
            nullable=False),
        sa.Column("entity_kind", sa.String(length=16), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("min_gap_hours", sa.Integer(),
                   nullable=False, server_default="0"),
        sa.Column("allowed_break_only", sa.Boolean(),
                   nullable=False, server_default=sa.false()),
        sa.Column("break_start_hour", sa.Integer(), nullable=True),
        sa.Column("break_end_hour", sa.Integer(), nullable=True),
        sa.Column("symmetric", sa.Boolean(),
                   nullable=False, server_default=sa.true()),
        sa.Column("priority", sa.Integer(),
                   nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column(
            "tenant_id", sa.Integer(),
            nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "from_plesso_id", "to_plesso_id",
            "entity_kind", "entity_id",
            name="uq_plesso_commuting_rule"),
    )
    op.create_index(
        "ix_plesso_commuting_rules_from",
        "plesso_commuting_rules", ["from_plesso_id"])
    op.create_index(
        "ix_plesso_commuting_rules_to",
        "plesso_commuting_rules", ["to_plesso_id"])
    op.create_index(
        "ix_plesso_commuting_rules_kind",
        "plesso_commuting_rules", ["entity_kind"])
    op.create_index(
        "ix_plesso_commuting_rules_entity",
        "plesso_commuting_rules", ["entity_id"])

    op.create_table(
        "plesso_entity_policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entity_kind", sa.String(length=16), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("policy", sa.String(length=32),
                   nullable=False, server_default="any"),
        sa.Column(
            "plesso_id", sa.Integer(),
            sa.ForeignKey("plessi.id", ondelete="SET NULL"),
            nullable=True),
        sa.Column("priority", sa.Integer(),
                   nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column(
            "tenant_id", sa.Integer(),
            nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "entity_kind", "entity_id", "policy",
            name="uq_plesso_entity_policy"),
    )
    op.create_index(
        "ix_plesso_entity_policies_kind",
        "plesso_entity_policies", ["entity_kind"])
    op.create_index(
        "ix_plesso_entity_policies_entity",
        "plesso_entity_policies", ["entity_id"])
    op.create_index(
        "ix_plesso_entity_policies_plesso",
        "plesso_entity_policies", ["plesso_id"])

    with op.batch_alter_table("classrooms") as batch:
        batch.add_column(sa.Column(
            "plesso_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_classrooms_plesso_id", "plessi",
            ["plesso_id"], ["id"], ondelete="SET NULL")
    op.create_index(
        "ix_classrooms_plesso_id",
        "classrooms", ["plesso_id"])


def downgrade() -> None:
    op.drop_index("ix_classrooms_plesso_id", table_name="classrooms")
    with op.batch_alter_table("classrooms") as batch:
        batch.drop_constraint("fk_classrooms_plesso_id",
                                type_="foreignkey")
        batch.drop_column("plesso_id")

    op.drop_table("plesso_entity_policies")
    op.drop_table("plesso_commuting_rules")
    op.drop_table("plessi")
