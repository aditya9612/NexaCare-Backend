"""create staff table

Revision ID: a609ea3b360d
Revises: d37ebcb2dc69
Create Date: 2026-06-10 15:45:14.304180

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a609ea3b360d'
down_revision: Union[str, None] = 'd37ebcb2dc69'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = insp.get_table_names()
    
    # 1. Create staff table if not exists
    if 'staff' not in tables:
        op.create_table(
            'staff',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('first_name', sa.String(length=100), nullable=False),
            sa.Column('last_name', sa.String(length=100), nullable=False),
            sa.Column('email', sa.String(length=255), nullable=False),
            sa.Column('phone', sa.String(length=20), nullable=True),
            sa.Column('employee_code', sa.String(length=50), nullable=False),
            sa.Column('department_id', sa.Integer(), nullable=False),
            sa.Column('role_id', sa.Integer(), nullable=False),
            sa.Column('status', sa.String(length=50), nullable=False, server_default='active'),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='0'),
            sa.Column('deleted_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['department_id'], ['departments.department_id']),
            sa.ForeignKeyConstraint(['role_id'], ['roles.id']),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_staff_id'), 'staff', ['id'], unique=False)
        op.create_index(op.f('ix_staff_first_name'), 'staff', ['first_name'], unique=False)
        op.create_index(op.f('ix_staff_last_name'), 'staff', ['last_name'], unique=False)
        op.create_index(op.f('ix_staff_email'), 'staff', ['email'], unique=True)
        op.create_index(op.f('ix_staff_employee_code'), 'staff', ['employee_code'], unique=True)
        op.create_index(op.f('ix_staff_department_id'), 'staff', ['department_id'], unique=False)
        op.create_index(op.f('ix_staff_role_id'), 'staff', ['role_id'], unique=False)
        op.create_index(op.f('ix_staff_status'), 'staff', ['status'], unique=False)
        op.create_index(op.f('ix_staff_is_deleted'), 'staff', ['is_deleted'], unique=False)

    # 2. Defensive handling of other autodetected index updates
    indexes_bed_activity = [idx['name'] for idx in insp.get_indexes('bed_activity_logs')]
    if 'ix_bed_activity_logs_id' not in indexes_bed_activity:
        op.create_index(op.f('ix_bed_activity_logs_id'), 'bed_activity_logs', ['id'], unique=False)

    indexes_beds = [idx['name'] for idx in insp.get_indexes('beds')]
    if 'ix_beds_id' not in indexes_beds:
        op.create_index(op.f('ix_beds_id'), 'beds', ['id'], unique=False)

    indexes_floors = [idx['name'] for idx in insp.get_indexes('floors')]
    if 'ix_floors_id' not in indexes_floors:
        op.create_index(op.f('ix_floors_id'), 'floors', ['id'], unique=False)

    indexes_nurses = [idx['name'] for idx in insp.get_indexes('nurses')]
    if 'uq_nurses_nurse_code' in indexes_nurses:
        op.drop_index('uq_nurses_nurse_code', table_name='nurses')


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = insp.get_table_names()
    
    # 1. Drop staff table if exists
    if 'staff' in tables:
        op.drop_table('staff')
        
    # 2. Restore indexes
    indexes_nurses = [idx['name'] for idx in insp.get_indexes('nurses')]
    if 'uq_nurses_nurse_code' not in indexes_nurses:
        op.create_index('uq_nurses_nurse_code', 'nurses', ['nurse_code'], unique=True)
        
    indexes_floors = [idx['name'] for idx in insp.get_indexes('floors')]
    if 'ix_floors_id' in indexes_floors:
        op.drop_index('ix_floors_id', table_name='floors')
        
    indexes_beds = [idx['name'] for idx in insp.get_indexes('beds')]
    if 'ix_beds_id' in indexes_beds:
        op.drop_index('ix_beds_id', table_name='beds')
        
    indexes_bed_activity = [idx['name'] for idx in insp.get_indexes('bed_activity_logs')]
    if 'ix_bed_activity_logs_id' in indexes_bed_activity:
        op.drop_index('ix_bed_activity_logs_id', table_name='bed_activity_logs')
