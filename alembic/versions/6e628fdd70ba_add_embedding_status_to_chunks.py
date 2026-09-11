"""add_embedding_status_to_chunks

Revision ID: 6e628fdd70ba
Revises: 1348df73b94e
Create Date: 2026-09-02 11:07:34.834118

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '6e628fdd70ba'
down_revision: Union[str, None] = '1348df73b94e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('hospital_voice_document_chunks', sa.Column('embedding_status', sa.String(length=50), server_default='pending', nullable=False))
    op.create_index(op.f('ix_hospital_voice_document_chunks_embedding_status'), 'hospital_voice_document_chunks', ['embedding_status'], unique=False)
    op.add_column('hospital_voice_document_chunks', sa.Column('embedding_error', sa.Text(), nullable=True))

def downgrade() -> None:
    op.drop_column('hospital_voice_document_chunks', 'embedding_error')
    op.drop_index(op.f('ix_hospital_voice_document_chunks_embedding_status'), table_name='hospital_voice_document_chunks')
    op.drop_column('hospital_voice_document_chunks', 'embedding_status')
