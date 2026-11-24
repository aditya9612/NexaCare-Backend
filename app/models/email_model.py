from datetime import date, datetime
from typing import Any
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.constants import EmailDeliveryStatus, EmailCampaignStatus, EmailMessageType, EmailSourceType
from app.models.mixins import TimestampMixin
from app.utils.helpers import utc_now


class EmailTemplate(Base, TimestampMixin):
    __tablename__ = "email_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hospital_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("hospitals.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    body_html: Mapped[str] = mapped_column(Text, nullable=False)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str] = mapped_column(String(20), default="en", nullable=False)
    variables: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True, nullable=False)

    campaigns = relationship("EmailCampaign", back_populates="template")


class EmailCampaign(Base, TimestampMixin):
    __tablename__ = "email_campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hospital_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("hospitals.id", ondelete="SET NULL"), nullable=True, index=True
    )
    campaign_name: Mapped[str] = mapped_column(String(255), nullable=False)
    template_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("email_templates.id", ondelete="SET NULL"), nullable=True, index=True
    )
    message_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), default=EmailCampaignStatus.DRAFT, index=True, nullable=False
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    total_recipients: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sent_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    template = relationship("EmailTemplate", back_populates="campaigns")
    messages = relationship("EmailMessage", back_populates="campaign")


class EmailBatch(Base, TimestampMixin):
    __tablename__ = "email_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    hospital_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("hospitals.id", ondelete="SET NULL"), nullable=True, index=True
    )
    batch_type: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="PENDING", index=True, nullable=False)
    total_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sent_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    results_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    messages = relationship("EmailMessage", back_populates="batch")


class EmailMessage(Base, TimestampMixin):
    __tablename__ = "email_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hospital_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("hospitals.id", ondelete="SET NULL"), nullable=True, index=True
    )
    batch_id: Mapped[str | None] = mapped_column(
        String(100), ForeignKey("email_batches.batch_id", ondelete="SET NULL"), nullable=True, index=True
    )
    campaign_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("email_campaigns.id", ondelete="SET NULL"), nullable=True, index=True
    )
    patient_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("patients.id", ondelete="SET NULL"), nullable=True, index=True
    )
    appointment_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    discharge_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("discharges.id", ondelete="SET NULL"), nullable=True, index=True
    )
    recipient_email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    body_html: Mapped[str] = mapped_column(Text, nullable=False)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    message_type: Mapped[str] = mapped_column(
        String(50), default=EmailMessageType.HTML, index=True, nullable=False
    )
    source_type: Mapped[str] = mapped_column(
        String(50), default=EmailSourceType.GENERAL, index=True, nullable=False
    )
    target_follow_up_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(190), unique=True, index=True, nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), default=EmailDeliveryStatus.PENDING, index=True, nullable=False
    )
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    batch = relationship("EmailBatch", back_populates="messages")
    campaign = relationship("EmailCampaign", back_populates="messages")
    patient = relationship("Patient")
    appointment = relationship("Appointment")
    discharge = relationship("Discharge")
    deliveries = relationship("EmailDelivery", back_populates="message", cascade="all, delete-orphan")


class EmailDelivery(Base):
    __tablename__ = "email_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("email_messages.id", ondelete="CASCADE"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True, nullable=False)

    message = relationship("EmailMessage", back_populates="deliveries")

