from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import CampaignStatus, WhatsAppDeliveryStatus, WhatsAppMessageType
from app.core.database import Base
from app.models.mixins import TimestampMixin


class WhatsAppMessage(Base, TimestampMixin):
    __tablename__ = "whatsapp_messages"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    patient_id: Mapped[int | None] = mapped_column(ForeignKey("patients.id"), nullable=True, index=True)
    phone_number: Mapped[str] = mapped_column(String(20), index=True)
    message_type: Mapped[str] = mapped_column(String(20), default=WhatsAppMessageType.TEXT)
    message_content: Mapped[str] = mapped_column(Text)
    media_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    template_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    delivery_status: Mapped[str] = mapped_column(String(50), default=WhatsAppDeliveryStatus.PENDING, index=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("whatsapp_campaigns.id"), nullable=True, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    delivery_records: Mapped[list["MessageDelivery"]] = relationship(
        back_populates="message", cascade="all, delete-orphan"
    )


class WhatsAppTemplate(Base, TimestampMixin):
    __tablename__ = "whatsapp_templates"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    template_name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    template_body: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(10), default="en")
    category: Mapped[str] = mapped_column(String(50), default="utility")
    is_active: Mapped[bool] = mapped_column(default=True)
    variables: Mapped[str | None] = mapped_column(Text, nullable=True)


class WhatsAppCampaign(Base, TimestampMixin):
    __tablename__ = "whatsapp_campaigns"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    campaign_name: Mapped[str] = mapped_column(String(150), index=True)
    template_id: Mapped[int | None] = mapped_column(ForeignKey("whatsapp_templates.id"), nullable=True)
    message_content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default=CampaignStatus.DRAFT, index=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    total_recipients: Mapped[int] = mapped_column(Integer, default=0)
    sent_count: Mapped[int] = mapped_column(Integer, default=0)
    delivered_count: Mapped[int] = mapped_column(Integer, default=0)
    read_count: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class MessageDelivery(Base, TimestampMixin):
    __tablename__ = "message_deliveries"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("whatsapp_messages.id"), index=True)
    status: Mapped[str] = mapped_column(String(50), index=True)
    provider_status: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status_timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    raw_payload: Mapped[str | None] = mapped_column(Text, nullable=True)

    message: Mapped["WhatsAppMessage"] = relationship(back_populates="delivery_records")


class WhatsAppAnalytics(Base, TimestampMixin):
    __tablename__ = "whatsapp_analytics"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime, index=True)
    period_end: Mapped[datetime] = mapped_column(DateTime, index=True)
    total_sent: Mapped[int] = mapped_column(Integer, default=0)
    total_delivered: Mapped[int] = mapped_column(Integer, default=0)
    total_read: Mapped[int] = mapped_column(Integer, default=0)
    total_failed: Mapped[int] = mapped_column(Integer, default=0)
    delivery_rate: Mapped[float] = mapped_column(Float, default=0.0)
    read_rate: Mapped[float] = mapped_column(Float, default=0.0)
