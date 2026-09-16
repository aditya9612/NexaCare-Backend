"""
OpenAITop5Selector — grounded KB selector over retrieved Top-5 entries only.

Reply formats:
- MATCH:faq|policy|document:<id>
- NO_ANSWER

Never invent fees, timings, or clinical advice. Spoken answers are resolved
verbatim from the Top-5 chunk texts by the caller.

Integration: RagFaqService when confidence >= FAQ_CONFIDENCE_ANSWER.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from app.ai.rag.retriever import RetrievedChunk
from app.core.config import settings
from app.core.logger import logger

_MATCH_PREFIX = re.compile(
    r"^MATCH:(faq|policy|document|document_chunk):(\d+)\s*$",
    re.IGNORECASE,
)


@dataclass
class SelectorResult:
    kind: str  # match | no_answer | invalid_id | error
    source: Optional[str] = None
    entry_id: Optional[int] = None
    text: str = ""
    clarify_question: str = ""


class OpenAITop5Selector:
    """Select one of the Top-5 retrieved KB entries via OpenAI chat."""

    async def select(
        self,
        question: str,
        chunks: list[RetrievedChunk],
        language: str = "en",
        normalized_question: str | None = None,
    ) -> SelectorResult:
        if not chunks:
            return SelectorResult(kind="no_answer")
        if not settings.OPENAI_API_KEY:
            return SelectorResult(kind="error", text="missing_api_key")

        allowed = {(c.source, c.id) for c in chunks}
        catalog = "\n\n".join(c.label for c in chunks[:5])
        system = (
            "You are a hospital voice FAQ selector for an Indian hospital. "
            "You may ONLY use the retrieved knowledge entries provided below. "
            "Never invent information. Never diagnose or prescribe. "
            "Reply with ONLY one of these formats:\n"
            "MATCH:faq:<id>\n"
            "MATCH:policy:<id>\n"
            "MATCH:document:<id>\n"
            "MATCH:document_chunk:<id>\n"
            "NO_ANSWER\n"
            "Do not include any other text."
        )
        user = (
            f"Retrieved knowledge (Top-5 only):\n{catalog}\n\n"
            f"Patient language: {language}\n"
            f"Patient question: {question}\n"
            f"Normalized question (retrieval): {normalized_question or question}"
        )
        try:
            from openai import AsyncOpenAI
            import time

            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            
            start_time = time.perf_counter()
            response = await client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_completion_tokens=200,
            )
            latency_ms = (time.perf_counter() - start_time) * 1000
            
            # Extract tokens
            usage = getattr(response, "usage", None)
            prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
            completion_tokens = getattr(usage, "completion_tokens", None) if usage else None
            total_tokens = getattr(usage, "total_tokens", None) if usage else None
            
            logger.info(
                "faq_ai_openai_usage",
                extra={
                    "event": "faq_ai_openai_usage",
                    "operation": "selector",
                    "model": settings.OPENAI_MODEL,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                    "latency_ms": round(latency_ms, 2),
                    "status": "success",
                }
            )

            text = (response.choices[0].message.content or "").strip()
        except Exception as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000 if 'start_time' in locals() else None
            
            from openai import RateLimitError, AuthenticationError, APIConnectionError, APITimeoutError, BadRequestError, OpenAIError
            
            error_type = "unexpected_error"
            client_msg = "AI service unavailable"
            
            if isinstance(exc, RateLimitError):
                error_type = "rate_limit"
                client_msg = "temporary AI service limitation"
            elif isinstance(exc, AuthenticationError):
                error_type = "authentication"
                client_msg = "AI service configuration unavailable"
            elif isinstance(exc, APITimeoutError):
                error_type = "timeout"
                client_msg = "AI service temporarily unavailable"
            elif isinstance(exc, APIConnectionError):
                error_type = "connection"
                client_msg = "AI service temporarily unavailable"
            elif isinstance(exc, BadRequestError):
                error_type = "bad_request"
                client_msg = "AI request could not be processed"
            elif isinstance(exc, OpenAIError):
                error_type = "openai_error"
                client_msg = "AI service unavailable"

            logger.warning(
                "OpenAITop5Selector failed [%s]: %s", error_type, type(exc).__name__,
                extra={
                    "event": "faq_ai_openai_error",
                    "operation": "selector",
                    "model": settings.OPENAI_MODEL,
                    "error_type": error_type,
                    "latency_ms": round(latency_ms, 2) if latency_ms else None,
                    "status": "error",
                }
            )
            return SelectorResult(kind="error", text=client_msg)

        if text.upper() == "NO_ANSWER":
            return SelectorResult(kind="no_answer")

        match = _MATCH_PREFIX.match(text)
        if match:
            source = match.group(1).lower()
            entry_id = int(match.group(2))
            if (source, entry_id) not in allowed:
                return SelectorResult(kind="invalid_id", source=source, entry_id=entry_id)
            for chunk in chunks:
                if chunk.source == source and chunk.id == entry_id:
                    return SelectorResult(
                        kind="match",
                        source=source,
                        entry_id=entry_id,
                        text=chunk.text,
                    )
            return SelectorResult(kind="invalid_id", source=source, entry_id=entry_id)

        return SelectorResult(kind="no_answer")
