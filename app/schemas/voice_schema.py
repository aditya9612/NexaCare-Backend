from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import Field

from app.schemas.common_schema import BaseSchema


class ScheduleCallRequest(BaseSchema):
    patient_id: int
    appointment_id: Optional[int] = None
    phone_number: str = Field(..., min_length=10, max_length=20)
    call_type: str = "reminder"
    language: str = "en"
    scheduled_time: datetime


class StartCallRequest(BaseSchema):
    call_id: int


class RetryCallRequest(BaseSchema):
    call_id: int


class VoiceCallResponse(BaseSchema):
    id: int
    patient_id: Optional[int] = None
    appointment_id: Optional[int] = None
    hospital_id: Optional[int] = None
    phone_number: str
    call_type: str
    language: str
    scheduled_time: datetime
    call_status: str
    retry_count: int
    provider: Optional[str] = None
    intent: Optional[str] = None
    faq_hit: bool = False
    ai_fallback: bool = False
    transferred_to_reception: bool = False
    booking_success: bool = False
    created_at: datetime


class VoiceCallLogResponse(BaseSchema):
    id: int
    call_id: int
    event_type: str
    event_data: Optional[str] = None
    created_at: datetime


class VoiceResponseSchema(BaseSchema):
    id: int
    call_id: int
    response_type: str
    response_value: str
    captured_at: datetime


class CallActionRequest(BaseSchema):
    call_id: int
    response_value: Optional[str] = None


class RescheduleViaVoiceRequest(BaseSchema):
    call_id: int
    new_scheduled_time: datetime


class CallAnalyticsResponse(BaseSchema):
    total_calls: int
    completed_calls: int
    failed_calls: int
    pending_calls: int
    busy_calls: int
    avg_duration_seconds: float
    confirmation_rate: float
    status_breakdown: List[Dict[str, Any]]
    language_breakdown: List[Dict[str, Any]]
