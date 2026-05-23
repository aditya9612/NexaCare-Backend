from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import Field

from app.schemas.common_schema import BaseSchema


class SendMessageRequest(BaseSchema):
    patient_id: Optional[int] = None
    phone_number: str = Field(..., min_length=10, max_length=20)
    message_content: str
    message_type: str = "Text"
    media_url: Optional[str] = None


class SendTemplateRequest(BaseSchema):
    patient_id: Optional[int] = None
    phone_number: str
    template_name: str
    variables: Dict[str, str] = Field(default_factory=dict)


class SendMediaRequest(BaseSchema):
    patient_id: Optional[int] = None
    phone_number: str
    message_type: str = "PDF"
    media_url: str
    caption: Optional[str] = None


class SendReminderRequest(BaseSchema):
    patient_id: int
    appointment_id: int
    phone_number: Optional[str] = None


class BroadcastRequest(BaseSchema):
    campaign_name: str
    message_content: str
    phone_numbers: List[str] = Field(..., min_length=1)
    template_name: Optional[str] = None
    scheduled_at: Optional[datetime] = None


class WhatsAppMessageResponse(BaseSchema):
    id: int
    patient_id: Optional[int] = None
    phone_number: str
    message_type: str
    message_content: str
    media_url: Optional[str] = None
    delivery_status: str
    sent_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    read_at: Optional[datetime] = None
    created_at: datetime


class DeliveryStatusResponse(BaseSchema):
    message_id: int
    delivery_status: str
    sent_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    read_at: Optional[datetime] = None
    events: List[Dict[str, Any]]


class WhatsAppAnalyticsResponse(BaseSchema):
    total_sent: int
    total_delivered: int
    total_read: int
    total_failed: int
    delivery_rate: float
    read_rate: float
    message_type_breakdown: List[Dict[str, Any]]


class WebhookPayload(BaseSchema):
    provider_message_id: Optional[str] = None
    phone_number: Optional[str] = None
    status: Optional[str] = None
    timestamp: Optional[datetime] = None
    raw: Dict[str, Any] = Field(default_factory=dict)
