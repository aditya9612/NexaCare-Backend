"""
RagAnalytics — structured logging for FAQ RAG turns.

Logs: question, retrieved documents, confidence, latency_ms, transfer_reason, outcome.

Integration: RagFaqService after each answer. Does not write booking tables.
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
    ) -> None:
        logger.info(
            "faq_rag_analytics hospital_id=%s outcome=%s confidence=%.3f "
            "latency_ms=%.1f transfer_reason=%s source=%s question=%r retrieved=%s",
            hospital_id,
            outcome,
            confidence,
            latency_ms,
            transfer_reason,
            source,
            (question or "")[:200],
            retrieved,
        )
