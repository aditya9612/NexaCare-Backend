"""add nurse code to nurses

Revision ID: 38c1d7274a68
Revises: 02bb5646252f
Create Date: 2026-07-01 16:58:19.886724

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



revision: str = '38c1d7274a68'
down_revision: Union[str, None] = '02bb5646252f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
