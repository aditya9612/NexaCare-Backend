"""add_address_to_users

Revision ID: 511be8fa0047
Revises: f7a1c2d3e4b5
Create Date: 2026-08-26 11:49:12.807875

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



revision: str = '511be8fa0047'
down_revision: Union[str, None] = 'f7a1c2d3e4b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('address', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'address')
