"""working hours config (Tab Ore)

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-05-07

Adds the `working_days` and `working_hour_slots` tables (Tab Ore --
configurable weekly working days and per-day timetable slots). Both
tables are created with guards so re-running on a dev DB where
``Base.metadata.create_all`` already produced them is a no-op.

Default seed (idempotent): lun-sab + slots 0..5 = 8:00-14:00. The
legacy code that hardcoded DAYS=[1..6] / HOURS=[8..13] keeps working
because the seed mirrors those exact values.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, Sequence[str], None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_DEFAULT_DAYS = [
    # (code, label, position, legacy_day_number)
    ("MON", "Lunedi",    0, 1),
    ("TUE", "Martedi",   1, 2),
    ("WED", "Mercoledi", 2, 3),
    ("THU", "Giovedi",   3, 4),
    ("FRI", "Venerdi",   4, 5),
    ("SAT", "Sabato",    5, 6),
]


def _default_slots() -> list[tuple[int, str, str, str, int]]:
    """6 slots / day, 8:00 -> 14:00, legacy_hour_number 8..13."""
    out = []
    for i in range(6):
        h = 8 + i
        out.append((
            i,
            f"{h:02d}:00",
            f"{h+1:02d}:00",
            f"{i+1}ª ora",
            h,
        ))
    return out


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "working_days" not in tables:
        op.create_table(
            "working_days",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False,
                      server_default="1"),
            sa.Column("code", sa.String(length=8), nullable=False),
            sa.Column("label", sa.String(length=32), nullable=False),
            sa.Column("position", sa.Integer(), nullable=False),
            sa.Column("legacy_day_number", sa.Integer(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False,
                      server_default=sa.text("1")),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "code",
                                name="uq_workingday_tenant_code"),
            sa.UniqueConstraint("tenant_id", "position",
                                name="uq_workingday_tenant_position"),
        )
        op.create_index(
            "ix_working_days_tenant_id", "working_days", ["tenant_id"]
        )
        op.create_index(
            "ix_working_days_code", "working_days", ["code"]
        )
        op.create_index(
            "ix_working_days_position", "working_days", ["position"]
        )
        op.create_index(
            "ix_working_days_legacy_day_number",
            "working_days", ["legacy_day_number"],
        )

    if "working_hour_slots" not in tables:
        op.create_table(
            "working_hour_slots",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("day_id", sa.Integer(), nullable=False),
            sa.Column("slot_index", sa.Integer(), nullable=False),
            sa.Column("start_time", sa.String(length=5), nullable=False),
            sa.Column("end_time", sa.String(length=5), nullable=False),
            sa.Column("label", sa.String(length=32), nullable=True),
            sa.Column("legacy_hour_number", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(
                ["day_id"], ["working_days.id"], ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("day_id", "slot_index",
                                name="uq_slot_day_index"),
        )
        op.create_index(
            "ix_working_hour_slots_day_id",
            "working_hour_slots", ["day_id"],
        )
        op.create_index(
            "ix_working_hour_slots_slot_index",
            "working_hour_slots", ["slot_index"],
        )

    # Idempotent default seed: lun-sab + slots 0..5 = 8..14.
    # Skipped if any working_day row already exists for tenant 1.
    existing = bind.execute(sa.text(
        "SELECT COUNT(*) FROM working_days WHERE tenant_id = 1"
    )).scalar()
    if existing == 0:
        for code, label, pos, legacy in _DEFAULT_DAYS:
            bind.execute(sa.text(
                "INSERT INTO working_days "
                "(tenant_id, code, label, position, "
                " legacy_day_number, is_active) "
                "VALUES (1, :code, :label, :pos, :legacy, 1)"
            ), {
                "code": code, "label": label,
                "pos": pos, "legacy": legacy,
            })
            day_id = bind.execute(sa.text(
                "SELECT id FROM working_days "
                "WHERE tenant_id = 1 AND code = :code"
            ), {"code": code}).scalar()
            for idx, start, end, lab, leg in _default_slots():
                bind.execute(sa.text(
                    "INSERT INTO working_hour_slots "
                    "(day_id, slot_index, start_time, end_time, "
                    " label, legacy_hour_number) "
                    "VALUES (:d, :i, :s, :e, :l, :leg)"
                ), {
                    "d": day_id, "i": idx, "s": start,
                    "e": end, "l": lab, "leg": leg,
                })


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    if "working_hour_slots" in tables:
        op.drop_index(
            "ix_working_hour_slots_slot_index",
            table_name="working_hour_slots",
        )
        op.drop_index(
            "ix_working_hour_slots_day_id",
            table_name="working_hour_slots",
        )
        op.drop_table("working_hour_slots")
    if "working_days" in tables:
        op.drop_index(
            "ix_working_days_legacy_day_number",
            table_name="working_days",
        )
        op.drop_index(
            "ix_working_days_position", table_name="working_days",
        )
        op.drop_index(
            "ix_working_days_code", table_name="working_days",
        )
        op.drop_index(
            "ix_working_days_tenant_id", table_name="working_days",
        )
        op.drop_table("working_days")
