"""add_admission_recommendation_fields_to_appointments

Revision ID: 56422ffac90d
Revises: f7a1c2d3e4b5
Create Date: 2026-08-21 16:35:10.734091

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '56422ffac90d'
down_revision: Union[str, None] = 'f7a1c2d3e4b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('appointments', sa.Column('admission_status', sa.String(length=50), nullable=True))
    op.create_index(op.f('ix_appointments_admission_status'), 'appointments', ['admission_status'], unique=False)
    op.add_column('appointments', sa.Column('admission_recommended', sa.Boolean(), server_default=sa.text('0'), nullable=False))
    op.add_column('appointments', sa.Column('admission_reason', sa.Text(), nullable=True))
    op.add_column('appointments', sa.Column('expected_los', sa.Integer(), nullable=True))
    op.add_column('appointments', sa.Column('recommended_ward', sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column('appointments', 'recommended_ward')
    op.drop_column('appointments', 'expected_los')
    op.drop_column('appointments', 'admission_reason')
    op.drop_column('appointments', 'admission_recommended')
    op.drop_index(op.f('ix_appointments_admission_status'), table_name='appointments')
    op.drop_column('appointments', 'admission_status')

