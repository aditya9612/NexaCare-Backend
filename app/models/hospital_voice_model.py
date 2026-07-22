from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import TelephonyProviderType, VoiceGender, VoiceLanguage
from app.core.database import Base
from app.models.mixins import SoftDeleteMixin, TimestampMixin


class HospitalVoiceConfig(Base, TimestampMixin, SoftDeleteMixin):
    """Per-hospital voice / telephony settings. No hardcoded voice defaults in services."""

    __tablename__ = "hospital_voice_configs"
    __table_args__ = (UniqueConstraint("hospital_id", name="uq_hospital_voice_configs_hospital_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    hospital_id: Mapped[int] = mapped_column(ForeignKey("hospitals.id"), index=True)
    telephony_provider: Mapped[str] = mapped_column(
        String(20), default=TelephonyProviderType.TWILIO, index=True
    )
    voice_gender: Mapped[str] = mapped_column(String(20), default=VoiceGender.FEMALE)
    voice_profile: Mapped[str | None] = mapped_column(String(100), nullable=True)
    default_language: Mapped[str] = mapped_column(String(10), default=VoiceLanguage.EN)
    reception_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=3)
    from_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    inbound_did: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)

    # Optional per-hospital Exotel credential overrides (empty = use env defaults)
    exotel_sid: Mapped[str | None] = mapped_column(String(100), nullable=True)
    exotel_api_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    exotel_api_token: Mapped[str | None] = mapped_column(String(100), nullable=True)
    exotel_subdomain: Mapped[str | None] = mapped_column(String(100), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    hospital = relationship("Hospital", backref="voice_config")


class HospitalFaq(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "hospital_faqs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    hospital_id: Mapped[int] = mapped_column(ForeignKey("hospitals.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(10), default=VoiceLanguage.EN, index=True)
    tags: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class HospitalPolicy(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "hospital_policies"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    hospital_id: Mapped[int] = mapped_column(ForeignKey("hospitals.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(10), default=VoiceLanguage.EN, index=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class HospitalVoiceDocument(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "hospital_voice_documents"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    hospital_id: Mapped[int] = mapped_column(ForeignKey("hospitals.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(10), default=VoiceLanguage.EN, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class VoiceCallbackTicket(Base, TimestampMixin):
    __tablename__ = "voice_callback_tickets"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    hospital_id: Mapped[int | None] = mapped_column(ForeignKey("hospitals.id"), nullable=True, index=True)
    patient_id: Mapped[int | None] = mapped_column(ForeignKey("patients.id"), nullable=True, index=True)
    call_id: Mapped[int | None] = mapped_column(ForeignKey("voice_calls.id"), nullable=True, index=True)
    phone: Mapped[str] = mapped_column(String(20), index=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="queued", index=True)
    language: Mapped[str] = mapped_column(String(10), default=VoiceLanguage.EN)
