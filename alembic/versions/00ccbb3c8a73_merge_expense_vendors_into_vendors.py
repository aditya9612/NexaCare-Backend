"""merge_expense_vendors_into_vendors

Revision ID: 00ccbb3c8a73
Revises: 78d4171aff88
Create Date: 2026-06-17 15:06:05.740670

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '00ccbb3c8a73'
down_revision: Union[str, None] = '78d4171aff88'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop foreign key constraints pointing to expense_vendors if they exist
    for fk_name, table in [("expenses_ibfk_2", "expenses"), ("vendor_payments_ibfk_2", "vendor_payments")]:
        try:
            op.drop_constraint(fk_name, table, type_='foreignkey')
        except Exception:
            pass

    # Drop index and table expense_vendors
    try:
        op.drop_index('ix_expense_vendors_created_at', table_name='expense_vendors')
        op.drop_index('ix_expense_vendors_id', table_name='expense_vendors')
        op.drop_index('ix_expense_vendors_is_deleted', table_name='expense_vendors')
        op.drop_index('ix_expense_vendors_name', table_name='expense_vendors')
    except Exception:
        pass
        
    try:
        op.drop_table('expense_vendors')
    except Exception:
        pass

    # Add vendor_type and service_type columns to vendors
    op.add_column('vendors', sa.Column('vendor_type', sa.String(length=50), nullable=False, server_default='inventory'))
    op.add_column('vendors', sa.Column('service_type', sa.String(length=100), nullable=True))
    op.create_index(op.f('ix_vendors_vendor_type'), 'vendors', ['vendor_type'], unique=False)

    # Create new foreign keys pointing to vendors.id
    try:
        op.create_foreign_key('expenses_ibfk_2', 'expenses', 'vendors', ['vendor_id'], ['id'], ondelete='SET NULL')
    except Exception:
        pass
    try:
        op.create_foreign_key('vendor_payments_ibfk_2', 'vendor_payments', 'vendors', ['vendor_id'], ['id'], ondelete='CASCADE')
    except Exception:
        pass


def downgrade() -> None:
    # Drop foreign key constraints pointing to vendors on expenses and vendor_payments
    for fk_name, table in [("expenses_ibfk_2", "expenses"), ("vendor_payments_ibfk_2", "vendor_payments")]:
        try:
            op.drop_constraint(fk_name, table, type_='foreignkey')
        except Exception:
            pass

    # Drop index and columns from vendors
    op.drop_index(op.f('ix_vendors_vendor_type'), table_name='vendors')
    op.drop_column('vendors', 'service_type')
    op.drop_column('vendors', 'vendor_type')

    # Recreate expense_vendors table
    op.create_table('expense_vendors',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('contact', sa.String(length=20), nullable=True),
    sa.Column('service_type', sa.String(length=100), nullable=True),
    sa.Column('email', sa.String(length=255), nullable=True),
    sa.Column('address', sa.String(length=500), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('is_deleted', sa.Boolean(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_expense_vendors_name'), 'expense_vendors', ['name'], unique=True)
    op.create_index(op.f('ix_expense_vendors_is_deleted'), 'expense_vendors', ['is_deleted'], unique=False)
    op.create_index(op.f('ix_expense_vendors_id'), 'expense_vendors', ['id'], unique=False)
    op.create_index(op.f('ix_expense_vendors_created_at'), 'expense_vendors', ['created_at'], unique=False)

    # Recreate foreign keys pointing to expense_vendors
    try:
        op.create_foreign_key('expenses_ibfk_2', 'expenses', 'expense_vendors', ['vendor_id'], ['id'], ondelete='SET NULL')
    except Exception:
        pass
    try:
        op.create_foreign_key('vendor_payments_ibfk_2', 'vendor_payments', 'expense_vendors', ['vendor_id'], ['id'], ondelete='CASCADE')
    except Exception:
        pass
