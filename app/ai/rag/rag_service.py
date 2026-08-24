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

from app.ai.rag.kb_cache import get_kb_version

from app.ai.rag.retriever import KnowledgeRetriever, RetrievedChunk, _normalize_query

from app.core.config import settings

from app.core.logger import logger

from app.utils.redis_service import cache_delete_pattern, cache_get, cache_set



SELECTOR_TOP_K = 5

RETRIEVAL_TOP_K = 15

SOURCE_PRIORITY = {"faq": 3, "policy": 2, "document": 1}

CONFLICT_SCORE_GAP = 0.05



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

    def query_cache_key(hospital_id: int, language: str, question: str, kb_version: int = 0) -> str:

        normalized = _normalize_query(question).lower()
        normalized = re.sub(r"\s+", " ", normalized).strip()

        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()

        return f"voice:faq:query:{hospital_id}:{language}:v{kb_version}:{digest}"



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

        kb_version = await get_kb_version(hospital_id)

        cache_key = self.query_cache_key(hospital_id, lang, question, kb_version)

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

                confidence_action=cached.get("confidence_action"),

                selector_called=bool(cached.get("selector_called")),

                cache_hit=True,

                kb_version=kb_version,

            )

            return result



        try:

            chunks = await self.retriever.retrieve(

                hospital_id, question, lang, top_k=RETRIEVAL_TOP_K

            )

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

                confidence_action=ConfidenceAction.TRANSFER.value,

                selector_called=False,

                cache_key=cache_key,

                kb_version=kb_version,

                embedding_status="error",

            )

            return result



        top_score = chunks[0].score if chunks else 0.0

        decision = self.scorer.score(top_score)

        selector_chunks = chunks[:SELECTOR_TOP_K]

        conflict = self._detect_conflict(chunks[:3])



        if not chunks or decision.action == ConfidenceAction.TRANSFER:

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

                confidence_action=decision.action.value,

                selector_called=False,

                cache_key=cache_key,

            )

            return result



        if decision.action == ConfidenceAction.CLARIFY:

            if conflict == "transfer":

                result = self._transfer(lang, decision.confidence)

                result.transfer_reason = "faq_conflict"

            else:

                result = self._clarify(lang, chunks, decision.confidence)

            await self._finalize(

                session_id=session_id,

                question=question,

                language=lang,

                result=result,

                hospital_id=hospital_id,

                chunks=chunks,

                started=started,

                outcome="clarify" if not result.should_transfer else "transfer",

                transfer_reason=result.transfer_reason or None,

                confidence_action=decision.action.value,

                selector_called=False,

                cache_key=cache_key,

            )

            return result



        # ANSWER band — selector only

        if conflict == "transfer":

            result = self._transfer(lang, decision.confidence)

            result.transfer_reason = "faq_conflict"

            await self._finalize(

                session_id=session_id,

                question=question,

                language=lang,

                result=result,

                hospital_id=hospital_id,

                chunks=chunks,

                started=started,

                outcome="transfer",

                transfer_reason="faq_conflict",

                confidence_action=decision.action.value,

                selector_called=False,

                cache_key=cache_key,

            )

            return result



        if conflict == "clarify":

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

                transfer_reason="faq_clarification",

                confidence_action=decision.action.value,

                selector_called=False,

                cache_key=cache_key,

            )

            return result



        selection = await self.selector.select(
            question, selector_chunks, lang, normalized_question=_normalize_query(question)
        )

        if selection.kind == "match" and selection.text:

            agreed = (

                chunks[0].source == selection.source

                and chunks[0].id == selection.entry_id

            )

            final_conf = self.scorer.score(

                decision.confidence, selector_agreed=agreed

            ).confidence

            result = RagFaqResult(

                found=True,

                answer=selection.text,

                source=selection.source or "faq",

                confidence=final_conf,

                faq_hit=True,

                ai_fallback=False,

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

                transfer_reason="faq_hit",

                confidence_action=ConfidenceAction.ANSWER.value,

                selector_called=True,

                cache_key=cache_key,

                kb_version=kb_version,

                selector_result=selection.kind,

            )

            return result

        transfer_reason = "faq_no_match"

        if selection.kind == "invalid_id":

            transfer_reason = "selector_invalid_id"

        elif selection.kind == "error":

            transfer_reason = "selector_error"



        result = self._transfer(lang, max(0.0, decision.confidence - 0.1))

        result.transfer_reason = transfer_reason

        await self._finalize(

            session_id=session_id,

            question=question,

            language=lang,

            result=result,

            hospital_id=hospital_id,

            chunks=chunks,

            started=started,

            outcome="transfer",

            transfer_reason=transfer_reason,

            confidence_action=decision.action.value,

            selector_called=True,

            cache_key=cache_key,

            kb_version=kb_version,

            selector_result=selection.kind,

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

    def _normalize_answer(text: str) -> str:

        return re.sub(r"\s+", " ", (text or "").lower()).strip()



    @staticmethod

    def _extract_fact_tokens(text: str) -> set[str]:

        normalized = RagFaqService._normalize_answer(text)

        tokens = set(re.findall(r"\d+(?::\d+)?|\d+\s*(?:am|pm|vajta)?", normalized))

        tokens.update(re.findall(r"\b\d+\b", normalized))

        return tokens



    @classmethod

    def _answers_materially_differ(cls, a: str, b: str) -> bool:

        na = cls._normalize_answer(a)

        nb = cls._normalize_answer(b)

        if na == nb:

            return False

        facts_a = cls._extract_fact_tokens(a)

        facts_b = cls._extract_fact_tokens(b)

        if facts_a and facts_b and facts_a != facts_b:

            return True

        return na != nb



    @classmethod

    def _detect_conflict(cls, chunks: list[RetrievedChunk]) -> str | None:

        """Return 'clarify', 'transfer', or None when top candidates disagree."""

        if len(chunks) < 2:

            return None



        top = chunks[0]

        for candidate in chunks[1:3]:

            if top.score - candidate.score > CONFLICT_SCORE_GAP:

                continue

            if not cls._answers_materially_differ(top.text, candidate.text):

                continue

            top_priority = SOURCE_PRIORITY.get(top.source, 0)

            candidate_priority = SOURCE_PRIORITY.get(candidate.source, 0)

            if top_priority > candidate_priority:

                return None

            if candidate_priority > top_priority:

                return "clarify"

            return "clarify"

        return None



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

        result: RagFaqResult,

        outcome: str,

        transfer_reason: str | None,

        confidence_action: str | None = None,

        selector_called: bool = False,

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

            "confidence_action": confidence_action,

            "selector_called": selector_called,

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

        confidence_action: str | None = None,

        selector_called: bool = False,

        cache_key: str | None = None,

        cache_hit: bool = False,

        kb_version: int = 0,

        embedding_status: str = "ok",

        selector_result: str | None = None,

    ) -> None:

        latency_ms = (time.perf_counter() - started) * 1000.0

        retrieved = [

            {"source": c.source, "id": c.id, "score": round(c.score, 4)} for c in chunks

        ]

        top = chunks[0] if chunks else None

        top_candidate_id = f"{top.source}:{top.id}" if top else None
        score_decision_reason = top.decision_reason if top else None
        if outcome == "transfer" and transfer_reason == "faq_low_confidence":
            score_decision_reason = "low_confidence"

        RagAnalytics.log(

            hospital_id=hospital_id,

            question=question,

            retrieved=retrieved,

            confidence=result.confidence,

            latency_ms=latency_ms,

            outcome=outcome,

            transfer_reason=transfer_reason or result.transfer_reason or None,

            source=result.source,

            language=language,

            confidence_action=confidence_action,

            selector_called=selector_called,

            selector_result=selector_result,

            normalized_query=_normalize_query(question),

            top_candidate_id=top_candidate_id,

            semantic_score=top.semantic_score if top else None,

            keyword_score=top.keyword_score if top else None,

            tag_score=top.tag_score if top else None,

            entity_score=top.entity_score if top else None,

            language_score=top.language_score if top else None,

            authority_score=top.authority_score if top else None,
            exact_match_score=top.exact_match_score if top else None,
            phrase_match_score=top.phrase_match_score if top else None,
            decision_reason=score_decision_reason,
            normalized_candidate=top.normalized_candidate if top else None,
            candidate_question=top.candidate_question if top else None,
            candidate_hospital_id=hospital_id,
            candidate_active=True if top else None,
            candidate_deleted=False if top else None,
            faq_hit=result.faq_hit,

            cache_hit=cache_hit,

            embedding_status=embedding_status,

            kb_version=kb_version,

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

                self._to_cache_dict(

                    result,

                    outcome,

                    transfer_reason,

                    confidence_action=confidence_action,

                    selector_called=selector_called,

                ),

                ttl=ttl,

            )


