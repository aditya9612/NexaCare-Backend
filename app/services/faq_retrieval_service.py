"""
FaqRetrievalService — public FAQ entry point for voice agent + voice-assistant.

Phase 1 RAG: delegates retrieval/answering to app.ai.rag.RagFaqService while
preserving the FaqAnswer public contract (found, answer, source, confidence,
faq_hit, ai_fallback, should_transfer) plus additive needs_clarification.

Pipeline:
1. MedicalSafetyGuard (unchanged)
2. RagFaqService (embeddings → Top-5 → confidence gates → OpenAI MATCH)

Does not modify booking, Twilio webhook contracts, Gemini, or Phase 6 conversation.py.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embeddings.store import EmbeddingStore
from app.ai.rag.kb_cache import bump_kb_version
from app.ai.rag.rag_service import TRANSFER_PHRASES, RagFaqService
from app.core.logger import logger
from app.services.medical_safety_guard import MedicalSafetyGuard
from app.utils.redis_service import cache_delete, cache_delete_pattern


@dataclass
class FaqAnswer:
    found: bool
    answer: str = ""
    source: str = ""  # faq | policy | document | openai | clarification | none | transfer
    confidence: float = 0.0
    faq_hit: bool = False
    ai_fallback: bool = False
    should_transfer: bool = False
    needs_clarification: bool = False
    transfer_reason: str = ""


# Re-export for existing imports (agent router, voice assistant)
__all__ = ["FaqAnswer", "TRANSFER_PHRASES", "FaqRetrievalService"]


class FaqRetrievalService:
    """
    Retrieval-Augmented FAQ facade.

    FAQ / Policies / Documents embeddings → Top-5 RAG → OpenAI grounded select
    (low confidence → clarify or transfer). Never invent fees, timings, or
    doctor information.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self._rag = RagFaqService(db)

    def _cache_key(self, hospital_id: int, language: str) -> str:
        return f"voice:faq:{hospital_id}:{language}"

    async def answer(
        self,
        hospital_id: int,
        question: str,
        language: str = "en",
        session_id: str | None = None,
    ) -> FaqAnswer:
        safety = MedicalSafetyGuard.check(question, language)
        if safety.is_medical_advice:
            return FaqAnswer(
                found=False,
                answer=safety.refusal_message,
                source="transfer",
                should_transfer=True,
                confidence=1.0,
            )

        try:
            rag = await self._rag.answer(
                hospital_id,
                question,
                language,
                session_id=session_id,
            )
        except Exception as exc:
            logger.warning("FaqRetrievalService RAG failed: %s", exc)
            return FaqAnswer(
                found=False,
                answer=TRANSFER_PHRASES.get(language, TRANSFER_PHRASES["en"]),
                source="transfer",
                should_transfer=True,
                ai_fallback=True,
                confidence=0.0,
            )

        return FaqAnswer(
            found=rag.found,
            answer=rag.answer,
            source=rag.source,
            confidence=rag.confidence,
            faq_hit=rag.faq_hit,
            ai_fallback=rag.ai_fallback,
            should_transfer=rag.should_transfer,
            needs_clarification=rag.needs_clarification,
            transfer_reason=rag.transfer_reason or "",
        )

    async def invalidate_cache(self, hospital_id: int) -> None:
        """Clear KB snapshot, query-answer, and vector caches for a hospital."""
        await bump_kb_version(hospital_id)
        for lang in ("en", "hi", "mr"):
            await cache_delete(self._cache_key(hospital_id, lang))
            await cache_delete(f"voice:faq:vectors:{hospital_id}:{lang}")
            await cache_delete(f"voice:faq:meta:{hospital_id}:{lang}")
        await RagFaqService.invalidate_query_cache(hospital_id)
        await cache_delete_pattern(f"voice:faq:query:{hospital_id}:*")
        try:
            await EmbeddingStore(self.db).invalidate_vector_cache(hospital_id)
        except Exception as exc:
            logger.warning("Vector cache invalidate failed: %s", exc)
