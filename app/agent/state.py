"""
app/agent/state.py
------------------
Single TypedDict that flows through every voice agent node.
Each field is populated progressively as the call advances.
"""

from typing import Optional
from typing_extensions import TypedDict


class BookingCallState(TypedDict):
    # ── Call metadata ──────────────────────────────────────────────────────
    call_sid: str                        # Twilio unique call ID
    from_number: str                     # Caller's phone number
    step: str                            # Current node name

    # ── Language ───────────────────────────────────────────────────────────
    language: str                        # "en" | "hi" | "mr"  (default "en")
    twilio_language: str                 # "en-IN" | "hi-IN" | "mr-IN"
    language_locked: bool                # True after resolver / DTMF
    language_source: Optional[str]       # preferred | temp_store | dtmf | ai_fallback | ...

    # ── Hospital / production config (from HospitalVoiceConfigService) ─────
    hospital_id: Optional[int]
    hospital_resolution_source: Optional[str]  # did_match | dev_single_hospital_fallback | ...
    to_number: Optional[str]                     # inbound DID (Twilio To) for safe re-resolution
    voice_profile: Optional[str]
    voice_gender: Optional[str]
    reception_number: Optional[str]
    patient_id: Optional[int]

    # ── Service selection ──────────────────────────────────────────────────
    service: Optional[str]               # "book" | "reschedule" | "cancel" | "faq"

    # ── Patient info (collected via STT) ──────────────────────────────────
    patient_name: Optional[str]
    problem_description: Optional[str]

    # ── AI analysis (from Groq) ────────────────────────────────────────────
    detected_specialty: Optional[str]    # e.g. "Cardiology"
    specialty_confidence: Optional[str]  # "high" | "medium" | "low"
    specialty_reasoning: Optional[str]

    # ── Doctor selection (from DB) ─────────────────────────────────────────
    suggested_doctors: Optional[list]    # list of doctor dicts from DB
    selected_doctor_id: Optional[int]
    selected_doctor_name: Optional[str]
    selected_doctor_specialization: Optional[str]

    # ── Slot selection ─────────────────────────────────────────────────────
    available_slots: Optional[list]      # list of slot dicts
    selected_slot: Optional[dict]        # {date, time, doctor_id}

    # ── Appointment ────────────────────────────────────────────────────────
    appointment_id: Optional[int]
    appointment_number: Optional[str]
    booking_attempt_id: Optional[str]     # idempotency key for voice booking

    # ── Phase 6 conversation memory ────────────────────────────────────────
    current_topic: Optional[str]
    last_question: Optional[str]
    last_answer: Optional[str]
    current_intent: Optional[str]
    question_count: int
    current_language: Optional[str]
    call_started_at: Optional[str]       # ISO timestamp UTC
    return_step: Optional[str]           # booking resume point after FAQ detour
    return_service: Optional[str]

    # ── Phase 6 analytics counters (session-scoped) ────────────────────────
    faq_count: int
    booking_count: int
    transfer_count: int
    unknown_count: int
    faq_topics: Optional[list]

    # ── Flow control ───────────────────────────────────────────────────────
    retry_count: int                     # retries within current step
    error_message: Optional[str]

    # ── Base URL (set at startup via ngrok or real domain) ─────────────────
    base_url: str                        # e.g. "https://xxxx.ngrok-free.app"

    # ── Gemini Live API fields ─────────────────────────────────────────────
    audio_stream_sid: Optional[str]      # Twilio Media Stream SID
    conversation_history: Optional[list] # Multi-turn context from live session
    conversation_analytics: Optional[list]  # lightweight event log (capped)
