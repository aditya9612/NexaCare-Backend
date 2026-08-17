"""
app/ai/embeddings — OpenAI embedding generation and MySQL/Redis persistence.

Public exports:
- EmbeddingService: calls OpenAI text-embedding-3-small
- EmbeddingStore: upsert/load vectors for FAQ RAG

Integration: used only by FAQ RAG (KnowledgeRetriever, HospitalKnowledgeService sync).
Does not touch booking, appointments, Twilio, or Gemini.
"""

from app.ai.embeddings.service import EmbeddingService
from app.ai.embeddings.store import EmbeddingStore, build_embed_text, content_hash

__all__ = [
    "EmbeddingService",
    "EmbeddingStore",
    "build_embed_text",
    "content_hash",
]
