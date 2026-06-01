"""add_branch_id_to_users

Revision ID: 3b601468c86f
Revises: c0838301c393
Create Date: 2026-06-01 18:42:01.306923

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '3b601468c86f'
down_revision: Union[str, None] = 'c0838301c393'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add branch_id column to users table
    op.add_column('users', sa.Column('branch_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_users_branch_id'), 'users', ['branch_id'], unique=False)
    op.create_foreign_key(
        'fk_users_branches', 
        'users', 
        'branches', 
        ['branch_id'], 
        ['id'], 
        ondelete='SET NULL'
    )


def downgrade() -> None:
    op.drop_constraint('fk_users_branches', 'users', type_='foreignkey')
    op.drop_index(op.f('ix_users_branch_id'), table_name='users')
    op.drop_column('users', 'branch_id')
