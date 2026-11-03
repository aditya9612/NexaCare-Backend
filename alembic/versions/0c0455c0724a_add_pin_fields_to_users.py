"""add_pin_fields_to_users

Revision ID: 0c0455c0724a
Revises: 2db09a4dbdcc
Create Date: 2026-11-03 10:18:15.326439

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision: str = '0c0455c0724a'
down_revision: Union[str, None] = '2db09a4dbdcc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)

    user_cols = [col['name'] for col in inspector.get_columns('users')]

    if 'hashed_pin' not in user_cols:
        op.add_column('users', sa.Column('hashed_pin', sa.String(length=255), nullable=True))
    if 'pin_set_at' not in user_cols:
        op.add_column('users', sa.Column('pin_set_at', sa.DateTime(), nullable=True))
    if 'pin_failed_attempts' not in user_cols:
        op.add_column('users', sa.Column('pin_failed_attempts', sa.Integer(), server_default='0', nullable=False))
    if 'pin_locked_until' not in user_cols:
        op.add_column('users', sa.Column('pin_locked_until', sa.DateTime(), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)

    user_cols = [col['name'] for col in inspector.get_columns('users')]

    if 'pin_locked_until' in user_cols:
        op.drop_column('users', 'pin_locked_until')
    if 'pin_failed_attempts' in user_cols:
        op.drop_column('users', 'pin_failed_attempts')
    if 'pin_set_at' in user_cols:
        op.drop_column('users', 'pin_set_at')
    if 'hashed_pin' in user_cols:
        op.drop_column('users', 'hashed_pin')
