"""
Name extraction pipeline orchestrator (Stages 1–9).

Public entry point used by app.agent.llm.extract_patient_name().
"""

from __future__ import annotations

import time
from typing import Any

from app.agent.name_extraction.fallback import (
    get_best_regex_score,
    not_found,
    resolve_from_gemini,
    resolve_heuristic_fallback,
    resolve_regex_fallback,
    try_regex_short_circuit,
)
from app.agent.name_extraction.gemini_client import call_gemini
from app.agent.name_extraction.logging_utils import ExtractionLogRecord, log_extraction
from app.agent.name_extraction.preprocess import preprocess_transcript
from app.agent.name_extraction.rule_engine import extract_regex_candidates


def run(transcript: str, twilio_confidence: float = -1.0) -> dict[str, Any]:
    """
    Execute the full multi-stage name extraction pipeline.

    Returns dict with keys: found, name, confidence, reason
    (backward-compatible with existing callers).
    """
    start = time.perf_counter()

    # Empty input fast path.
    if not transcript or not transcript.strip():
        record = ExtractionLogRecord(
            input_transcript=transcript or "",
            clean_transcript="",
            language_hint="unknown",
            final_output={"found": False, "name": "", "confidence": "low", "reason": "Empty transcript."},
            elapsed_ms=0.0,
            path_used="none",
        )
        log_extraction(record)
        return record.final_output

    # Stage 1: Preprocess.
    preprocessed = preprocess_transcript(transcript)
    cleaned = preprocessed.cleaned

    if not cleaned:
        elapsed_ms = (time.perf_counter() - start) * 1000
        final = {"found": False, "name": "", "confidence": "low", "reason": "Empty after preprocessing."}
        log_extraction(ExtractionLogRecord(
            input_transcript=transcript,
            clean_transcript="",
            language_hint=preprocessed.language_hint,
            final_output=final,
            elapsed_ms=elapsed_ms,
            path_used="none",
        ))
        return final

    # Stage 2: Rule engine.
    regex_candidates = extract_regex_candidates(cleaned)
    best_regex = regex_candidates[0].name if regex_candidates else None
    regex_score = get_best_regex_score(regex_candidates)

    # Stage 2 short-circuit: high-confidence regex + validation.
    short_circuit = try_regex_short_circuit(cleaned, twilio_confidence)
    if short_circuit and short_circuit.found:
        elapsed_ms = (time.perf_counter() - start) * 1000
        final = {
            "found": True,
            "name": short_circuit.name,
            "confidence": short_circuit.confidence,
            "reason": short_circuit.reason,
        }
        log_extraction(ExtractionLogRecord(
            input_transcript=transcript,
            clean_transcript=cleaned,
            language_hint=preprocessed.language_hint,
            regex_candidate=best_regex,
            regex_score=regex_score,
            validation_ok=True,
            validation_reason="Valid Indian name.",
            final_output=final,
            elapsed_ms=elapsed_ms,
            path_used=short_circuit.path_used,
        ))
        return final

    # Stage 4: Gemini call.
    gemini_output = call_gemini(
        cleaned_transcript=cleaned,
        language_hint=preprocessed.language_hint,
        regex_candidate=best_regex,
        twilio_confidence=twilio_confidence,
    )

    # Stage 5–8: Postprocess, validate, confidence, fallback.
    if gemini_output and gemini_output.get("found"):
        resolved = resolve_from_gemini(gemini_output, twilio_confidence, regex_score)
        if resolved.found:
            elapsed_ms = (time.perf_counter() - start) * 1000
            final = {
                "found": True,
                "name": resolved.name,
                "confidence": resolved.confidence,
                "reason": resolved.reason,
            }
            log_extraction(ExtractionLogRecord(
                input_transcript=transcript,
                clean_transcript=cleaned,
                language_hint=preprocessed.language_hint,
                regex_candidate=best_regex,
                regex_score=regex_score,
                gemini_output=gemini_output,
                validation_ok=True,
                validation_reason="Valid Indian name.",
                final_output=final,
                elapsed_ms=elapsed_ms,
                path_used=resolved.path_used,
            ))
            return final

    # Gemini failed or returned invalid — regex fallback.
    regex_fallback = resolve_regex_fallback(cleaned, twilio_confidence)
    if regex_fallback and regex_fallback.found:
        elapsed_ms = (time.perf_counter() - start) * 1000
        final = {
            "found": True,
            "name": regex_fallback.name,
            "confidence": regex_fallback.confidence,
            "reason": regex_fallback.reason,
        }
        log_extraction(ExtractionLogRecord(
            input_transcript=transcript,
            clean_transcript=cleaned,
            language_hint=preprocessed.language_hint,
            regex_candidate=best_regex,
            regex_score=regex_score,
            gemini_output=gemini_output,
            validation_ok=True,
            validation_reason="Valid Indian name.",
            final_output=final,
            elapsed_ms=elapsed_ms,
            path_used=regex_fallback.path_used,
        ))
        return final

    # Heuristic fallback.
    heuristic = resolve_heuristic_fallback(cleaned, twilio_confidence)
    if heuristic and heuristic.found:
        elapsed_ms = (time.perf_counter() - start) * 1000
        final = {
            "found": True,
            "name": heuristic.name,
            "confidence": heuristic.confidence,
            "reason": heuristic.reason,
        }
        log_extraction(ExtractionLogRecord(
            input_transcript=transcript,
            clean_transcript=cleaned,
            language_hint=preprocessed.language_hint,
            regex_candidate=best_regex,
            regex_score=regex_score,
            gemini_output=gemini_output,
            validation_ok=True,
            validation_reason="Valid Indian name.",
            final_output=final,
            elapsed_ms=elapsed_ms,
            path_used=heuristic.path_used,
        ))
        return final

    # Nothing found.
    elapsed_ms = (time.perf_counter() - start) * 1000
    failure = not_found(
        reason=(
            gemini_output.get("reason", "No valid name found.")
            if gemini_output
            else "No valid name found in transcript."
        )
    )
    final = {
        "found": False,
        "name": "",
        "confidence": "low",
        "reason": failure.reason,
    }
    log_extraction(ExtractionLogRecord(
        input_transcript=transcript,
        clean_transcript=cleaned,
        language_hint=preprocessed.language_hint,
        regex_candidate=best_regex,
        regex_score=regex_score,
        gemini_output=gemini_output,
        validation_ok=False,
        validation_reason=failure.reason,
        final_output=final,
        elapsed_ms=elapsed_ms,
        path_used="none",
    ))
    return final
