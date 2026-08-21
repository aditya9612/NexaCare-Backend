"""add_lab_ocr_extractions_table

Revision ID: 19166eac062a
Revises: e2d7635c10aa
Create Date: 2026-08-18 14:04:03.551225

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



revision: str = '19166eac062a'
down_revision: Union[str, None] = 'e2d7635c10aa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'lab_ocr_extractions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('test_order_id', sa.Integer(), nullable=False),
        sa.Column('patient_id', sa.Integer(), nullable=True),
        sa.Column('report_id', sa.Integer(), nullable=True),
        sa.Column('extracted_patient_code', sa.String(length=50), nullable=True),
        sa.Column('extracted_first_name', sa.String(length=100), nullable=True),
        sa.Column('extracted_last_name', sa.String(length=100), nullable=True),
        sa.Column('file_path', sa.String(length=500), nullable=False),
        sa.Column('raw_ocr_text', sa.Text(), nullable=True),
        sa.Column('extracted_json', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='processed'),
        sa.Column('model_used', sa.String(length=100), nullable=True),
        sa.Column('extracted_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.ForeignKeyConstraint(['extracted_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['report_id'], ['lab_reports.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['test_order_id'], ['test_orders.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_lab_ocr_extractions_id'), 'lab_ocr_extractions', ['id'], unique=False)
    op.create_index(op.f('ix_lab_ocr_extractions_test_order_id'), 'lab_ocr_extractions', ['test_order_id'], unique=False)
    op.create_index(op.f('ix_lab_ocr_extractions_patient_id'), 'lab_ocr_extractions', ['patient_id'], unique=False)
    op.create_index(op.f('ix_lab_ocr_extractions_report_id'), 'lab_ocr_extractions', ['report_id'], unique=False)
    op.create_index(op.f('ix_lab_ocr_extractions_extracted_patient_code'), 'lab_ocr_extractions', ['extracted_patient_code'], unique=False)
    op.create_index(op.f('ix_lab_ocr_extractions_status'), 'lab_ocr_extractions', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_lab_ocr_extractions_status'), table_name='lab_ocr_extractions')
    op.drop_index(op.f('ix_lab_ocr_extractions_extracted_patient_code'), table_name='lab_ocr_extractions')
    op.drop_index(op.f('ix_lab_ocr_extractions_report_id'), table_name='lab_ocr_extractions')
    op.drop_index(op.f('ix_lab_ocr_extractions_patient_id'), table_name='lab_ocr_extractions')
    op.drop_index(op.f('ix_lab_ocr_extractions_test_order_id'), table_name='lab_ocr_extractions')
    op.drop_index(op.f('ix_lab_ocr_extractions_id'), table_name='lab_ocr_extractions')
    op.drop_table('lab_ocr_extractions')

