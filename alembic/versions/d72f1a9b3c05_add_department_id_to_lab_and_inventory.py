"""add_department_id_to_lab_and_inventory

Revision ID: d72f1a9b3c05
Revises: c91f3e8d2a01
Create Date: 2026-05-27 19:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd72f1a9b3c05'
down_revision: Union[str, None] = 'c91f3e8d2a01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add department_id to lab_tests
    op.add_column('lab_tests', sa.Column(
        'department_id', sa.Integer(), nullable=True
    ))
    op.create_index('ix_lab_tests_department_id', 'lab_tests', ['department_id'], unique=False)
    op.create_foreign_key(
        'fk_lab_tests_department_id', 'lab_tests',
        'departments', ['department_id'], ['department_id']
    )

    # Add department_id to test_orders
    op.add_column('test_orders', sa.Column(
        'department_id', sa.Integer(), nullable=True
    ))
    op.create_index('ix_test_orders_department_id', 'test_orders', ['department_id'], unique=False)
    op.create_foreign_key(
        'fk_test_orders_department_id', 'test_orders',
        'departments', ['department_id'], ['department_id']
    )

    # Add department_id to inventory_items
    op.add_column('inventory_items', sa.Column(
        'department_id', sa.Integer(), nullable=True
    ))
    op.create_index('ix_inventory_items_department_id', 'inventory_items', ['department_id'], unique=False)
    op.create_foreign_key(
        'fk_inventory_items_department_id', 'inventory_items',
        'departments', ['department_id'], ['department_id']
    )


def downgrade() -> None:
    # Remove from inventory_items
    op.drop_constraint('fk_inventory_items_department_id', 'inventory_items', type_='foreignkey')
    op.drop_index('ix_inventory_items_department_id', table_name='inventory_items')
    op.drop_column('inventory_items', 'department_id')

    # Remove from test_orders
    op.drop_constraint('fk_test_orders_department_id', 'test_orders', type_='foreignkey')
    op.drop_index('ix_test_orders_department_id', table_name='test_orders')
    op.drop_column('test_orders', 'department_id')

    # Remove from lab_tests
    op.drop_constraint('fk_lab_tests_department_id', 'lab_tests', type_='foreignkey')
    op.drop_index('ix_lab_tests_department_id', table_name='lab_tests')
    op.drop_column('lab_tests', 'department_id')
