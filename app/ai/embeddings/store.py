"""
EmbeddingStore — persist and load knowledge embeddings in MySQL + Redis.

Integration points:
- HospitalKnowledgeService CRUD → upsert_kb_entry / deactivate_entry
- KnowledgeRetriever → list_active_for_hospital (with Redis vector cache)
- FaqRetrievalService.invalidate_cache → invalidate_vector_cache

Does not modify booking state or Phase 6 conversation memory.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embeddings.service import EmbeddingService
from app.core.config import settings
from app.core.logger import logger
from app.repositories.knowledge_embedding_repository import KnowledgeEmbeddingRepository
from app.utils.redis_service import cache_delete, cache_get, cache_set


def content_hash(text: str) -> str:
    """SHA-256 of normalized embed text for skip-reembed checks."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def build_embed_text(
    source_type: str,
    *,
    question: str = "",
    answer: str = "",
    tags: str = "",
    title: str = "",
    body: str = "",
    category: str = "",
    content: str = "",
) -> str:
    """Build canonical text to embed for a KB row."""
    if source_type == "faq":
        parts = [question or "", tags or "", answer or ""]
    elif source_type == "policy":
        parts = [title or "", category or "", body or ""]
    else:
        parts = [title or "", content or ""]
    return "\n".join(p.strip() for p in parts if p and str(p).strip())


def answer_text_for_source(
    source_type: str,
    *,
    answer: str = "",
    body: str = "",
    content: str = "",
) -> str:
    """Verbatim spoken answer field for a source type."""
    if source_type == "faq":
        return answer or ""
    if source_type == "policy":
        return body or ""
    return content or ""


def label_for_entry(
    source_type: str,
    source_id: int,
    *,
    question: str = "",
    answer: str = "",
    title: str = "",
    body: str = "",
    category: str = "",
    content: str = "",
) -> str:
    """Human-readable catalog label for OpenAI Top-5 selector."""
    if source_type == "faq":
        return f"[faq:{source_id}] Q: {question}\nA: {answer}"
    if source_type == "policy":
        return (
            f"[policy:{source_id}] Title: {title}\n"
            f"Category: {category}\n"
            f"Body: {body}"
        )
    return f"[document:{source_id}] Title: {title}\nContent: {content}"


class EmbeddingStore:
    """
    Upsert/load knowledge embeddings.

    Redis key: voice:faq:vectors:{hospital_id}:{language}
    Value: list of dicts with source, id, text, label, embedding, language
    """

    def __init__(self, db: AsyncSession, embedder: EmbeddingService | None = None):
        self.db = db
        self.repo = KnowledgeEmbeddingRepository(db)
        self.embedder = embedder or EmbeddingService()

    @staticmethod
    def vector_cache_key(hospital_id: int, language: str) -> str:
        return f"voice:faq:vectors:{hospital_id}:{language}"

    async def invalidate_vector_cache(self, hospital_id: int) -> None:
        for lang in ("en", "hi", "mr"):
            await cache_delete(self.vector_cache_key(hospital_id, lang))

    async def upsert_kb_entry(
        self,
        *,
        hospital_id: int,
        source_type: str,
        source_id: int,
        language: str,
        embed_text: str,
        answer_text: str,
        label: str,
    ) -> None:
        """Embed and persist if content_hash changed; refresh Redis cache."""
        digest = content_hash(embed_text)
        existing = await self.repo.get_by_source(source_type, source_id)
        if (
            existing
            and existing.content_hash == digest
            and existing.is_active
            and existing.embedding_model == self.embedder.model
        ):
            return

        vector = await self.embedder.embed_text(embed_text)
        if not vector:
            logger.warning(
                "EmbeddingStore: empty vector for %s:%s — skipping persist",
                source_type,
                source_id,
            )
            return

        await self.repo.upsert(
            hospital_id=hospital_id,
            source_type=source_type,
            source_id=source_id,
            language=language or "en",
            content_hash=digest,
            embedding_model=self.embedder.model,
            embedding=vector,
            is_active=True,
        )
        # Store metadata alongside vectors in Redis on next load
        await self.invalidate_vector_cache(hospital_id)
        # Keep answer/label in a sidecar Redis map for retriever without re-querying KB
        meta_key = self._meta_cache_key(hospital_id, language or "en")
        meta = await cache_get(meta_key) or {}
        meta[f"{source_type}:{source_id}"] = {
            "text": answer_text,
            "label": label,
            "language": language or "en",
        }
        await cache_set(
            meta_key,
            meta,
            ttl=settings.VOICE_FAQ_VECTOR_CACHE_TTL_SECONDS,
        )

    @staticmethod
    def _meta_cache_key(hospital_id: int, language: str) -> str:
        return f"voice:faq:meta:{hospital_id}:{language}"

    async def deactivate_entry(self, source_type: str, source_id: int, hospital_id: int) -> None:
        await self.repo.deactivate(source_type, source_id)
        await self.invalidate_vector_cache(hospital_id)
        for lang in ("en", "hi", "mr"):
            await cache_delete(self._meta_cache_key(hospital_id, lang))

    async def list_active_vectors(
        self,
        hospital_id: int,
        language: str,
        *,
        kb_lookup: Optional[dict[str, dict[str, Any]]] = None,
    ) -> list[dict[str, Any]]:
        """
        Return active embedding rows enriched with text/label.

        kb_lookup maps "faq:1" → {text, label} when Redis meta is cold.
        """
        cache_key = self.vector_cache_key(hospital_id, language)
        cached = await cache_get(cache_key)
        if cached:
            return cached

        rows = await self.repo.list_active_for_hospital(hospital_id, language)
        meta = await cache_get(self._meta_cache_key(hospital_id, language)) or {}
        kb_lookup = kb_lookup or {}

        items: list[dict[str, Any]] = []
        for row in rows:
            try:
                vector = json.loads(row.embedding) if isinstance(row.embedding, str) else row.embedding
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(vector, list) or not vector:
                continue
            ref = f"{row.source_type}:{row.source_id}"
            info = meta.get(ref) or kb_lookup.get(ref) or {}
            items.append(
                {
                    "source": row.source_type,
                    "id": row.source_id,
                    "hospital_id": row.hospital_id,
                    "language": row.language,
                    "embedding": vector,
                    "text": info.get("text", ""),
                    "label": info.get("label", f"[{ref}]"),
                    "content_hash": row.content_hash,
                }
            )

        await cache_set(cache_key, items, ttl=settings.VOICE_FAQ_VECTOR_CACHE_TTL_SECONDS)
        return items
