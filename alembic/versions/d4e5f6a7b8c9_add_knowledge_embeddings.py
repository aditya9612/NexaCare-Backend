"""Add knowledge_embeddings table for FAQ RAG Phase 1

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-08-06 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "knowledge_embeddings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("hospital_id", sa.Integer(), sa.ForeignKey("hospitals.id"), nullable=False),
        sa.Column("source_type", sa.String(length=20), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(length=10), nullable=False, server_default="en"),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("embedding_model", sa.String(length=100), nullable=False),
        sa.Column("embedding", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("source_type", "source_id", name="uq_knowledge_embeddings_source"),
    )
    op.create_index("ix_knowledge_embeddings_id", "knowledge_embeddings", ["id"])
    op.create_index("ix_knowledge_embeddings_hospital_id", "knowledge_embeddings", ["hospital_id"])
    op.create_index("ix_knowledge_embeddings_source_type", "knowledge_embeddings", ["source_type"])
    op.create_index("ix_knowledge_embeddings_source_id", "knowledge_embeddings", ["source_id"])
    op.create_index("ix_knowledge_embeddings_language", "knowledge_embeddings", ["language"])
    op.create_index("ix_knowledge_embeddings_content_hash", "knowledge_embeddings", ["content_hash"])
    op.create_index("ix_knowledge_embeddings_is_active", "knowledge_embeddings", ["is_active"])


def downgrade() -> None:
    op.drop_table("knowledge_embeddings")
