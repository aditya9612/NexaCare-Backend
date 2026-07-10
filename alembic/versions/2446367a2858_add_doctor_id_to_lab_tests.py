"""add_doctor_id_to_lab_tests

Revision ID: 2446367a2858
Revises: f9bdc8e26d36
Create Date: 2026-07-08 17:05:30.301698

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '2446367a2858'
down_revision: Union[str, None] = 'f9bdc8e26d36'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('lab_tests', sa.Column('doctor_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_lab_tests_doctor_id'), 'lab_tests', ['doctor_id'], unique=False)
    op.create_foreign_key('fk_lab_tests_doctor_id', 'lab_tests', 'doctors', ['doctor_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_lab_tests_doctor_id', 'lab_tests', type_='foreignkey')
    op.drop_index(op.f('ix_lab_tests_doctor_id'), table_name='lab_tests')
    op.drop_column('lab_tests', 'doctor_id')
