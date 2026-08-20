"""add_lab_ocr_extraction_items_table

Revision ID: 46bfa1804b10
Revises: 19166eac062a
Create Date: 2026-08-18 15:21:15.619298

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



revision: str = '46bfa1804b10'
down_revision: Union[str, None] = '19166eac062a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create lab_ocr_extraction_items table
    op.create_table(
        'lab_ocr_extraction_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ocr_extraction_id', sa.Integer(), nullable=False),
        sa.Column('parameter_name', sa.String(length=255), nullable=False),
        sa.Column('result_value', sa.String(length=255), nullable=True),
        sa.Column('normal_range', sa.String(length=255), nullable=True),
        sa.Column('unit', sa.String(length=50), nullable=True),
        sa.Column('remarks', sa.String(length=500), nullable=True),
        sa.Column('is_matched_catalog', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.ForeignKeyConstraint(['ocr_extraction_id'], ['lab_ocr_extractions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_lab_ocr_extraction_items_id'), 'lab_ocr_extraction_items', ['id'], unique=False)
    op.create_index(op.f('ix_lab_ocr_extraction_items_ocr_extraction_id'), 'lab_ocr_extraction_items', ['ocr_extraction_id'], unique=False)
    op.create_index(op.f('ix_lab_ocr_extraction_items_parameter_name'), 'lab_ocr_extraction_items', ['parameter_name'], unique=False)
    op.create_index(op.f('ix_lab_ocr_extraction_items_status'), 'lab_ocr_extraction_items', ['status'], unique=False)

    # 2. Drop raw_ocr_text and extracted_json from lab_ocr_extractions
    try:
        op.drop_column('lab_ocr_extractions', 'raw_ocr_text')
    except Exception:
        pass
    try:
        op.drop_column('lab_ocr_extractions', 'extracted_json')
    except Exception:
        pass


def downgrade() -> None:
    op.add_column('lab_ocr_extractions', sa.Column('extracted_json', sa.JSON(), nullable=True))
    op.add_column('lab_ocr_extractions', sa.Column('raw_ocr_text', sa.Text(), nullable=True))
    op.drop_index(op.f('ix_lab_ocr_extraction_items_status'), table_name='lab_ocr_extraction_items')
    op.drop_index(op.f('ix_lab_ocr_extraction_items_parameter_name'), table_name='lab_ocr_extraction_items')
    op.drop_index(op.f('ix_lab_ocr_extraction_items_ocr_extraction_id'), table_name='lab_ocr_extraction_items')
    op.drop_index(op.f('ix_lab_ocr_extraction_items_id'), table_name='lab_ocr_extraction_items')
    op.drop_table('lab_ocr_extraction_items')

