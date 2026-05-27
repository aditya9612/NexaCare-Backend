from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import Field

from app.schemas.appointment_schema import AppointmentCreate
from app.schemas.common_schema import BaseSchema


class ChatSessionCreate(BaseSchema):
    patient_id: int
    language: str = "en"


class ChatSessionResponse(BaseSchema):
    id: int
    session_id: str
    patient_id: int
    language: str
    session_status: str
    started_at: datetime
    ended_at: Optional[datetime] = None
    sentiment_score: Optional[float] = None


class SendMessageRequest(BaseSchema):
    session_id: str
    message: str
    message_type: str = "Text"
    language: Optional[str] = None


class ChatMessageResponse(BaseSchema):
    id: int
    session_id: int
    sender_type: str
    message: str
    message_type: str
    sent_at: datetime


class ChatHistoryResponse(BaseSchema):
    session: ChatSessionResponse
    messages: List[ChatMessageResponse]


class SymptomAnalysisRequest(BaseSchema):
    session_id: Optional[str] = None
    symptoms: List[str] = Field(..., min_length=1)
    language: str = "en"


class SymptomAnalysisResponse(BaseSchema):
    symptoms: List[str]
    possible_conditions: List[str]
    recommended_specialist: str
    urgency: str
    disclaimer: str = "This is not a medical diagnosis. Please consult a physician."


class ChatBookAppointmentRequest(BaseSchema):
    session_id: str
    appointment: AppointmentCreate


class EscalateHumanRequest(BaseSchema):
    session_id: str
    reason: Optional[str] = None


class ChatIntentResponse(BaseSchema):
    id: int
    session_id: int
    intent_name: str
    confidence_score: float
    detected_entities: Optional[str] = None
    created_at: datetime


class AIResponseSchema(BaseSchema):
    id: int
    session_id: int
    response_text: str
    response_type: str
    confidence_score: float
    created_at: datetime


class SendMessageResponse(BaseSchema):
    user_message: ChatMessageResponse
    bot_message: ChatMessageResponse
    intent: Optional[ChatIntentResponse] = None
    ai_response: Optional[AIResponseSchema] = None
    booking_state: Optional[Dict[str, Any]] = None
    suggested_slots: Optional[List[Dict[str, Any]]] = None
    appointment: Optional[Dict[str, Any]] = None


class BookingStateResponse(BaseSchema):
    step: str
    patient_id: int
    symptoms: Optional[str] = None
    recommended_specialist: Optional[str] = None
    doctor_id: Optional[int] = None
    doctor_name: Optional[str] = None
    department_id: Optional[int] = None
    appointment_date: Optional[str] = None
    appointment_time: Optional[str] = None
    consultation_type: Optional[str] = None


class ChatAnalyticsResponse(BaseSchema):
    total_sessions: int
    active_sessions: int
    escalated_sessions: int
    total_messages: int
    top_intents: List[Dict[str, Any]]
    avg_messages_per_session: float
    booking_conversions: int = 0
    booking_conversion_rate: float = 0.0
