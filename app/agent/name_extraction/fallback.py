"""
Stage 8 — Fallback chain for name extraction.

Never hallucinate names. Try validated sources in priority order.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.agent.name_extraction.confidence import (
    compute_combined_score,
    meets_acceptance_threshold,
    score_to_confidence_level,
)
from app.agent.name_extraction.postprocess import postprocess_name
from app.agent.name_extraction.rule_engine import NameCandidate, best_regex_candidate
from app.agent.name_extraction.validate import is_valid_indian_name

# Minimum regex score for regex-only fallback (no Gemini).
REGEX_SHORT_CIRCUIT_THRESHOLD = 0.85


@dataclass
class FallbackResult:
    """Result from the fallback resolution chain."""

    found: bool
    name: str
    confidence: str
    reason: str
    path_used: str
    combined_score: float = 0.0


def _build_result(
    name: str,
    path_used: str,
    reason: str,
    gemini_confidence: str | None,
    twilio_confidence: float,
    regex_score: float,
) -> FallbackResult:
    """Postprocess, validate, score, and build a FallbackResult."""
    processed = postprocess_name(name)
    valid, validation_reason = is_valid_indian_name(processed)

    combined = compute_combined_score(
        gemini_confidence=gemini_confidence,
        twilio_confidence=twilio_confidence,
        regex_score=regex_score,
        is_valid=valid,
    )

    if valid and meets_acceptance_threshold(combined, valid):
        return FallbackResult(
            found=True,
            name=processed,
            confidence=score_to_confidence_level(combined),
            reason=reason,
            path_used=path_used,
            combined_score=combined,
        )

    return FallbackResult(
        found=False,
        name="",
        confidence="low",
        reason=validation_reason if not valid else f"Confidence below threshold ({combined:.2f}).",
        path_used=path_used,
        combined_score=combined,
    )


def try_regex_short_circuit(
    cleaned: str,
    twilio_confidence: float,
) -> FallbackResult | None:
    """
    Skip Gemini when regex yields high-confidence valid candidate.

    Returns FallbackResult if short-circuit succeeds, else None.
    """
    candidate = best_regex_candidate(cleaned)
    if not candidate or candidate.score < REGEX_SHORT_CIRCUIT_THRESHOLD:
        return None

    result = _build_result(
        name=candidate.name,
        path_used="regex_short_circuit",
        reason=f"High-confidence regex match ({candidate.source}).",
        gemini_confidence=None,
        twilio_confidence=twilio_confidence,
        regex_score=candidate.score,
    )
    return result if result.found else None


def resolve_from_gemini(
    gemini_output: dict,
    twilio_confidence: float,
    regex_score: float,
) -> FallbackResult:
    """Resolve using validated Gemini output."""
    if not gemini_output or not gemini_output.get("found"):
        return FallbackResult(
            found=False,
            name="",
            confidence="low",
            reason=gemini_output.get("reason", "Gemini found no name.") if gemini_output else "Gemini returned no output.",
            path_used="gemini",
            combined_score=0.0,
        )

    return _build_result(
        name=gemini_output.get("name", ""),
        path_used="gemini",
        reason=gemini_output.get("reason", "Extracted by Gemini."),
        gemini_confidence=gemini_output.get("confidence"),
        twilio_confidence=twilio_confidence,
        regex_score=regex_score,
    )


def resolve_regex_fallback(
    cleaned: str,
    twilio_confidence: float,
) -> FallbackResult | None:
    """Use best regex candidate when Gemini fails."""
    candidate = best_regex_candidate(cleaned)
    if not candidate:
        return None

    result = _build_result(
        name=candidate.name,
        path_used="regex_fallback",
        reason=f"Regex fallback ({candidate.source}).",
        gemini_confidence=None,
        twilio_confidence=twilio_confidence,
        regex_score=candidate.score,
    )
    return result if result.found else None


def resolve_heuristic_fallback(
    cleaned: str,
    twilio_confidence: float,
) -> FallbackResult | None:
    """
    Last resort: cleaned transcript is already a short valid name.

    Only used when transcript is 1–3 tokens with no cue phrases.
    """
    tokens = cleaned.strip().split()
    if not tokens or len(tokens) > 3:
        return None

    lower = cleaned.lower()
    cue_fragments = (
        "my name", "i am", "i'm", "this is", "call me", "mera naam",
        "majhe naav", "मेरा नाम", "माझे नाव", "speaking", "hospital",
        "doctor", "appointment", "fever", "pain",
    )
    if any(frag in lower for frag in cue_fragments):
        return None

    result = _build_result(
        name=cleaned,
        path_used="heuristic",
        reason="Heuristic: bare short utterance treated as name.",
        gemini_confidence=None,
        twilio_confidence=twilio_confidence,
        regex_score=0.62,
    )
    return result if result.found else None


def not_found(reason: str = "No valid name found in transcript.") -> FallbackResult:
    """Final fallback when all strategies fail."""
    return FallbackResult(
        found=False,
        name="",
        confidence="low",
        reason=reason,
        path_used="none",
        combined_score=0.0,
    )


def get_best_regex_score(candidates: list[NameCandidate]) -> float:
    """Return highest regex score from candidate list."""
    if not candidates:
        return 0.0
    return max(c.score for c in candidates)
