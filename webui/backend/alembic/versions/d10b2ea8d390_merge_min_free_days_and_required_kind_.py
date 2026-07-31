"""merge min_free_days and required_kind heads

Revision ID: d10b2ea8d390
Revises: b2c3d4e5f6a7, c2d3e4f5a6b7
Create Date: 2026-07-30 21:10:01.127227

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd10b2ea8d390'
down_revision: Union[str, Sequence[str], None] = ('b2c3d4e5f6a7', 'c2d3e4f5a6b7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
