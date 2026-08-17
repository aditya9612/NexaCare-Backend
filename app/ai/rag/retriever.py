"""
KnowledgeRetriever — Top-5 cosine similarity over hospital knowledge embeddings.

Integration:
- Loads vectors via EmbeddingStore (MySQL + Redis cache)
- Lazy-backfills missing embeddings from MySQL KB snapshot
- Called by RagFaqService only

Does not call OpenAI chat; does not touch booking flows.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embeddings.service import EmbeddingService, EmbeddingUnavailableError
from app.ai.embeddings.store import (
    EmbeddingStore,
    build_embed_text,
    label_for_entry,
)
from app.core.logger import logger
from app.repositories.hospital_voice_repository import (
    HospitalFaqRepository,
    HospitalPolicyRepository,
    HospitalVoiceDocumentRepository,
)


@dataclass
class RetrievedChunk:
    """One retrieved KB entry with similarity score."""

    source: str  # faq | policy | document
    id: int
    text: str
    label: str
    score: float


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Pure-Python cosine similarity; returns 0.0 on empty/mismatched vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


class KnowledgeRetriever:
    """Retrieve Top-K knowledge entries for a hospital FAQ question."""

    def __init__(
        self,
        db: AsyncSession,
        embedder: EmbeddingService | None = None,
        store: EmbeddingStore | None = None,
    ):
        self.db = db
        self.embedder = embedder or EmbeddingService()
        self.store = store or EmbeddingStore(db, self.embedder)
        self.faq_repo = HospitalFaqRepository(db)
        self.policy_repo = HospitalPolicyRepository(db)
        self.doc_repo = HospitalVoiceDocumentRepository(db)

    async def retrieve(
        self,
        hospital_id: int,
        query: str,
        language: str = "en",
        top_k: int = 5,
    ) -> list[RetrievedChunk]:
        """Embed query and return Top-K chunks sorted by cosine similarity desc."""
        normalized = (query or "").strip()
        if not normalized:
            return []

        try:
            query_vec = await self.embedder.embed_text(normalized)
        except EmbeddingUnavailableError:
            raise

        if not query_vec:
            logger.warning("KnowledgeRetriever: empty query embedding")
            raise EmbeddingUnavailableError("empty query embedding vector")

        items = await self._load_enriched_vectors(hospital_id, language)
        if language != "en":
            en_items = await self._load_enriched_vectors(hospital_id, "en")
            seen = {(i["source"], i["id"]) for i in items}
            for item in en_items:
                key = (item["source"], item["id"])
                if key not in seen:
                    items.append(item)
                    seen.add(key)

        scored: list[RetrievedChunk] = []
        for item in items:
            vec = item.get("embedding") or []
            score = cosine_similarity(query_vec, vec)
            scored.append(
                RetrievedChunk(
                    source=item["source"],
                    id=int(item["id"]),
                    text=item.get("text") or "",
                    label=item.get("label") or f"[{item['source']}:{item['id']}]",
                    score=score,
                )
            )

        scored.sort(key=lambda c: c.score, reverse=True)
        return scored[: max(1, top_k)]

    async def _load_enriched_vectors(
        self, hospital_id: int, language: str
    ) -> list[dict[str, Any]]:
        kb_lookup = await self._build_kb_lookup(hospital_id, language)
        items = await self.store.list_active_vectors(
            hospital_id, language, kb_lookup=kb_lookup
        )

        # Lazy backfill when KB has rows but embeddings are missing
        if len(items) < len(kb_lookup):
            await self._backfill_missing(hospital_id, language, kb_lookup, items)
            items = await self.store.list_active_vectors(
                hospital_id, language, kb_lookup=kb_lookup
            )
        return items

    async def _build_kb_lookup(
        self, hospital_id: int, language: str
    ) -> dict[str, dict[str, Any]]:
        lookup: dict[str, dict[str, Any]] = {}
        faqs = await self.faq_repo.list_for_hospital(hospital_id, language)
        for f in faqs:
            ref = f"faq:{f.id}"
            lookup[ref] = {
                "text": f.answer,
                "label": label_for_entry(
                    "faq", f.id, question=f.question, answer=f.answer
                ),
                "embed_text": build_embed_text(
                    "faq",
                    question=f.question,
                    tags=f.tags or "",
                    answer=f.answer,
                ),
                "language": f.language or language,
                "hospital_id": f.hospital_id,
                "source_type": "faq",
                "source_id": f.id,
            }
        policies = await self.policy_repo.list_for_hospital(hospital_id, language)
        for p in policies:
            ref = f"policy:{p.id}"
            lookup[ref] = {
                "text": p.body,
                "label": label_for_entry(
                    "policy",
                    p.id,
                    title=p.title,
                    body=p.body,
                    category=p.category or "",
                ),
                "embed_text": build_embed_text(
                    "policy",
                    title=p.title,
                    category=p.category or "",
                    body=p.body,
                ),
                "language": p.language or language,
                "hospital_id": p.hospital_id,
                "source_type": "policy",
                "source_id": p.id,
            }
        docs = await self.doc_repo.list_for_hospital(hospital_id, language)
        for d in docs:
            ref = f"document:{d.id}"
            lookup[ref] = {
                "text": d.content,
                "label": label_for_entry(
                    "document", d.id, title=d.title, content=d.content
                ),
                "embed_text": build_embed_text(
                    "document", title=d.title, content=d.content
                ),
                "language": d.language or language,
                "hospital_id": d.hospital_id,
                "source_type": "document",
                "source_id": d.id,
            }
        return lookup

    async def _backfill_missing(
        self,
        hospital_id: int,
        language: str,
        kb_lookup: dict[str, dict[str, Any]],
        existing: list[dict[str, Any]],
    ) -> None:
        have = {(i["source"], i["id"]) for i in existing}
        for ref, meta in kb_lookup.items():
            key = (meta["source_type"], meta["source_id"])
            if key in have:
                continue
            try:
                await self.store.upsert_kb_entry(
                    hospital_id=hospital_id,
                    source_type=meta["source_type"],
                    source_id=meta["source_id"],
                    language=meta.get("language") or language,
                    embed_text=meta["embed_text"],
                    answer_text=meta["text"],
                    label=meta["label"],
                )
            except Exception as exc:
                logger.warning("Lazy embed backfill failed for %s: %s", ref, exc)
