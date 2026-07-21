from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import VoiceCallStatus, VoiceCallType, VoiceResponseType
from app.core.database import Base
from app.models.mixins import TimestampMixin


class VoiceCall(Base, TimestampMixin):
    __tablename__ = "voice_calls"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    patient_id: Mapped[int | None] = mapped_column(ForeignKey("patients.id"), nullable=True, index=True)
    appointment_id: Mapped[int | None] = mapped_column(ForeignKey("appointments.id"), nullable=True, index=True)
    hospital_id: Mapped[int | None] = mapped_column(ForeignKey("hospitals.id"), nullable=True, index=True)
    phone_number: Mapped[str] = mapped_column(String(20), index=True)
    call_type: Mapped[str] = mapped_column(String(50), default=VoiceCallType.REMINDER)
    language: Mapped[str] = mapped_column(String(10), default="en")
    scheduled_time: Mapped[datetime] = mapped_column(DateTime, index=True)
    call_status: Mapped[str] = mapped_column(String(50), default=VoiceCallStatus.PENDING, index=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    provider: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    provider_call_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    intent: Mapped[str | None] = mapped_column(String(50), nullable=True)
    faq_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    transferred_to_reception: Mapped[bool] = mapped_column(Boolean, default=False)
    transfer_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    booking_success: Mapped[bool] = mapped_column(Boolean, default=False)

    logs: Mapped[list["VoiceCallLog"]] = relationship(back_populates="call", cascade="all, delete-orphan")
    responses: Mapped[list["VoiceResponse"]] = relationship(back_populates="call", cascade="all, delete-orphan")


class VoiceCallLog(Base, TimestampMixin):
    __tablename__ = "voice_call_logs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    call_id: Mapped[int] = mapped_column(ForeignKey("voice_calls.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    event_data: Mapped[str | None] = mapped_column(Text, nullable=True)

    call: Mapped["VoiceCall"] = relationship(back_populates="logs")


class CallSchedule(Base, TimestampMixin):
    __tablename__ = "call_schedules"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    call_id: Mapped[int] = mapped_column(ForeignKey("voice_calls.id"), index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(100), nullable=True)


class VoiceResponse(Base):
    __tablename__ = "voice_responses"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    call_id: Mapped[int] = mapped_column(ForeignKey("voice_calls.id"), index=True)
    response_type: Mapped[str] = mapped_column(String(20), default=VoiceResponseType.DTMF)
    response_value: Mapped[str] = mapped_column(String(255))
    captured_at: Mapped[datetime] = mapped_column(DateTime, index=True)

    call: Mapped["VoiceCall"] = relationship(back_populates="responses")


class CallAnalytics(Base, TimestampMixin):
    __tablename__ = "call_analytics"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime, index=True)
    period_end: Mapped[datetime] = mapped_column(DateTime, index=True)
    total_calls: Mapped[int] = mapped_column(Integer, default=0)
    completed_calls: Mapped[int] = mapped_column(Integer, default=0)
    failed_calls: Mapped[int] = mapped_column(Integer, default=0)
    avg_duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    confirmation_rate: Mapped[float] = mapped_column(Float, default=0.0)
    language_breakdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    transfer_count: Mapped[int] = mapped_column(Integer, default=0)
    faq_success_count: Mapped[int] = mapped_column(Integer, default=0)
    ai_fallback_count: Mapped[int] = mapped_column(Integer, default=0)
    booking_success_count: Mapped[int] = mapped_column(Integer, default=0)
    retry_total: Mapped[int] = mapped_column(Integer, default=0)
