"""add_bed_allocation_tables

Revision ID: 52eb1621ddf4
Revises: d72f1a9b3c05
Create Date: 2026-05-28 10:38:52.431628

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '52eb1621ddf4'
down_revision: Union[str, None] = 'd72f1a9b3c05'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create floors table
    op.create_table(
        'floors',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('type', sa.String(length=50), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_floors_number'), 'floors', ['number'], unique=True)
    op.create_index(op.f('ix_floors_created_at'), 'floors', ['created_at'], unique=False)

    # 2. Create rooms table
    op.create_table(
        'rooms',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('floor_id', sa.String(length=36), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('type', sa.String(length=50), nullable=False),
        sa.Column('capacity', sa.Integer(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['floor_id'], ['floors.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_rooms_floor_id'), 'rooms', ['floor_id'], unique=False)
    op.create_index(op.f('ix_rooms_number'), 'rooms', ['number'], unique=False)
    op.create_index(op.f('ix_rooms_created_at'), 'rooms', ['created_at'], unique=False)

    # 3. Create beds table
    op.create_table(
        'beds',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('room_id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('type', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('patient_id', sa.Integer(), nullable=True),
        sa.Column('allocation_time', sa.DateTime(), nullable=True),
        sa.Column('admission_date', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['room_id'], ['rooms.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_beds_room_id'), 'beds', ['room_id'], unique=False)
    op.create_index(op.f('ix_beds_patient_id'), 'beds', ['patient_id'], unique=False)
    op.create_index(op.f('ix_beds_created_at'), 'beds', ['created_at'], unique=False)

    # 4. Create bed_activity_logs table
    op.create_table(
        'bed_activity_logs',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('type', sa.String(length=50), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('floor_id', sa.String(length=36), nullable=True),
        sa.Column('room_id', sa.String(length=36), nullable=True),
        sa.Column('bed_id', sa.String(length=36), nullable=True),
        sa.Column('patient_id', sa.String(length=36), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_bed_activity_logs_timestamp'), 'bed_activity_logs', ['timestamp'], unique=False)
    op.create_index(op.f('ix_bed_activity_logs_created_at'), 'bed_activity_logs', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_table('bed_activity_logs')
    op.drop_table('beds')
    op.drop_table('rooms')
    op.drop_table('floors')
