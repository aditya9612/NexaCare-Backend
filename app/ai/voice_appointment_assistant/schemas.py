from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class VoiceIntent(str, Enum):
    BOOK = "book"
    RESCHEDULE = "reschedule"
    CANCEL = "cancel"
    AVAILABILITY = "availability"
    HOSPITAL_INFO = "hospital_info"
    RECEPTION = "reception"
    UNKNOWN = "unknown"


class VoiceStep(str, Enum):
    GREET = "greet"
    LANGUAGE_SELECT = "language_select"
    INTENT = "intent"
    BOOK_NAME = "book_name"
    BOOK_DOCTOR = "book_doctor"
    BOOK_SYMPTOMS = "book_symptoms"
    BOOK_DATE = "book_date"
    BOOK_TIME = "book_time"
    BOOK_MOBILE = "book_mobile"
    BOOK_CONFIRM = "book_confirm"
    RESCHEDULE_MOBILE = "reschedule_mobile"
    RESCHEDULE_DATE = "reschedule_date"
    RESCHEDULE_TIME = "reschedule_time"
    RESCHEDULE_CONFIRM = "reschedule_confirm"
    CANCEL_MOBILE = "cancel_mobile"
    CANCEL_CONFIRM = "cancel_confirm"
    AVAILABILITY_QUERY = "availability_query"
    FAQ_QUESTION = "faq_question"
    DONE = "done"
    EMERGENCY = "emergency"
    TRANSFER = "transfer"


class VoiceState(BaseModel):
    call_sid: str = ""
    from_number: str = ""
    language: str = "en"
    language_locked: bool = False
    language_source: str = ""
    step: VoiceStep = VoiceStep.GREET
    intent: VoiceIntent = VoiceIntent.UNKNOWN

    hospital_id: Optional[int] = None
    provider: str = "twilio"
    voice_call_id: Optional[int] = None

    patient_name: Optional[str] = None
    doctor_or_department: Optional[str] = None
    symptoms: Optional[str] = None
    appointment_date: Optional[str] = None
    appointment_time: Optional[str] = None
    mobile_number: Optional[str] = None

    doctor_id: Optional[int] = None
    patient_id: Optional[int] = None
    appointment_id: Optional[int] = None

    pending_booking: bool = False
    booking_completed: bool = False
    faq_hit: bool = False
    ai_fallback: bool = False
    last_confidence: Optional[float] = None
    transfer_requested: bool = False
    faq_answer: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = self.model_dump(mode="json")
        data["step"] = self.step.value
        data["intent"] = self.intent.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VoiceState":
        payload = dict(data)
        if "step" in payload and isinstance(payload["step"], str):
            payload["step"] = VoiceStep(payload["step"])
        if "intent" in payload and isinstance(payload["intent"], str):
            payload["intent"] = VoiceIntent(payload["intent"])
        return cls.model_validate(payload)


class VoiceBookingPayload(BaseModel):
    patient_name: str = ""
    doctor_or_department: str = ""
    symptoms: str = ""
    appointment_date: str = ""
    appointment_time: str = ""
    mobile_number: str = ""
    language: str = ""

    @classmethod
    def from_state(cls, state: VoiceState) -> "VoiceBookingPayload":
        return cls(
            patient_name=state.patient_name or "",
            doctor_or_department=state.doctor_or_department or "",
            symptoms=state.symptoms or "",
            appointment_date=state.appointment_date or "",
            appointment_time=state.appointment_time or "",
            mobile_number=state.mobile_number or "",
            language=state.language or "en",
        )


class VoiceTurnResult(BaseModel):
    prompt: str
    state: VoiceState
    hangup: bool = False
    use_dtmf_menu: bool = False
    booking_json: Optional[VoiceBookingPayload] = None
