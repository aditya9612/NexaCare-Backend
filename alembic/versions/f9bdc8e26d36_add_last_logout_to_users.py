"""add_last_logout_to_users

Revision ID: f9bdc8e26d36
Revises: a7b8c9d0e1f2, b62b952f14aa
Create Date: 2026-07-08 12:42:29.546277

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f9bdc8e26d36'
down_revision: Union[str, None] = ('a7b8c9d0e1f2', 'b62b952f14aa')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('last_logout_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'last_logout_at')
