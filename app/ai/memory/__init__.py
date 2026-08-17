"""
app/ai/memory — lightweight FAQ-only conversation memory in Redis.

Stores: last_topic, language, last_question, question_count, last_answer.
Does NOT modify BookingCallState booking fields or Phase 6 conversation.py.
"""

from app.ai.memory.faq_memory import FaqMemory, FaqMemoryState

__all__ = ["FaqMemory", "FaqMemoryState"]
