"""add_nurse_communication_tables

Revision ID: b340001aad77
Revises: beca753eae5d
Create Date: 2026-07-31 15:30:27.613004

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b340001aad77'
down_revision: Union[str, None] = 'beca753eae5d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Safe cleanup of any partial tables
    op.execute("SET FOREIGN_KEY_CHECKS = 0;")
    op.execute("DROP TABLE IF EXISTS emergency_alerts;")
    op.execute("DROP TABLE IF EXISTS patient_emergency_alerts;")
    op.execute("DROP TABLE IF EXISTS patient_updates;")
    op.execute("SET FOREIGN_KEY_CHECKS = 1;")

    # 1. Create table emergency_alerts
    op.create_table(
        'emergency_alerts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('patient_id', sa.Integer(), nullable=False),
        sa.Column('nurse_id', sa.Integer(), nullable=False),
        sa.Column('emergency_type', sa.String(length=100), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['nurse_id'], ['nurses.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_emergency_alerts_created_at'), 'emergency_alerts', ['created_at'], unique=False)
    op.create_index(op.f('ix_emergency_alerts_emergency_type'), 'emergency_alerts', ['emergency_type'], unique=False)
    op.create_index(op.f('ix_emergency_alerts_id'), 'emergency_alerts', ['id'], unique=False)
    op.create_index(op.f('ix_emergency_alerts_nurse_id'), 'emergency_alerts', ['nurse_id'], unique=False)
    op.create_index(op.f('ix_emergency_alerts_patient_id'), 'emergency_alerts', ['patient_id'], unique=False)

    # 2. Create table patient_updates
    op.create_table(
        'patient_updates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('patient_id', sa.Integer(), nullable=False),
        sa.Column('nurse_id', sa.Integer(), nullable=False),
        sa.Column('update_type', sa.String(length=100), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('severity', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['nurse_id'], ['nurses.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_patient_updates_created_at'), 'patient_updates', ['created_at'], unique=False)
    op.create_index(op.f('ix_patient_updates_id'), 'patient_updates', ['id'], unique=False)
    op.create_index(op.f('ix_patient_updates_nurse_id'), 'patient_updates', ['nurse_id'], unique=False)
    op.create_index(op.f('ix_patient_updates_patient_id'), 'patient_updates', ['patient_id'], unique=False)
    op.create_index(op.f('ix_patient_updates_severity'), 'patient_updates', ['severity'], unique=False)
    op.create_index(op.f('ix_patient_updates_update_type'), 'patient_updates', ['update_type'], unique=False)

    # 3. Index update for purchases table
    try:
        op.drop_index('idx_purchases_is_deleted', table_name='purchases')
    except Exception:
        pass

    try:
        op.create_index(op.f('ix_purchases_is_deleted'), 'purchases', ['is_deleted'], unique=False)
    except Exception:
        pass

    # 4. Add created_by column to test_orders
    op.add_column(
        'test_orders',
        sa.Column('created_by', sa.Integer(), nullable=True)
    )

    op.create_foreign_key(
        'fk_test_orders_created_by',
        'test_orders',
        'users',
        ['created_by'],
        ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    # Remove created_by from test_orders
    op.drop_constraint(
        'fk_test_orders_created_by',
        'test_orders',
        type_='foreignkey'
    )
    op.drop_column('test_orders', 'created_by')

    try:
        op.drop_index(op.f('ix_purchases_is_deleted'), table_name='purchases')
    except Exception:
        pass

    try:
        op.create_index('idx_purchases_is_deleted', 'purchases', ['is_deleted'], unique=False)
    except Exception:
        pass

    op.drop_index(op.f('ix_patient_updates_update_type'), table_name='patient_updates')
    op.drop_index(op.f('ix_patient_updates_severity'), table_name='patient_updates')
    op.drop_index(op.f('ix_patient_updates_patient_id'), table_name='patient_updates')
    op.drop_index(op.f('ix_patient_updates_nurse_id'), table_name='patient_updates')
    op.drop_index(op.f('ix_patient_updates_id'), table_name='patient_updates')
    op.drop_index(op.f('ix_patient_updates_created_at'), table_name='patient_updates')
    op.drop_table('patient_updates')

    op.drop_index(op.f('ix_emergency_alerts_patient_id'), table_name='emergency_alerts')
    op.drop_index(op.f('ix_emergency_alerts_nurse_id'), table_name='emergency_alerts')
    op.drop_index(op.f('ix_emergency_alerts_id'), table_name='emergency_alerts')
    op.drop_index(op.f('ix_emergency_alerts_emergency_type'), table_name='emergency_alerts')
    op.drop_index(op.f('ix_emergency_alerts_created_at'), table_name='emergency_alerts')
    op.drop_table('emergency_alerts')