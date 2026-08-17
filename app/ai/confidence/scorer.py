"""
ConfidenceScorer — map retrieval similarity to answer / clarify / transfer.

Gates (FAQ path only):
- >= FAQ_CONFIDENCE_ANSWER (0.90): answer directly via OpenAI Top-5 MATCH
- FAQ_CONFIDENCE_CLARIFY .. answer (0.70–0.89): ask clarification
- < FAQ_CONFIDENCE_CLARIFY (0.70): transfer to reception

Integration: RagFaqService only. Does not modify ReceptionTransferService.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.core.config import settings


class ConfidenceAction(str, Enum):
    ANSWER = "answer"
    CLARIFY = "clarify"
    TRANSFER = "transfer"


@dataclass
class ConfidenceDecision:
    confidence: float
    action: ConfidenceAction


class ConfidenceScorer:
    """Derive a ConfidenceDecision from top retrieval score."""

    def __init__(
        self,
        answer_threshold: float | None = None,
        clarify_threshold: float | None = None,
    ):
        self.answer_threshold = (
            answer_threshold
            if answer_threshold is not None
            else settings.FAQ_CONFIDENCE_ANSWER
        )
        self.clarify_threshold = (
            clarify_threshold
            if clarify_threshold is not None
            else settings.FAQ_CONFIDENCE_CLARIFY
        )

    def score(self, top_similarity: float, *, selector_agreed: bool | None = None) -> ConfidenceDecision:
        """
        Compute gated decision.

        Optional selector_agreed boosts confidence slightly when OpenAI MATCH
        aligns with the top retrieved chunk (capped at 1.0).
        """
        conf = max(0.0, min(1.0, float(top_similarity or 0.0)))
        if selector_agreed is True:
            conf = min(1.0, conf + 0.05)
        elif selector_agreed is False:
            conf = max(0.0, conf - 0.05)

        if conf >= self.answer_threshold:
            action = ConfidenceAction.ANSWER
        elif conf >= self.clarify_threshold:
            action = ConfidenceAction.CLARIFY
        else:
            action = ConfidenceAction.TRANSFER
        return ConfidenceDecision(confidence=conf, action=action)
