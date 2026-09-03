"""add hospital voice document chunks

Revision ID: 1348df73b94e
Revises: b7d5f0e9c1a2
Create Date: 2026-09-01 21:50:05.208654

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



revision: str = '1348df73b94e'
down_revision: Union[str, None] = 'b7d5f0e9c1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'hospital_voice_document_chunks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('document_id', sa.Integer(), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('page_number', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['hospital_voice_documents.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_hospital_voice_document_chunks_id'), 'hospital_voice_document_chunks', ['id'], unique=False)
    op.create_index(op.f('ix_hospital_voice_document_chunks_document_id'), 'hospital_voice_document_chunks', ['document_id'], unique=False)
    op.create_index(op.f('ix_hospital_voice_document_chunks_chunk_index'), 'hospital_voice_document_chunks', ['chunk_index'], unique=False)
    op.create_index(op.f('ix_hospital_voice_document_chunks_created_at'), 'hospital_voice_document_chunks', ['created_at'], unique=False)

def downgrade() -> None:
    # MySQL does not allow dropping an index used by a FK constraint without dropping the FK first.
    # Since we are dropping the entire table, simply dropping the table is sufficient and drops indexes.
    op.drop_table('hospital_voice_document_chunks')
