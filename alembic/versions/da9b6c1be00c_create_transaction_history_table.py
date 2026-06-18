"""create_transaction_history_table

Revision ID: da9b6c1be00c
Revises: dec36816e434
Create Date: 2026-06-16 17:36:07.808109

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'da9b6c1be00c'
down_revision: Union[str, None] = 'dec36816e434'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'transaction_history',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('reference_no', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('amount', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='completed'),
        sa.Column('source_module', sa.String(length=50), nullable=False),
        sa.Column('source_id', sa.Integer(), nullable=False),
        sa.Column('event_date', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_transaction_history_id'), 'transaction_history', ['id'], unique=False)
    op.create_index(op.f('ix_transaction_history_event_type'), 'transaction_history', ['event_type'], unique=False)
    op.create_index(op.f('ix_transaction_history_reference_no'), 'transaction_history', ['reference_no'], unique=False)
    op.create_index(op.f('ix_transaction_history_status'), 'transaction_history', ['status'], unique=False)
    op.create_index(op.f('ix_transaction_history_source_module'), 'transaction_history', ['source_module'], unique=False)
    op.create_index(op.f('ix_transaction_history_source_id'), 'transaction_history', ['source_id'], unique=False)
    op.create_index(op.f('ix_transaction_history_event_date'), 'transaction_history', ['event_date'], unique=False)


def downgrade() -> None:
    op.drop_table('transaction_history')
