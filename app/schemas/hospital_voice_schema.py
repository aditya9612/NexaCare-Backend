from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import Field

from app.core.constants import TelephonyProviderType, VoiceGender, VoiceLanguage
from app.schemas.common_schema import BaseSchema


class HospitalVoiceConfigCreate(BaseSchema):
    hospital_id: int
    telephony_provider: str = TelephonyProviderType.TWILIO
    voice_gender: str = VoiceGender.FEMALE
    voice_profile: Optional[str] = None
    default_language: str = VoiceLanguage.EN
    reception_number: Optional[str] = None
    retry_count: int = Field(default=3, ge=0, le=10)
    from_number: Optional[str] = None
    inbound_did: Optional[str] = None
    exotel_sid: Optional[str] = None
    exotel_api_key: Optional[str] = None
    exotel_api_token: Optional[str] = None
    exotel_subdomain: Optional[str] = None
    is_active: bool = True


class HospitalVoiceConfigUpdate(BaseSchema):
    telephony_provider: Optional[str] = None
    voice_gender: Optional[str] = None
    voice_profile: Optional[str] = None
    default_language: Optional[str] = None
    reception_number: Optional[str] = None
    retry_count: Optional[int] = Field(default=None, ge=0, le=10)
    from_number: Optional[str] = None
    inbound_did: Optional[str] = None
    exotel_sid: Optional[str] = None
    exotel_api_key: Optional[str] = None
    exotel_api_token: Optional[str] = None
    exotel_subdomain: Optional[str] = None
    is_active: Optional[bool] = None


class HospitalVoiceConfigResponse(BaseSchema):
    id: int
    hospital_id: int
    telephony_provider: str
    voice_gender: str
    voice_profile: Optional[str] = None
    default_language: str
    reception_number: Optional[str] = None
    retry_count: int
    from_number: Optional[str] = None
    inbound_did: Optional[str] = None
    is_active: bool
    created_at: datetime


class HospitalFaqCreate(BaseSchema):
    hospital_id: int
    question: str
    answer: str
    language: str = VoiceLanguage.EN
    tags: Optional[str] = None
    is_active: bool = True


class HospitalFaqUpdate(BaseSchema):
    question: Optional[str] = None
    answer: Optional[str] = None
    language: Optional[str] = None
    tags: Optional[str] = None
    is_active: Optional[bool] = None


class HospitalFaqResponse(BaseSchema):
    id: int
    hospital_id: int
    question: str
    answer: str
    language: str
    tags: Optional[str] = None
    is_active: bool
    created_at: datetime


class HospitalPolicyCreate(BaseSchema):
    hospital_id: int
    title: str
    body: str
    language: str = VoiceLanguage.EN
    category: Optional[str] = None
    is_active: bool = True


class HospitalPolicyUpdate(BaseSchema):
    title: Optional[str] = None
    body: Optional[str] = None
    language: Optional[str] = None
    category: Optional[str] = None
    is_active: Optional[bool] = None


class HospitalPolicyResponse(BaseSchema):
    id: int
    hospital_id: int
    title: str
    body: str
    language: str
    category: Optional[str] = None
    is_active: bool
    created_at: datetime


class HospitalVoiceDocumentCreate(BaseSchema):
    hospital_id: int
    title: str
    content: str
    source: Optional[str] = None
    language: str = VoiceLanguage.EN
    is_active: bool = True


class HospitalVoiceDocumentUpdate(BaseSchema):
    title: Optional[str] = None
    content: Optional[str] = None
    source: Optional[str] = None
    language: Optional[str] = None
    is_active: Optional[bool] = None


class HospitalVoiceDocumentResponse(BaseSchema):
    id: int
    hospital_id: int
    title: str
    content: str
    source: Optional[str] = None
    language: str
    is_active: bool
    created_at: datetime


class VoiceCallbackTicketResponse(BaseSchema):
    id: int
    hospital_id: Optional[int] = None
    patient_id: Optional[int] = None
    call_id: Optional[int] = None
    phone: str
    reason: Optional[str] = None
    status: str
    language: str
    created_at: datetime


class VoiceAnalyticsSummary(BaseSchema):
    total_calls: int = 0
    booking_success: int = 0
    language_distribution: List[Dict[str, Any]] = Field(default_factory=list)
    transfer_count: int = 0
    avg_duration_seconds: float = 0.0
    faq_success: int = 0
    ai_fallback: int = 0
    retry_count: int = 0
    completed_calls: int = 0
    failed_calls: int = 0
    provider_breakdown: List[Dict[str, Any]] = Field(default_factory=list)
    twilio_calls: int = 0
    exotel_calls: int = 0
    twilio_success_rate: float = 0.0
    exotel_success_rate: float = 0.0
