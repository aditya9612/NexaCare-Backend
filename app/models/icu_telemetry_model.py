from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin
from app.utils.helpers import utc_now


class IcuDevice(Base, TimestampMixin):
    __tablename__ = "icu_devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    bed_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("beds.id", ondelete="CASCADE"), index=True
    )
    device_serial: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    api_key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(150))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    bed = relationship("Bed")
    readings = relationship("IcuVitalReading", back_populates="device")


class IcuVitalReading(Base):
    __tablename__ = "icu_vital_readings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    bed_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("beds.id", ondelete="CASCADE"), index=True
    )
    patient_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("patients.id", ondelete="SET NULL"), nullable=True, index=True
    )
    device_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("icu_devices.id", ondelete="CASCADE"), index=True
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    heart_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    systolic_bp: Mapped[float | None] = mapped_column(Float, nullable=True)
    diastolic_bp: Mapped[float | None] = mapped_column(Float, nullable=True)
    spo2: Mapped[float | None] = mapped_column(Float, nullable=True)
    respiratory_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    ecg_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)

    device = relationship("IcuDevice", back_populates="readings")
    bed = relationship("Bed")
    patient = relationship("Patient")
    alerts = relationship("IcuTelemetryAlert", back_populates="vital_reading")


class IcuTelemetryAlert(Base, TimestampMixin):
    __tablename__ = "icu_telemetry_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    bed_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("beds.id", ondelete="CASCADE"), index=True
    )
    patient_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("patients.id", ondelete="SET NULL"), nullable=True, index=True
    )
    vital_reading_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("icu_vital_readings.id", ondelete="CASCADE"), index=True
    )
    vital_type: Mapped[str] = mapped_column(String(50), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    message: Mapped[str] = mapped_column(Text)
    value: Mapped[float] = mapped_column(Float)
    threshold_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    threshold_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    acknowledged_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    vital_reading = relationship("IcuVitalReading", back_populates="alerts")
    bed = relationship("Bed")
    patient = relationship("Patient")
