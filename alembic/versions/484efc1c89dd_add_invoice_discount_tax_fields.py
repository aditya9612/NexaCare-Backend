"""add_invoice_discount_tax_fields

Revision ID: 484efc1c89dd
Revises: 2f49ae75d53f
Create Date: 2026-06-29 15:24:03.808399

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



revision: str = '484efc1c89dd'
down_revision: Union[str, None] = '2f49ae75d53f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("pharmacy_invoices", sa.Column("discount_percentage", sa.Float(), nullable=True))
    op.add_column("pharmacy_invoices", sa.Column("tax_percentage", sa.Float(), nullable=True))
    op.add_column("pharmacy_invoices", sa.Column("tax_amount", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("pharmacy_invoices", "tax_amount")
    op.drop_column("pharmacy_invoices", "tax_percentage")
    op.drop_column("pharmacy_invoices", "discount_percentage")
