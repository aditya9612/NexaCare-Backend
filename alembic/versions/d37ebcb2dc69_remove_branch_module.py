"""remove_branch_module

Revision ID: d37ebcb2dc69
Revises: 1ce52ee59f85
Create Date: 2026-06-03 15:38:59.474206

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



revision: str = 'd37ebcb2dc69'
down_revision: Union[str, None] = '1ce52ee59f85'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    
    # 1. Drop foreign key constraint on users referencing branches dynamically
    fks = insp.get_foreign_keys('users')
    fk_name = None
    for fk in fks:
        if fk['referred_table'] == 'branches':
            fk_name = fk['name']
            break
            
    if fk_name:
        op.drop_constraint(fk_name, 'users', type_='foreignkey')
    
    # 2. Drop index on users if it exists
    indexes = [idx['name'] for idx in insp.get_indexes('users')]
    if 'ix_users_branch_id' in indexes:
        op.drop_index('ix_users_branch_id', table_name='users')
    
    # 3. Drop branch_id column from users if it exists
    columns = [c['name'] for c in insp.get_columns('users')]
    if 'branch_id' in columns:
        op.drop_column('users', 'branch_id')
    
    # 4. Drop branches table if it exists
    tables = insp.get_table_names()
    if 'branches' in tables:
        op.drop_table('branches')


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = insp.get_table_names()
    
    # 1. Recreate branches table if not exists
    if 'branches' not in tables:
        op.create_table(
            'branches',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('hospital_id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=255), nullable=False),
            sa.Column('code', sa.String(length=50), nullable=False),
            sa.Column('phone', sa.String(length=20), nullable=True),
            sa.Column('email', sa.String(length=255), nullable=True),
            sa.Column('address', sa.String(length=500), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.Column('is_deleted', sa.Boolean(), nullable=False),
            sa.Column('deleted_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['hospital_id'], ['hospitals.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_branches_code'), 'branches', ['code'], unique=True)
        op.create_index(op.f('ix_branches_created_at'), 'branches', ['created_at'], unique=False)
        op.create_index(op.f('ix_branches_email'), 'branches', ['email'], unique=False)
        op.create_index(op.f('ix_branches_hospital_id'), 'branches', ['hospital_id'], unique=False)
        op.create_index(op.f('ix_branches_id'), 'branches', ['id'], unique=False)
        op.create_index(op.f('ix_branches_is_active'), 'branches', ['is_active'], unique=False)
        op.create_index(op.f('ix_branches_is_deleted'), 'branches', ['is_deleted'], unique=False)
        op.create_index(op.f('ix_branches_name'), 'branches', ['name'], unique=False)

    # 2. Re-add branch_id to users if not exists
    columns = [c['name'] for c in insp.get_columns('users')]
    if 'branch_id' not in columns:
        op.add_column('users', sa.Column('branch_id', sa.Integer(), nullable=True))
        op.create_index('ix_users_branch_id', 'users', ['branch_id'], unique=False)
        op.create_foreign_key(
            'fk_users_branches',
            'users',
            'branches',
            ['branch_id'],
            ['id'],
            ondelete='SET NULL'
        )


