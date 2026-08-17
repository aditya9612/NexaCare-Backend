"""
RagFaqService — orchestrate FAQ RAG: cache → retrieve → confidence → OpenAI Top-5.

Integration:
- Called exclusively from FaqRetrievalService.answer (after MedicalSafetyGuard)
- Optional session_id updates FaqMemory (FAQ-only Redis key)
- Emits RagAnalytics structured logs

Public result maps 1:1 onto FaqAnswer fields used by agent / voice-assistant.
Does not modify booking, Twilio contracts, Gemini, or Phase 6 conversation.py.
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.confidence.scorer import ConfidenceAction, ConfidenceScorer
from app.ai.memory.faq_memory import FaqMemory
from app.ai.rag.analytics import RagAnalytics
from app.ai.rag.openai_selector import OpenAITop5Selector
from app.ai.embeddings.service import EmbeddingUnavailableError
from app.ai.rag.retriever import KnowledgeRetriever, RetrievedChunk
from app.core.config import settings
from app.core.logger import logger
from app.utils.redis_service import cache_delete_pattern, cache_get, cache_set

TRANSFER_PHRASES = {
    "en": "I could not find a reliable answer. Let me transfer you to reception.",
    "hi": "मुझे विश्वसनीय उत्तर नहीं मिला। मैं आपको रिसेप्शन से जोड़ती हूँ।",
    "mr": "मला विश्वासार्ह उत्तर सापडले नाही. मी तुम्हाला रिसेप्शनशी जोडते.",
}

CLARIFY_PHRASES = {
    "en": "Just to make sure I help correctly — are you asking about {topics}?",
    "hi": "ठीक से मदद करने के लिए बताइए — क्या आप {topics} के बारे में पूछ रहे हैं?",
    "mr": "योग्य मदत करण्यासाठी सांगा — तुम्ही {topics} बद्दल विचारत आहात का?",
}


@dataclass
class RagFaqResult:
    found: bool
    answer: str = ""
    source: str = ""
    confidence: float = 0.0
    faq_hit: bool = False
    ai_fallback: bool = False
    should_transfer: bool = False
    needs_clarification: bool = False
    transfer_reason: str = ""


class RagFaqService:
    """End-to-end FAQ RAG orchestration for one hospital question."""

    def __init__(
        self,
        db: AsyncSession,
        retriever: KnowledgeRetriever | None = None,
        selector: OpenAITop5Selector | None = None,
        scorer: ConfidenceScorer | None = None,
        memory: FaqMemory | None = None,
    ):
        self.db = db
        self.retriever = retriever or KnowledgeRetriever(db)
        self.selector = selector or OpenAITop5Selector()
        self.scorer = scorer or ConfidenceScorer()
        self.memory = memory or FaqMemory()

    @staticmethod
    def query_cache_key(hospital_id: int, language: str, question: str) -> str:
        normalized = re.sub(r"\s+", " ", (question or "").lower()).strip()
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return f"voice:faq:query:{hospital_id}:{language}:{digest}"

    @staticmethod
    async def invalidate_query_cache(hospital_id: int) -> None:
        await cache_delete_pattern(f"voice:faq:query:{hospital_id}:*")

    async def answer(
        self,
        hospital_id: int,
        question: str,
        language: str = "en",
        session_id: str | None = None,
    ) -> RagFaqResult:
        started = time.perf_counter()
        lang = language or "en"
        cache_key = self.query_cache_key(hospital_id, lang, question)
        cached = await cache_get(cache_key)
        if isinstance(cached, dict) and "answer" in cached:
            result = self._from_cache_dict(cached)
            await self._finalize(
                session_id=session_id,
                question=question,
                language=lang,
                result=result,
                hospital_id=hospital_id,
                chunks=[],
                started=started,
                outcome=cached.get("outcome") or "answer",
                transfer_reason=cached.get("transfer_reason"),
            )
            return result

        try:
            chunks = await self.retriever.retrieve(hospital_id, question, lang, top_k=5)
        except EmbeddingUnavailableError as exc:
            logger.warning("RagFaqService embedding unavailable: %s", exc)
            result = self._infrastructure_transfer(lang, "embedding_error")
            await self._finalize(
                session_id=session_id,
                question=question,
                language=lang,
                result=result,
                hospital_id=hospital_id,
                chunks=[],
                started=started,
                outcome="embedding_error",
                transfer_reason="embedding_error",
                cache_key=cache_key,
            )
            return result

        top_score = chunks[0].score if chunks else 0.0
        decision = self.scorer.score(top_score)

        if decision.action == ConfidenceAction.TRANSFER or not chunks:
            result = self._transfer(lang, decision.confidence)
            result.transfer_reason = "faq_low_confidence"
            await self._finalize(
                session_id=session_id,
                question=question,
                language=lang,
                result=result,
                hospital_id=hospital_id,
                chunks=chunks,
                started=started,
                outcome="transfer",
                transfer_reason="faq_low_confidence",
                cache_key=cache_key,
            )
            return result

        if decision.action == ConfidenceAction.CLARIFY:
            result = self._clarify(lang, chunks, decision.confidence)
            await self._finalize(
                session_id=session_id,
                question=question,
                language=lang,
                result=result,
                hospital_id=hospital_id,
                chunks=chunks,
                started=started,
                outcome="clarify",
                cache_key=cache_key,
            )
            return result

        selection = await self.selector.select(question, chunks, lang)
        if selection.kind == "match" and selection.text:
            agreed = (
                chunks[0].source == selection.source and chunks[0].id == selection.entry_id
            )
            final_conf = self.scorer.score(
                decision.confidence, selector_agreed=agreed
            ).confidence
            result = RagFaqResult(
                found=True,
                answer=selection.text,
                source=selection.source or "openai",
                confidence=final_conf,
                faq_hit=True,
                ai_fallback=True,
            )
            await self._finalize(
                session_id=session_id,
                question=question,
                language=lang,
                result=result,
                hospital_id=hospital_id,
                chunks=chunks,
                started=started,
                outcome="answer",
                cache_key=cache_key,
            )
            return result

        if selection.kind == "clarify" and selection.clarify_question:
            result = RagFaqResult(
                found=True,
                answer=selection.clarify_question,
                source="clarification",
                confidence=decision.confidence,
                needs_clarification=True,
                ai_fallback=True,
            )
            await self._finalize(
                session_id=session_id,
                question=question,
                language=lang,
                result=result,
                hospital_id=hospital_id,
                chunks=chunks,
                started=started,
                outcome="clarify",
                cache_key=cache_key,
            )
            return result

        result = self._transfer(lang, max(0.0, decision.confidence - 0.1))
        result.transfer_reason = "faq_no_match"
        await self._finalize(
            session_id=session_id,
            question=question,
            language=lang,
            result=result,
            hospital_id=hospital_id,
            chunks=chunks,
            started=started,
            outcome="transfer",
            transfer_reason="faq_no_match",
            cache_key=cache_key,
        )
        return result

    def _transfer(self, language: str, confidence: float) -> RagFaqResult:
        return RagFaqResult(
            found=False,
            answer=TRANSFER_PHRASES.get(language, TRANSFER_PHRASES["en"]),
            source="transfer",
            should_transfer=True,
            ai_fallback=True,
            confidence=confidence,
        )

    def _infrastructure_transfer(self, language: str, reason: str) -> RagFaqResult:
        return RagFaqResult(
            found=False,
            answer=TRANSFER_PHRASES.get(language, TRANSFER_PHRASES["en"]),
            source=reason,
            should_transfer=True,
            ai_fallback=True,
            confidence=0.0,
            transfer_reason=reason,
        )

    def _clarify(
        self, language: str, chunks: list[RetrievedChunk], confidence: float
    ) -> RagFaqResult:
        topics = self._topic_hints(chunks)
        template = CLARIFY_PHRASES.get(language, CLARIFY_PHRASES["en"])
        return RagFaqResult(
            found=True,
            answer=template.format(topics=topics),
            source="clarification",
            confidence=confidence,
            needs_clarification=True,
        )

    @staticmethod
    def _topic_hints(chunks: list[RetrievedChunk], limit: int = 2) -> str:
        hints: list[str] = []
        for chunk in chunks[:limit]:
            label = chunk.label or ""
            if "Q:" in label:
                q = label.split("Q:", 1)[-1].split("\n", 1)[0].strip()
                if q:
                    hints.append(q[:80])
                    continue
            if "Title:" in label:
                t = label.split("Title:", 1)[-1].split("\n", 1)[0].strip()
                if t:
                    hints.append(t[:80])
                    continue
            hints.append(f"{chunk.source} {chunk.id}")
        if not hints:
            return "visiting hours, parking, or contact details"
        if len(hints) == 1:
            return hints[0]
        return f"{hints[0]} or {hints[1]}"

    @staticmethod
    def _from_cache_dict(data: dict) -> RagFaqResult:
        return RagFaqResult(
            found=bool(data.get("found")),
            answer=data.get("answer") or "",
            source=data.get("source") or "",
            confidence=float(data.get("confidence") or 0.0),
            faq_hit=bool(data.get("faq_hit")),
            ai_fallback=bool(data.get("ai_fallback")),
            should_transfer=bool(data.get("should_transfer")),
            needs_clarification=bool(data.get("needs_clarification")),
            transfer_reason=data.get("transfer_reason") or "",
        )

    @staticmethod
    def _to_cache_dict(
        result: RagFaqResult, outcome: str, transfer_reason: str | None
    ) -> dict:
        return {
            "found": result.found,
            "answer": result.answer,
            "source": result.source,
            "confidence": result.confidence,
            "faq_hit": result.faq_hit,
            "ai_fallback": result.ai_fallback,
            "should_transfer": result.should_transfer,
            "needs_clarification": result.needs_clarification,
            "outcome": outcome,
            "transfer_reason": transfer_reason or result.transfer_reason,
        }

    async def _finalize(
        self,
        *,
        session_id: str | None,
        question: str,
        language: str,
        result: RagFaqResult,
        hospital_id: int,
        chunks: list[RetrievedChunk],
        started: float,
        outcome: str,
        transfer_reason: str | None = None,
        cache_key: str | None = None,
    ) -> None:
        latency_ms = (time.perf_counter() - started) * 1000.0
        retrieved = [
            {"source": c.source, "id": c.id, "score": round(c.score, 4)} for c in chunks
        ]
        RagAnalytics.log(
            hospital_id=hospital_id,
            question=question,
            retrieved=retrieved,
            confidence=result.confidence,
            latency_ms=latency_ms,
            outcome=outcome,
            transfer_reason=transfer_reason,
            source=result.source,
        )

        if session_id:
            topic = question
            if chunks:
                topic = self._topic_hints(chunks[:1], limit=1)
            await self.memory.update(
                session_id,
                question=question,
                answer=result.answer,
                language=language,
                topic=topic,
            )

        if cache_key:
            ttl = settings.VOICE_FAQ_QUERY_CACHE_TTL_SECONDS
            if result.should_transfer:
                ttl = min(60, ttl)
            await cache_set(
                cache_key,
                self._to_cache_dict(result, outcome, transfer_reason),
                ttl=ttl,
            )
