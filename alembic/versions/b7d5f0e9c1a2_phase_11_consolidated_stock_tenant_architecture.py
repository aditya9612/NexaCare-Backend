"""phase 11 consolidated stock tenant architecture

Revision ID: b7d5f0e9c1a2
Revises: 7f9a1b2c3d4e
Create Date: 2026-08-26 15:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b7d5f0e9c1a2'
down_revision: Union[str, None] = '7f9a1b2c3d4e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # --- PHASE 1 ---
    op.add_column('medicines', sa.Column('inventory_item_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_medicines_inventory_item_id'), 'medicines', ['inventory_item_id'], unique=False)
    op.create_foreign_key('fk_medicines_inventory_item', 'medicines', 'inventory_items', ['inventory_item_id'], ['id'])

    op.add_column('suppliers', sa.Column('vendor_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_suppliers_vendor_id'), 'suppliers', ['vendor_id'], unique=False)
    op.create_foreign_key('fk_suppliers_vendor', 'suppliers', 'vendors', ['vendor_id'], ['id'])

    # --- PHASE 2 ---
    op.create_table('item_batches',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('inventory_item_id', sa.Integer(), nullable=False),
        sa.Column('batch_number', sa.String(length=100), nullable=True),
        sa.Column('expiry_date', sa.Date(), nullable=True),
        sa.Column('manufacturing_date', sa.Date(), nullable=True),
        sa.Column('purchase_price', sa.Float(), nullable=True),
        sa.Column('mrp', sa.Float(), nullable=True),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['inventory_item_id'], ['inventory_items.id'], name="fk_item_batches_inv_item"),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_item_batches_batch_number'), 'item_batches', ['batch_number'], unique=False)
    op.create_index(op.f('ix_item_batches_created_at'), 'item_batches', ['created_at'], unique=False)
    op.create_index(op.f('ix_item_batches_expiry_date'), 'item_batches', ['expiry_date'], unique=False)
    op.create_index(op.f('ix_item_batches_id'), 'item_batches', ['id'], unique=False)
    op.create_index(op.f('ix_item_batches_inventory_item_id'), 'item_batches', ['inventory_item_id'], unique=False)

    op.create_table('warehouse_stock',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('warehouse_id', sa.Integer(), nullable=False),
        sa.Column('inventory_item_id', sa.Integer(), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['inventory_item_id'], ['inventory_items.id'], name="fk_warehouse_stock_inv_item"),
        sa.ForeignKeyConstraint(['warehouse_id'], ['warehouses.id'], name="fk_warehouse_stock_warehouse"),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_warehouse_stock_created_at'), 'warehouse_stock', ['created_at'], unique=False)
    op.create_index(op.f('ix_warehouse_stock_id'), 'warehouse_stock', ['id'], unique=False)
    op.create_index(op.f('ix_warehouse_stock_inventory_item_id'), 'warehouse_stock', ['inventory_item_id'], unique=False)
    op.create_index(op.f('ix_warehouse_stock_warehouse_id'), 'warehouse_stock', ['warehouse_id'], unique=False)

    # --- PHASE 3 ---
    op.add_column('stock_transactions', sa.Column('batch_id', sa.Integer(), nullable=True))
    op.add_column('stock_transactions', sa.Column('direction', sa.String(length=10), nullable=True))
    op.add_column('stock_transactions', sa.Column('balance_before', sa.Integer(), nullable=True))
    op.add_column('stock_transactions', sa.Column('balance_after', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_stock_transactions_batch_id'), 'stock_transactions', ['batch_id'], unique=False)
    op.create_foreign_key('fk_stock_tx_batch', 'stock_transactions', 'item_batches', ['batch_id'], ['id'])

    # --- PHASE 11.7 ---
    op.add_column('warehouses', sa.Column('hospital_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_warehouses_hospital_id_hospitals', 'warehouses', 'hospitals', ['hospital_id'], ['id'], ondelete='SET NULL')

    op.add_column('purchases', sa.Column('hospital_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_purchases_hospital_id_hospitals', 'purchases', 'hospitals', ['hospital_id'], ['id'], ondelete='SET NULL')

    op.add_column('prescriptions', sa.Column('hospital_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_prescriptions_hospital_id_hospitals', 'prescriptions', 'hospitals', ['hospital_id'], ['id'], ondelete='SET NULL')

    op.add_column('pharmacy_invoices', sa.Column('hospital_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_pharmacy_invoices_hospital_id_hospitals', 'pharmacy_invoices', 'hospitals', ['hospital_id'], ['id'], ondelete='SET NULL')

    # --- PHASE 11.26 ---
    op.drop_index('ix_warehouses_code', table_name='warehouses')
    op.create_index('ix_warehouses_code', 'warehouses', ['code'], unique=False)

    # --- PHASE 11.28 ---
    op.create_unique_constraint(
        'uq_warehouse_item',
        'warehouse_stock',
        ['warehouse_id', 'inventory_item_id']
    )


def downgrade() -> None:

    # --- PHASE 11.28 ---
    op.drop_constraint(
        'uq_warehouse_item',
        'warehouse_stock',
        type_='unique'
    )

    # --- PHASE 11.26 ---
    op.drop_index('ix_warehouses_code', table_name='warehouses')
    op.create_index('ix_warehouses_code', 'warehouses', ['code'], unique=True)

    # --- PHASE 11.7 ---
    op.drop_constraint('fk_pharmacy_invoices_hospital_id_hospitals', 'pharmacy_invoices', type_='foreignkey')
    op.drop_column('pharmacy_invoices', 'hospital_id')

    op.drop_constraint('fk_prescriptions_hospital_id_hospitals', 'prescriptions', type_='foreignkey')
    op.drop_column('prescriptions', 'hospital_id')

    op.drop_constraint('fk_purchases_hospital_id_hospitals', 'purchases', type_='foreignkey')
    op.drop_column('purchases', 'hospital_id')

    op.drop_constraint('fk_warehouses_hospital_id_hospitals', 'warehouses', type_='foreignkey')
    op.drop_column('warehouses', 'hospital_id')

    # --- PHASE 3 ---
    op.drop_constraint('fk_stock_tx_batch', 'stock_transactions', type_='foreignkey')
    op.drop_index(op.f('ix_stock_transactions_batch_id'), table_name='stock_transactions')
    op.drop_column('stock_transactions', 'balance_after')
    op.drop_column('stock_transactions', 'balance_before')
    op.drop_column('stock_transactions', 'direction')
    op.drop_column('stock_transactions', 'batch_id')

    # --- PHASE 2 ---
    op.drop_table('warehouse_stock')
    op.drop_table('item_batches')

    # --- PHASE 1 ---
    op.drop_constraint('fk_suppliers_vendor', 'suppliers', type_='foreignkey')
    op.drop_index(op.f('ix_suppliers_vendor_id'), table_name='suppliers')
    op.drop_column('suppliers', 'vendor_id')

    op.drop_constraint('fk_medicines_inventory_item', 'medicines', type_='foreignkey')
    op.drop_index(op.f('ix_medicines_inventory_item_id'), table_name='medicines')
    op.drop_column('medicines', 'inventory_item_id')
