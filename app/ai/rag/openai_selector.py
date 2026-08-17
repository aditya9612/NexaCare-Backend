"""
OpenAITop5Selector — grounded KB selector over retrieved Top-5 entries only.

Reply formats:
- MATCH:faq|policy|document:<id>
- CLARIFY:<short question>
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
    r"^MATCH:(faq|policy|document):(\d+)\s*$",
    re.IGNORECASE,
)
_CLARIFY_PREFIX = re.compile(r"^CLARIFY:\s*(.+)$", re.IGNORECASE | re.DOTALL)


@dataclass
class SelectorResult:
    kind: str  # match | clarify | no_answer | error
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
            "CLARIFY:<short clarification question in the patient's language>\n"
            "NO_ANSWER\n"
            "Do not include any other text."
        )
        user = (
            f"Retrieved knowledge (Top-5 only):\n{catalog}\n\n"
            f"Patient language: {language}\n"
            f"Patient question: {question}"
        )
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            response = await client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.0,
                max_tokens=80,
            )
            text = (response.choices[0].message.content or "").strip()
        except Exception as exc:
            logger.warning("OpenAITop5Selector failed: %s", exc)
            return SelectorResult(kind="error", text=str(exc))

        if text.upper() == "NO_ANSWER":
            return SelectorResult(kind="no_answer")

        match = _MATCH_PREFIX.match(text)
        if match:
            source = match.group(1).lower()
            entry_id = int(match.group(2))
            if (source, entry_id) not in allowed:
                return SelectorResult(kind="no_answer")
            for chunk in chunks:
                if chunk.source == source and chunk.id == entry_id:
                    return SelectorResult(
                        kind="match",
                        source=source,
                        entry_id=entry_id,
                        text=chunk.text,
                    )
            return SelectorResult(kind="no_answer")

        clarify = _CLARIFY_PREFIX.match(text)
        if clarify:
            return SelectorResult(
                kind="clarify",
                clarify_question=clarify.group(1).strip()[:300],
            )

        return SelectorResult(kind="no_answer")
