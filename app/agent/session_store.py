"""
app/agent/session_store.py
--------------------------
In-memory session store for active calls, keyed by Twilio CallSid.

Replace with Redis in production for multi-worker deployments:
    await redis.set(call_sid, json.dumps(state), ex=3600)
    state = json.loads(await redis.get(call_sid))
"""

import logging
from typing import Optional
from app.agent.state import BookingCallState

logger = logging.getLogger("nexacare.agent.session")

# Global in-memory store: { call_sid: BookingCallState }
_sessions: dict[str, BookingCallState] = {}


def create_session(call_sid: str, from_number: str, base_url: str) -> BookingCallState:
    """Create a fresh session for a new incoming call."""
    state = BookingCallState(
        call_sid=call_sid,
        from_number=from_number,
        step="language_select",
        language="en",
        twilio_language="en-IN",
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
        retry_count=0,
        error_message=None,
        base_url=base_url,
        audio_stream_sid=None,
        conversation_history=None,
    )
    _sessions[call_sid] = state
    logger.info(f"[{call_sid}] Session created | from={from_number}")
    return state


def get_session(call_sid: str) -> Optional[BookingCallState]:
    """Return existing session or None if not found."""
    return _sessions.get(call_sid)


def update_session(call_sid: str, updates: dict) -> BookingCallState:
    """Merge updates into the session and return the new state."""
    session = _sessions.get(call_sid)
    if session is None:
        raise KeyError(f"No active session for CallSid: {call_sid}")
    session.update(updates)
    _sessions[call_sid] = session
    return session


def delete_session(call_sid: str) -> None:
    """Remove session after call ends or booking is confirmed."""
    removed = _sessions.pop(call_sid, None)
    if removed:
        logger.info(f"[{call_sid}] Session deleted")


def active_session_count() -> int:
    return len(_sessions)