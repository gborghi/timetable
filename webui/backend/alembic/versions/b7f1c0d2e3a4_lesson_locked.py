"""lesson locked: per-slot pin distinct from cattedra lock (finding 26)

Revision ID: b7f1c0d2e3a4
Revises: a4d81e2c9f57
Create Date: 2026-07-31

`Lesson.locked` is the "immovable hour" pin. It is deliberately separate
from `Assignment.locked` ("confirmed cattedra"): locking a cattedra fixes
WHO teaches a (class, subject) but must NOT freeze the hours, or a school
that confirms its cattedre can never regenerate the timetable. Only a
pinned Lesson is fed to Phase B / meta as a fixed slot.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7f1c0d2e3a4"
down_revision: Union[str, Sequence[str], None] = "a4d81e2c9f57"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "lessons",
        sa.Column("locked", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("lessons", "locked")
