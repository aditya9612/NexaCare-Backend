"""add_pharmacy_cogs_fields and patient vitals

Revision ID: 2db09a4dbdcc
Revises: b4c5d6e7f8a9
Create Date: 2026-10-29 13:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision: str = '2db09a4dbdcc'
down_revision: Union[str, None] = 'b4c5d6e7f8a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)

    # 1. Add average_unit_cost to medicines
    med_cols = [col['name'] for col in inspector.get_columns('medicines')]
    if 'average_unit_cost' not in med_cols:
        op.add_column('medicines', sa.Column('average_unit_cost', sa.Float(), nullable=True))

    # 2. Add unit_cost and line_cost to pharmacy_invoice_items
    inv_item_cols = [col['name'] for col in inspector.get_columns('pharmacy_invoice_items')]
    if 'unit_cost' not in inv_item_cols:
        op.add_column('pharmacy_invoice_items', sa.Column('unit_cost', sa.Float(), nullable=True))
    if 'line_cost' not in inv_item_cols:
        op.add_column('pharmacy_invoice_items', sa.Column('line_cost', sa.Float(), nullable=True))

    # 3. Add unit_cost to pharmacy_return_items
    ret_item_cols = [col['name'] for col in inspector.get_columns('pharmacy_return_items')]
    if 'unit_cost' not in ret_item_cols:
        op.add_column('pharmacy_return_items', sa.Column('unit_cost', sa.Float(), nullable=True))

    # 4. Add weight and blood_pressure to patients
    patient_cols = [col['name'] for col in inspector.get_columns('patients')]
    if 'weight' not in patient_cols:
        op.add_column('patients', sa.Column('weight', sa.Float(), nullable=True))
    if 'blood_pressure' not in patient_cols:
        op.add_column('patients', sa.Column('blood_pressure', sa.String(length=20), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)

    patient_cols = [col['name'] for col in inspector.get_columns('patients')]
    if 'blood_pressure' in patient_cols:
        op.drop_column('patients', 'blood_pressure')
    if 'weight' in patient_cols:
        op.drop_column('patients', 'weight')

    ret_item_cols = [col['name'] for col in inspector.get_columns('pharmacy_return_items')]
    if 'unit_cost' in ret_item_cols:
        op.drop_column('pharmacy_return_items', 'unit_cost')

    inv_item_cols = [col['name'] for col in inspector.get_columns('pharmacy_invoice_items')]
    if 'line_cost' in inv_item_cols:
        op.drop_column('pharmacy_invoice_items', 'line_cost')
    if 'unit_cost' in inv_item_cols:
        op.drop_column('pharmacy_invoice_items', 'unit_cost')

    med_cols = [col['name'] for col in inspector.get_columns('medicines')]
    if 'average_unit_cost' in med_cols:
        op.drop_column('medicines', 'average_unit_cost')
