"""merge all heads

Revision ID: 292b3968f22a
Revises: 1a4e7d0514e6, 98c954715cb0, f5b2c3d4e6f7
Create Date: 2026-06-18 14:49:38.340680

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



revision: str = '292b3968f22a'
down_revision: Union[str, None] = ('1a4e7d0514e6', '98c954715cb0', 'f5b2c3d4e6f7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
