from datetime import date, datetime, time
from typing import Any
from pydantic import BaseModel, EmailStr, Field

from app.core.constants import (
    EmailCampaignStatus,
    EmailDeliveryStatus,
    EmailMessageType,
    EmailSourceType,
)


# --- Request Schemas ---

class SendTemplateEmailRequest(BaseModel):
    patient_ids: list[int] = Field(..., min_items=1, description="List of patient IDs")
    template_name: str = Field(..., description="Name or code of template e.g. EMLT-2")
    language: str = Field(default="en", description="Language code")
    variables: dict[str, Any] = Field(default_factory=dict, description="Custom template variables")


class SendMediaEmailRequest(BaseModel):
    patient_ids: list[int] = Field(..., min_items=1, description="List of patient IDs")
    message_type: EmailMessageType = Field(default=EmailMessageType.PDF, description="PDF, IMAGE, ATTACHMENT")
    media_url: str = Field(..., description="Public or accessible URL of the file/media")
    caption: str | None = Field(None, description="Optional caption / message text")


class SendEmailReminderRequest(BaseModel):
    patient_ids: list[int] = Field(..., min_items=1, description="List of patient IDs")
    custom_notes: str | None = Field(None, description="Optional notes to include in reminder")
    force_async: bool = Field(default=False, description="Force background processing via Celery")


class SendDirectEmailRequest(BaseModel):
    to_email: EmailStr = Field(..., description="Recipient email address")
    subject: str = Field(..., min_length=1, description="Email subject")
    body_html: str = Field(..., min_length=1, description="HTML email body")
    body_text: str | None = Field(None, description="Plain text fallback")


class BroadcastEmailRequest(BaseModel):
    campaign_name: str = Field(..., min_length=1, description="Name of the broadcast campaign")
    message_content: str | None = Field(None, description="Direct broadcast HTML/text content")
    template_name: str | None = Field(None, description="Optional template name to use")
    emails: list[EmailStr] = Field(..., min_items=1, description="List of recipient email addresses")
    scheduled_at: datetime | None = Field(None, description="Optional UTC scheduled datetime")


# --- Result / Response Schemas ---

class PatientReminderResult(BaseModel):
    patient_id: int
    patient_name: str | None = None
    recipient_email: str | None = None
    status: EmailDeliveryStatus
    reason: str | None = None
    source_type: EmailSourceType | None = None
    event_id: int | None = None
    follow_up_date: date | None = None
    appointment_time: str | None = None
    message_id: int | None = None


class PatientEmailResult(BaseModel):
    patient_id: int
    patient_name: str | None = None
    recipient_email: str | None = None
    status: EmailDeliveryStatus
    reason: str | None = None
    message_id: int | None = None


class EmailBatchResponse(BaseModel):
    batch_id: str
    is_async: bool
    total_patients: int
    sent_count: int
    failed_count: int
    skipped_count: int
    results: list[PatientReminderResult | PatientEmailResult]
    message: str


class BroadcastResponse(BaseModel):
    campaign_id: int
    campaign_name: str
    status: EmailCampaignStatus
    scheduled_at: datetime | None = None
    total_recipients: int
    message: str


class EmailDeliveryLogResponse(BaseModel):
    id: int
    status: str
    details: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class EmailMessageResponse(BaseModel):
    id: int
    hospital_id: int | None = None
    batch_id: str | None = None
    campaign_id: int | None = None
    patient_id: int | None = None
    appointment_id: int | None = None
    discharge_id: int | None = None
    recipient_email: str
    subject: str
    body_html: str
    body_text: str | None = None
    media_url: str | None = None
    message_type: str
    source_type: str
    target_follow_up_date: date | None = None
    status: str
    failure_reason: str | None = None
    sent_at: datetime | None = None
    created_at: datetime
    deliveries: list[EmailDeliveryLogResponse] = []

    class Config:
        from_attributes = True

