"""
FaqMemory — Redis-backed FAQ interaction memory (call-scoped).

Key: voice:faq_memory:{session_id}
TTL: 3600 seconds (aligned with voice agent sessions)

Fields: last_topic, language, last_question, question_count, last_answer

Integration:
- Updated by RagFaqService when session_id is provided
- Isolated from booking Redis keys (voice_agent:*, voice_assistant:*)
- Does not write BookingCallState or call conversation.update_memory
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

from app.utils.redis_service import cache_delete, cache_get, cache_set

_FAQ_MEMORY_TTL = 3600


@dataclass
class FaqMemoryState:
    last_topic: Optional[str] = None
    language: Optional[str] = None
    last_question: Optional[str] = None
    question_count: int = 0
    last_answer: Optional[str] = None


class FaqMemory:
    """Load/update FAQ-only memory for a voice session."""

    @staticmethod
    def _key(session_id: str) -> str:
        return f"voice:faq_memory:{session_id}"

    async def get(self, session_id: str) -> FaqMemoryState:
        if not session_id:
            return FaqMemoryState()
        data = await cache_get(self._key(session_id))
        if not isinstance(data, dict):
            return FaqMemoryState()
        return FaqMemoryState(
            last_topic=data.get("last_topic"),
            language=data.get("language"),
            last_question=data.get("last_question"),
            question_count=int(data.get("question_count") or 0),
            last_answer=data.get("last_answer"),
        )

    async def update(
        self,
        session_id: str,
        *,
        question: str,
        answer: str,
        language: str,
        topic: str | None = None,
    ) -> FaqMemoryState:
        """Increment question_count and store last FAQ turn fields."""
        if not session_id:
            return FaqMemoryState()
        state = await self.get(session_id)
        state.last_question = (question or "")[:500]
        state.last_answer = (answer or "")[:2000]
        state.language = language or state.language or "en"
        state.last_topic = (topic or question or "")[:200]
        state.question_count = int(state.question_count or 0) + 1
        await cache_set(self._key(session_id), asdict(state), ttl=_FAQ_MEMORY_TTL)
        return state

    async def clear(self, session_id: str) -> None:
        if session_id:
            await cache_delete(self._key(session_id))
