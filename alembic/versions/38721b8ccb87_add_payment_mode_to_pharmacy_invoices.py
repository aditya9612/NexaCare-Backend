"""add payment_mode to pharmacy_invoices

Revision ID: 38721b8ccb87
Revises: 7184a260df5c
Create Date: 2026-07-18 18:37:50.400059

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



revision: str = '38721b8ccb87'
down_revision: Union[str, None] = '7184a260df5c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('pharmacy_invoices', sa.Column('payment_mode', sa.String(length=50), nullable=True, server_default='Cash'))


def downgrade() -> None:
    op.drop_column('pharmacy_invoices', 'payment_mode')

