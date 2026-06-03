"""rename_departments_columns

Revision ID: 06b170ef9061
Revises: c91f3e8d2a01
Create Date: 2026-06-03 10:54:10.899262

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



revision: str = '06b170ef9061'
down_revision: Union[str, None] = 'c91f3e8d2a01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = [c['name'] for c in insp.get_columns('departments')]
    
    if 'id' in columns:
        op.alter_column('departments', 'id', new_column_name='department_id', existing_type=sa.Integer())
    
    if 'name' in columns:
        op.alter_column('departments', 'name', new_column_name='department_name', existing_type=sa.String(length=100))
        
    if 'description' in columns:
        op.drop_column('departments', 'description')
        
    if 'is_active' in columns:
        op.drop_column('departments', 'is_active')


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = [c['name'] for c in insp.get_columns('departments')]
    
    if 'department_id' in columns:
        op.alter_column('departments', 'department_id', new_column_name='id', existing_type=sa.Integer())
        
    if 'department_name' in columns:
        op.alter_column('departments', 'department_name', new_column_name='name', existing_type=sa.String(length=100))
        
    if 'description' not in columns:
        op.add_column('departments', sa.Column('description', sa.String(length=255), nullable=True))
        
    if 'is_active' not in columns:
        op.add_column('departments', sa.Column('is_active', sa.Boolean(), server_default='1', nullable=False))

