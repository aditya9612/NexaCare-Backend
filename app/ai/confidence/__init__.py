"""
app/ai/confidence — FAQ RAG confidence scoring and response gates.

Integration: used only by RagFaqService after Top-5 retrieval.
Thresholds from settings.FAQ_CONFIDENCE_ANSWER / FAQ_CONFIDENCE_CLARIFY.
Does not affect booking specialty confidence or name extraction.
"""

from app.ai.confidence.scorer import ConfidenceDecision, ConfidenceScorer

__all__ = ["ConfidenceDecision", "ConfidenceScorer"]
