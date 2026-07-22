"""
Stage 7 — Combined confidence scoring for name extraction.
"""

from __future__ import annotations

# Minimum combined score to accept found=True.
ACCEPTANCE_THRESHOLD = 0.45

# Signal weights (must sum to 1.0).
_WEIGHT_GEMINI = 0.35
_WEIGHT_TWILIO = 0.20
_WEIGHT_REGEX = 0.25
_WEIGHT_VALIDATION = 0.20

_GEMINI_MAP = {"high": 1.0, "medium": 0.6, "low": 0.3}
_TWILIO_NEUTRAL = 0.5


def _gemini_score(confidence: str | None) -> float:
    if not confidence:
        return 0.0
    return _GEMINI_MAP.get(str(confidence).lower(), 0.3)


def _twilio_score(twilio_confidence: float) -> float:
    if twilio_confidence < 0:
        return _TWILIO_NEUTRAL
    return max(0.0, min(1.0, twilio_confidence))


def _validation_score(is_valid: bool) -> float:
    return 1.0 if is_valid else 0.0


def compute_combined_score(
    gemini_confidence: str | None,
    twilio_confidence: float,
    regex_score: float,
    is_valid: bool,
) -> float:
    """
    Combine Gemini, Twilio STT, regex, and validation signals into [0, 1].
    """
    score = (
        _WEIGHT_GEMINI * _gemini_score(gemini_confidence)
        + _WEIGHT_TWILIO * _twilio_score(twilio_confidence)
        + _WEIGHT_REGEX * max(0.0, min(1.0, regex_score))
        + _WEIGHT_VALIDATION * _validation_score(is_valid)
    )
    return round(max(0.0, min(1.0, score)), 4)


def score_to_confidence_level(combined_score: float) -> str:
    """Map float score back to high/medium/low for API compatibility."""
    if combined_score >= 0.75:
        return "high"
    if combined_score >= 0.50:
        return "medium"
    return "low"


def meets_acceptance_threshold(combined_score: float, is_valid: bool) -> bool:
    """Return True if name should be accepted as found."""
    return is_valid and combined_score >= ACCEPTANCE_THRESHOLD
