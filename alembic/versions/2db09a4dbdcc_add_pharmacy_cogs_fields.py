"""add_pharmacy_cogs_fields

Revision ID: 2db09a4dbdcc
Revises: f9a8b7c6d5e4
Create Date: 2026-10-29 13:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '2db09a4dbdcc'
down_revision: Union[str, None] = 'f9a8b7c6d5e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add average_unit_cost to medicines
    op.add_column('medicines', sa.Column('average_unit_cost', sa.Float(), nullable=True))

    # 2. Add unit_cost and line_cost to pharmacy_invoice_items
    op.add_column('pharmacy_invoice_items', sa.Column('unit_cost', sa.Float(), nullable=True))
    op.add_column('pharmacy_invoice_items', sa.Column('line_cost', sa.Float(), nullable=True))

    # 3. Add unit_cost to pharmacy_return_items
    op.add_column('pharmacy_return_items', sa.Column('unit_cost', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('pharmacy_return_items', 'unit_cost')
    op.drop_column('pharmacy_invoice_items', 'line_cost')
    op.drop_column('pharmacy_invoice_items', 'unit_cost')
    op.drop_column('medicines', 'average_unit_cost')
