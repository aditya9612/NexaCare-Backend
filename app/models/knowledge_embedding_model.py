"""
Knowledge embedding persistence for FAQ RAG (Phase 1).

Stores OpenAI text-embedding-3-small vectors for every FAQ, policy, and
hospital voice document. Source of truth remains MySQL KB tables; this table
holds vectors only.

Integration:
- Written by app.ai.embeddings.store.EmbeddingStore on KB CRUD / lazy backfill
- Read by app.ai.rag.retriever.KnowledgeRetriever for Top-5 cosine retrieval
- Must not be used by booking, appointment, or Gemini booking paths
"""

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin


class KnowledgeEmbedding(Base, TimestampMixin):
    """One embedding row per KB source (faq | policy | document)."""

    __tablename__ = "knowledge_embeddings"
    __table_args__ = (
        UniqueConstraint("source_type", "source_id", name="uq_knowledge_embeddings_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    hospital_id: Mapped[int] = mapped_column(ForeignKey("hospitals.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(20), index=True)  # faq | policy | document
    source_id: Mapped[int] = mapped_column(Integer, index=True)
    language: Mapped[str] = mapped_column(String(10), default="en", index=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    embedding_model: Mapped[str] = mapped_column(String(100))
    embedding: Mapped[str] = mapped_column(Text)  # JSON-encoded list[float]
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
