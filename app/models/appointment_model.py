from datetime import date, time

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, Text, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.constants import AppointmentStatus
from app.models.mixins import TimestampMixin


class Appointment(Base, TimestampMixin):
    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    appointment_number: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"), index=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True, index=True)
    appointment_date: Mapped[date] = mapped_column(Date, index=True)
    appointment_time: Mapped[time] = mapped_column(Time, index=True)
    appointment_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    appointment_status: Mapped[str] = mapped_column(
        String(50), default=AppointmentStatus.PENDING, index=True
    )
    symptoms: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    consultation_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False)

    patient = relationship("Patient", back_populates="appointments")
    doctor = relationship("Doctor", back_populates="appointments")
    department = relationship("Department", back_populates="appointments")
