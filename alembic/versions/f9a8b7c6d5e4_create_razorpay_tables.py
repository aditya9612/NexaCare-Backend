"""create_razorpay_tables

Revision ID: f9a8b7c6d5e4
Revises: e3bd4423a766
Create Date: 2026-10-22 18:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f9a8b7c6d5e4'
down_revision: Union[str, None] = 'e3bd4423a766'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'razorpay_orders',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('hospital_id', sa.Integer(), nullable=True),
        sa.Column('bill_type', sa.String(length=50), nullable=False),
        sa.Column('bill_id', sa.Integer(), nullable=False),
        sa.Column('razorpay_order_id', sa.String(length=100), nullable=False),
        sa.Column('razorpay_payment_id', sa.String(length=100), nullable=True),
        sa.Column('amount_paise', sa.BigInteger(), nullable=False),
        sa.Column('amount_inr', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('currency', sa.String(length=10), nullable=False, server_default='INR'),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='created'),
        sa.Column('settled_amount_inr', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('excess_amount_inr', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('signature', sa.String(length=255), nullable=True),
        sa.Column('error_code', sa.String(length=100), nullable=True),
        sa.Column('error_reason', sa.Text(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['hospital_id'], ['hospitals.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_razorpay_orders_hospital_id'), 'razorpay_orders', ['hospital_id'], unique=False)
    op.create_index(op.f('ix_razorpay_orders_bill_type'), 'razorpay_orders', ['bill_type'], unique=False)
    op.create_index(op.f('ix_razorpay_orders_bill_id'), 'razorpay_orders', ['bill_id'], unique=False)
    op.create_index(op.f('ix_razorpay_orders_razorpay_order_id'), 'razorpay_orders', ['razorpay_order_id'], unique=True)
    op.create_index(op.f('ix_razorpay_orders_razorpay_payment_id'), 'razorpay_orders', ['razorpay_payment_id'], unique=False)
    op.create_index(op.f('ix_razorpay_orders_status'), 'razorpay_orders', ['status'], unique=False)

    op.create_table(
        'razorpay_webhook_events',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('event_id', sa.String(length=100), nullable=False),
        sa.Column('event_type', sa.String(length=100), nullable=False),
        sa.Column('payload', sa.Text(), nullable=True),
        sa.Column('processed', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column('processed_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_razorpay_webhook_events_event_id'), 'razorpay_webhook_events', ['event_id'], unique=True)
    op.create_index(op.f('ix_razorpay_webhook_events_event_type'), 'razorpay_webhook_events', ['event_type'], unique=False)
    op.create_index(op.f('ix_razorpay_webhook_events_processed'), 'razorpay_webhook_events', ['processed'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_razorpay_webhook_events_processed'), table_name='razorpay_webhook_events')
    op.drop_index(op.f('ix_razorpay_webhook_events_event_type'), table_name='razorpay_webhook_events')
    op.drop_index(op.f('ix_razorpay_webhook_events_event_id'), table_name='razorpay_webhook_events')
    op.drop_table('razorpay_webhook_events')

    op.drop_index(op.f('ix_razorpay_orders_status'), table_name='razorpay_orders')
    op.drop_index(op.f('ix_razorpay_orders_razorpay_payment_id'), table_name='razorpay_orders')
    op.drop_index(op.f('ix_razorpay_orders_razorpay_order_id'), table_name='razorpay_orders')
    op.drop_index(op.f('ix_razorpay_orders_bill_id'), table_name='razorpay_orders')
    op.drop_index(op.f('ix_razorpay_orders_bill_type'), table_name='razorpay_orders')
    op.drop_index(op.f('ix_razorpay_orders_hospital_id'), table_name='razorpay_orders')
    op.drop_table('razorpay_orders')
