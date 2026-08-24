from datetime import date, time, datetime

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, Text, Time, DateTime
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
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.department_id"), nullable=True, index=True)
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

    check_in_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    check_out_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    queue_token: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    queue_status: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)

    admission_status: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    admission_recommended: Mapped[bool] = mapped_column(Boolean, default=False)
    admission_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_los: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recommended_ward: Mapped[str | None] = mapped_column(String(50), nullable=True)

    patient = relationship("Patient", back_populates="appointments")
    doctor = relationship("Doctor", back_populates="appointments")
    department = relationship("Department", back_populates="appointments")
    clinical_record = relationship("ClinicalRecord", back_populates="appointment", uselist=False)

    @property
    def patient_name(self) -> str | None:
        if not self.patient:
            return None
        return f"{self.patient.first_name or ''} {self.patient.last_name or ''}".strip() or None

    @property
    def age(self) -> int | None:
        if not self.patient or not self.patient.dob:
            return None
        today = date.today()
        dob = self.patient.dob
        return (
            today.year
            - dob.year
            - ((today.month, today.day) < (dob.month, dob.day))
        )

    @property
    def patient_mobile_number(self) -> str | None:
        if not self.patient:
            return None
        return self.patient.phone


