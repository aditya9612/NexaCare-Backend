"""create_clinical_records_table

Revision ID: 1a4e7d0514e6
Revises: 00ccbb3c8a73
Create Date: 2026-06-17 19:26:55.169970

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '1a4e7d0514e6'
down_revision: Union[str, None] = '00ccbb3c8a73'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create clinical_records table
    op.create_table('clinical_records',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('patient_id', sa.Integer(), nullable=False),
    sa.Column('doctor_id', sa.Integer(), nullable=False),
    sa.Column('appointment_id', sa.Integer(), nullable=True),
    sa.Column('symptoms', sa.Text(), nullable=True),
    sa.Column('diagnosis', sa.Text(), nullable=True),
    sa.Column('treatment_plan', sa.Text(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.text('0')),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['appointment_id'], ['appointments.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['doctor_id'], ['doctors.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_clinical_records_id'), 'clinical_records', ['id'], unique=False)
    op.create_index(op.f('ix_clinical_records_patient_id'), 'clinical_records', ['patient_id'], unique=False)
    op.create_index(op.f('ix_clinical_records_doctor_id'), 'clinical_records', ['doctor_id'], unique=False)
    op.create_index(op.f('ix_clinical_records_appointment_id'), 'clinical_records', ['appointment_id'], unique=False)
    op.create_index(op.f('ix_clinical_records_is_deleted'), 'clinical_records', ['is_deleted'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_clinical_records_is_deleted'), table_name='clinical_records')
    op.drop_index(op.f('ix_clinical_records_appointment_id'), table_name='clinical_records')
    op.drop_index(op.f('ix_clinical_records_doctor_id'), table_name='clinical_records')
    op.drop_index(op.f('ix_clinical_records_patient_id'), table_name='clinical_records')
    op.drop_index(op.f('ix_clinical_records_id'), table_name='clinical_records')
    op.drop_table('clinical_records')
