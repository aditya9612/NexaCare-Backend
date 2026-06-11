"""
app/agent/state.py
------------------
Single TypedDict that flows through every LangGraph node.
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

    # ── Service selection ──────────────────────────────────────────────────
    service: Optional[str]               # "book" | "reschedule" | "cancel"

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

    # ── Flow control ───────────────────────────────────────────────────────
    retry_count: int                     # retries within current step
    error_message: Optional[str]

    # ── Base URL (set at startup via ngrok or real domain) ─────────────────
    base_url: str                        # e.g. "https://xxxx.ngrok-free.app"