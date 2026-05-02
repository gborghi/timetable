"""free-day prefs + class max-hours + general DSL constraints

Revision ID: c2bf15b1f730
Revises: eb0ed055682c
Create Date: 2026-05-02 20:42:54.785630

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c2bf15b1f730"
down_revision: Union[str, Sequence[str], None] = "eb0ed055682c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(bind, table: str, col: str) -> bool:
    insp = sa.inspect(bind)
    return col in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    """Upgrade schema.

    Autogenerate diff caught:
      - new `general_constraints` table
      - new SchoolClass columns (preferred_free_days_json,
        required_free_days_count, max_hours_per_day)

    The Teacher.preferred_free_days_json + Teacher.required_free_days_count
    columns were already added to dev DBs by
    `db._apply_lightweight_migrations` (which runs idempotently on
    every backend startup), so autogenerate didn't see them as a
    diff. They MUST also live in this Alembic migration so a fresh
    DB coming from `alembic upgrade head` ends up with the same
    shape. The _has_column() guards make every ADD COLUMN
    idempotent so re-running on an already-migrated dev DB is a
    no-op.
    """
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # ----- general_constraints (new table) ---------------------------
    if "general_constraints" not in insp.get_table_names():
        op.create_table(
            "general_constraints",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("expression", sa.Text(), nullable=False),
            sa.Column("label", sa.String(length=160), nullable=True),
            sa.Column("level", sa.String(length=16), nullable=False,
                      comment="hard|soft|preferred|enforced"),
            sa.Column("weight", sa.Integer(), nullable=False,
                      comment="SOFT penalty (sign-flipped negative for PREFERRED)."),
            sa.Column("scope", sa.String(length=24), nullable=False,
                      comment="global|teacher|class|classroom|group|subject|curriculum"),
            sa.Column("owner_id", sa.Integer(), nullable=True,
                      comment="FK-like reference into the right entity table; "
                              "NULL for scope=global."),
            sa.Column("parsed_ast_json", sa.Text(), nullable=True,
                      comment="JSON cache of the parsed AST."),
            sa.PrimaryKeyConstraint("id"),
        )

    # ----- SchoolClass: free-day fields + max_hours_per_day ----------
    with op.batch_alter_table("school_classes", schema=None) as batch_op:
        if not _has_column(bind, "school_classes",
                            "preferred_free_days_json"):
            batch_op.add_column(sa.Column(
                "preferred_free_days_json", sa.Text(), nullable=True,
                comment="JSON list of up to 3 free-day preferences "
                        "[{day:1..6, is_hard:bool, soft_penalty:int|None}].",
            ))
        if not _has_column(bind, "school_classes",
                            "required_free_days_count"):
            batch_op.add_column(sa.Column(
                "required_free_days_count", sa.Integer(),
                nullable=False, server_default="0",
                comment="HARD: numero esatto di giorni liberi a settimana.",
            ))
        if not _has_column(bind, "school_classes", "max_hours_per_day"):
            batch_op.add_column(sa.Column(
                "max_hours_per_day", sa.Integer(),
                nullable=False, server_default="5",
                comment="HARD: massimo numero di ore al giorno.",
            ))

    # ----- Teacher: free-day fields ---------------------------------
    with op.batch_alter_table("teachers", schema=None) as batch_op:
        if not _has_column(bind, "teachers", "preferred_free_days_json"):
            batch_op.add_column(sa.Column(
                "preferred_free_days_json", sa.Text(), nullable=True,
                comment="JSON list of up to 3 free-day preferences.",
            ))
        if not _has_column(bind, "teachers", "required_free_days_count"):
            batch_op.add_column(sa.Column(
                "required_free_days_count", sa.Integer(),
                nullable=False, server_default="1",
                comment="HARD: numero esatto di giorni liberi a settimana "
                        "(CCNL italiano = 1).",
            ))


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    insp = sa.inspect(bind)

    with op.batch_alter_table("teachers", schema=None) as batch_op:
        if _has_column(bind, "teachers", "required_free_days_count"):
            batch_op.drop_column("required_free_days_count")
        if _has_column(bind, "teachers", "preferred_free_days_json"):
            batch_op.drop_column("preferred_free_days_json")

    with op.batch_alter_table("school_classes", schema=None) as batch_op:
        if _has_column(bind, "school_classes", "max_hours_per_day"):
            batch_op.drop_column("max_hours_per_day")
        if _has_column(bind, "school_classes", "required_free_days_count"):
            batch_op.drop_column("required_free_days_count")
        if _has_column(bind, "school_classes", "preferred_free_days_json"):
            batch_op.drop_column("preferred_free_days_json")

    if "general_constraints" in insp.get_table_names():
        op.drop_table("general_constraints")
