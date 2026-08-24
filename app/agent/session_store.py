"""
app/agent/session_store.py
--------------------------
Call session store keyed by Twilio CallSid.

Uses shared Redis helpers (cache_get / cache_set) with in-memory fallback
for multi-worker production — same pattern as VoiceAssistantService.
Namespace: voice_agent:{call_sid} (does not collide with voice_assistant:*).
"""

import logging
from typing import Optional

from app.agent.state import BookingCallState
from app.utils.redis_service import cache_delete, cache_get, cache_set

logger = logging.getLogger("nexacare.agent.session")

SESSION_TTL = 3600
_KEY_PREFIX = "voice_agent:"

# In-memory fallback when Redis is unavailable
_sessions: dict[str, BookingCallState] = {}


def _key(call_sid: str) -> str:
    return f"{_KEY_PREFIX}{call_sid}"


def _empty_state(call_sid: str, from_number: str, base_url: str) -> BookingCallState:
    return BookingCallState(
        call_sid=call_sid,
        from_number=from_number,
        step="language_select",
        language="en",
        twilio_language="en-IN",
        language_locked=False,
        language_source=None,
        hospital_id=None,
        hospital_resolution_source=None,
        to_number=None,
        voice_profile=None,
        voice_gender=None,
        reception_number=None,
        patient_id=None,
        service=None,
        patient_name=None,
        problem_description=None,
        detected_specialty=None,
        specialty_confidence=None,
        specialty_reasoning=None,
        suggested_doctors=None,
        selected_doctor_id=None,
        selected_doctor_name=None,
        selected_doctor_specialization=None,
        available_slots=None,
        selected_slot=None,
        appointment_id=None,
        appointment_number=None,
        booking_attempt_id=None,
        current_topic=None,
        last_question=None,
        last_answer=None,
        current_intent=None,
        question_count=0,
        current_language=None,
        call_started_at=None,
        return_step=None,
        return_service=None,
        faq_count=0,
        booking_count=0,
        transfer_count=0,
        unknown_count=0,
        faq_topics=None,
        retry_count=0,
        error_message=None,
        base_url=base_url,
        audio_stream_sid=None,
        conversation_history=None,
        conversation_analytics=None,
    )


async def _persist(call_sid: str, state: BookingCallState) -> None:
    payload = dict(state)
    saved = await cache_set(_key(call_sid), payload, ttl=SESSION_TTL)
    if not saved:
        _sessions[call_sid] = state
        logger.debug(
            "SESSION_UPDATED call_sid=%s step=%s hospital_id=%s redis_available=false",
            call_sid,
            state.get("step"),
            state.get("hospital_id"),
        )
    else:
        _sessions[call_sid] = state  # keep local mirror for active_session_count
        logger.debug(
            "SESSION_UPDATED call_sid=%s step=%s hospital_id=%s redis_available=true",
            call_sid,
            state.get("step"),
            state.get("hospital_id"),
        )


async def create_session(
    call_sid: str,
    from_number: str,
    base_url: str,
    **extra,
) -> BookingCallState:
    """Create a fresh session for a new incoming call."""
    state = _empty_state(call_sid, from_number, base_url)
    if extra:
        for k, v in extra.items():
            if k in state:
                state[k] = v  # type: ignore[literal-required]
    await _persist(call_sid, state)
    logger.info(
        "SESSION_CREATED call_sid=%s hospital_id=%s step=%s from=%s",
        call_sid,
        state.get("hospital_id"),
        state.get("step"),
        from_number,
    )
    return state


async def get_session(call_sid: str) -> Optional[BookingCallState]:
    """Return existing session or None if not found."""
    data = await cache_get(_key(call_sid))
    if data is None:
        return _sessions.get(call_sid)
    if not isinstance(data, dict):
        return _sessions.get(call_sid)
    # Ensure TypedDict-compatible dict; merge defaults for new fields
    base = _empty_state(
        data.get("call_sid", call_sid),
        data.get("from_number", ""),
        data.get("base_url", ""),
    )
    base.update({k: v for k, v in data.items() if k in base})
    _sessions[call_sid] = base
    return base


async def update_session(call_sid: str, updates: dict) -> BookingCallState:
    """Merge updates into the session and return the new state."""
    session = await get_session(call_sid)
    if session is None:
        raise KeyError(f"No active session for CallSid: {call_sid}")
    session.update(updates)
    await _persist(call_sid, session)
    return session


async def delete_session(call_sid: str) -> None:
    """Remove session after call ends or booking is confirmed."""
    session = _sessions.get(call_sid)
    if session:
        try:
            from app.agent.conversation import log_session_analytics_summary

            log_session_analytics_summary(session)
        except Exception:
            pass
    await cache_delete(_key(call_sid))
    removed = _sessions.pop(call_sid, None)
    if removed:
        logger.info(
            "SESSION_DELETED call_sid=%s hospital_id=%s step=%s",
            call_sid,
            (session or {}).get("hospital_id"),
            (session or {}).get("step"),
        )


def active_session_count() -> int:
    return len(_sessions)
