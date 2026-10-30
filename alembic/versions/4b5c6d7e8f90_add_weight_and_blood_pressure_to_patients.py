"""add weight and blood pressure to patients

Revision ID: 4b5c6d7e8f90
Revises: 2db09a4dbdcc
Create Date: 2026-10-30 13:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision: str = '4b5c6d7e8f90'
down_revision: Union[str, None] = '2db09a4dbdcc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    existing_columns = [col['name'] for col in inspector.get_columns('patients')]

    if 'weight' not in existing_columns:
        op.add_column('patients', sa.Column('weight', sa.Float(), nullable=True))

    if 'blood_pressure' not in existing_columns:
        op.add_column('patients', sa.Column('blood_pressure', sa.String(length=20), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    existing_columns = [col['name'] for col in inspector.get_columns('patients')]

    if 'blood_pressure' in existing_columns:
        op.drop_column('patients', 'blood_pressure')

    if 'weight' in existing_columns:
        op.drop_column('patients', 'weight')

