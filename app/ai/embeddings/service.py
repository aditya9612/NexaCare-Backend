"""
EmbeddingService — OpenAI text-embedding-3-small client.

Integration points:
- Called by EmbeddingStore.upsert_entry / KnowledgeRetriever (query embed)
- Requires settings.OPENAI_API_KEY; returns empty list on missing key / API error
- Must not be used for booking NLU (Gemini path stays untouched)
"""

from __future__ import annotations

from typing import Sequence

from app.core.config import settings
from app.core.logger import logger


class EmbeddingUnavailableError(Exception):
    """Raised when OpenAI embedding API is unavailable for non-empty input."""


class EmbeddingService:
    """Generate dense vectors via OpenAI embeddings API."""

    def __init__(self, model: str | None = None):
        self.model = model or settings.OPENAI_EMBEDDING_MODEL

    async def embed_text(self, text: str) -> list[float]:
        """Embed a single string. Returns [] for blank input; raises on API failure."""
        vectors = await self.embed_texts([text])
        return vectors[0] if vectors else []

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        """Batch-embed texts. Blank inputs become []. API/key failures raise."""
        cleaned = [(t or "").strip() for t in texts]
        if not cleaned:
            return []
        needs_embed = [i for i, t in enumerate(cleaned) if t]
        if not needs_embed:
            return [[] for _ in cleaned]
        if not settings.OPENAI_API_KEY:
            logger.warning("EmbeddingService: OPENAI_API_KEY empty — embedding unavailable")
            raise EmbeddingUnavailableError("OPENAI_API_KEY not configured")

        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            # OpenAI rejects empty strings; use a single space placeholder
            payload = [t if t else " " for t in cleaned]
            response = await client.embeddings.create(model=self.model, input=payload)
            by_index = {item.index: list(item.embedding) for item in response.data}
            return [by_index[i] for i in range(len(payload))]
        except EmbeddingUnavailableError:
            raise
        except Exception as exc:
            logger.warning("EmbeddingService failed: %s", exc)
            raise EmbeddingUnavailableError(str(exc)) from exc
