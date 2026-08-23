"""
RagAnalytics — structured logging for FAQ RAG turns.

Logs decomposed retrieval scores, cache status, and outcome for production observability.
Does not write booking tables or log unnecessary PII.
"""

from __future__ import annotations

from typing import Any, Optional

from app.core.logger import logger


class RagAnalytics:
    """Emit structured FAQ RAG analytics via the app logger."""

    @staticmethod
    def log(
        *,
        hospital_id: int,
        question: str,
        retrieved: list[dict[str, Any]],
        confidence: float,
        latency_ms: float,
        outcome: str,
        transfer_reason: Optional[str] = None,
        source: Optional[str] = None,
        language: str = "en",
        confidence_action: Optional[str] = None,
        selector_called: bool = False,
        selector_result: Optional[str] = None,
        normalized_query: Optional[str] = None,
        top_candidate_id: Optional[str] = None,
        semantic_score: Optional[float] = None,
        keyword_score: Optional[float] = None,
        tag_score: Optional[float] = None,
        entity_score: Optional[float] = None,
        language_score: Optional[float] = None,
        authority_score: Optional[float] = None,
        faq_hit: bool = False,
        cache_hit: bool = False,
        embedding_status: str = "ok",
        kb_version: int = 0,
    ) -> None:
        score_diag = {
            "semantic": round(semantic_score, 3) if semantic_score is not None else None,
            "keyword": round(keyword_score, 3) if keyword_score is not None else None,
            "tag": round(tag_score, 3) if tag_score is not None else None,
            "entity": round(entity_score, 3) if entity_score is not None else None,
            "language": round(language_score, 3) if language_score is not None else None,
            "authority": round(authority_score, 3) if authority_score is not None else None,
            "fused": round(confidence, 3),
        }
        logger.info(
            "faq_rag_analytics hospital_id=%s kb_version=%s language=%s outcome=%s "
            "confidence=%.3f confidence_action=%s selector_called=%s selector_result=%s "
            "latency_ms=%.1f transfer_reason=%s source=%s faq_hit=%s cache_hit=%s "
            "embedding_status=%s top_candidate_id=%s normalized_query=%r "
            "score_diag=%s question=%r retrieved=%s",
            hospital_id,
            kb_version,
            language,
            outcome,
            confidence,
            confidence_action,
            selector_called,
            selector_result,
            latency_ms,
            transfer_reason,
            source,
            faq_hit,
            cache_hit,
            embedding_status,
            top_candidate_id,
            (normalized_query or "")[:200],
            score_diag,
            (question or "")[:200],
            retrieved,
        )
