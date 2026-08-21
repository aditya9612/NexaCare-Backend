"""
Stage 4 — Deterministic LLM call for name extraction.

Primary: Gemini. Fallback: OpenAI when Gemini fails or is not configured.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from google.genai import types

from app.agent.llm import (
    NameExtractionResult,
    _gemini_configured,
    _get_client,
    _get_model,
    openai_json_completion,
)
from app.agent.name_extraction.prompt import NAME_SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger("nexacare.agent.name_extraction.gemini")


def _normalise_name_result(result: dict[str, Any]) -> dict[str, Any]:
    conf = result.get("confidence", "low")
    if hasattr(conf, "value"):
        conf = conf.value
    result["confidence"] = str(conf).lower()

    if not isinstance(result.get("found"), bool):
        result["found"] = bool(result.get("name", "").strip())
    if not result.get("name", "").strip():
        result["found"] = False
        result["name"] = ""

    return result


def call_gemini(
    cleaned_transcript: str,
    language_hint: str,
    regex_candidate: str | None = None,
    twilio_confidence: float = -1.0,
) -> dict[str, Any] | None:
    """
    Call Gemini (then OpenAI fallback) for name extraction.

    Returns parsed dict matching NameExtractionResult, or None on failure.
    """
    if not cleaned_transcript or not cleaned_transcript.strip():
        return None

    user_prompt = build_user_prompt(
        cleaned_transcript=cleaned_transcript,
        language_hint=language_hint,
        regex_candidate=regex_candidate,
        twilio_confidence=twilio_confidence,
    )

    if _gemini_configured():
        try:
            client = _get_client()
            model = _get_model()

            response = client.models.generate_content(
                model=model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=NAME_SYSTEM_PROMPT,
                    temperature=0.0,
                    top_p=0.1,
                    top_k=1,
                    max_output_tokens=80,
                    response_mime_type="application/json",
                    response_schema=NameExtractionResult,
                ),
            )

            if not response.text:
                logger.warning("Gemini returned empty response for name extraction")
            else:
                return _normalise_name_result(json.loads(response.text))

        except Exception as exc:
            logger.warning("Gemini name extraction failed: %s — trying OpenAI", exc)
    else:
        logger.info("Name extraction: Gemini not configured — trying OpenAI")

    try:
        result = openai_json_completion(
            system_prompt=NAME_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            schema=NameExtractionResult,
            temperature=0.0,
            max_completion_tokens=80,
        )
        logger.info("Name extraction succeeded via OpenAI fallback")
        return _normalise_name_result(result)
    except Exception as exc:
        logger.warning("OpenAI name extraction failed: %s", exc)
        return None
