from datetime import date, datetime, time

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin


class Nurse(Base, TimestampMixin):
    __tablename__ = "nurses"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    nurse_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    license_number: Mapped[str] = mapped_column(String(100), unique=True)
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("departments.department_id"), nullable=True, index=True
    )
    shift: Mapped[str | None] = mapped_column(String(50), nullable=True)

    department = relationship("Department", back_populates="nurses")
    shifts = relationship("NurseShift", back_populates="nurse", cascade="all, delete-orphan")
    attendance = relationship(
        "NurseAttendance", back_populates="nurse", cascade="all, delete-orphan"
    )
    handover_notes = relationship(
        "NurseHandoverNote", back_populates="nurse", cascade="all, delete-orphan"
    )
    patient_assignments = relationship(
        "NursePatientAssignment", back_populates="nurse", cascade="all, delete-orphan"
    )
    notifications = relationship(
        "NurseNotification", back_populates="nurse", cascade="all, delete-orphan"
    )
    patient_vitals = relationship(
        "PatientVital", back_populates="nurse", cascade="all, delete-orphan"
    )
    tasks = relationship("NurseTask", back_populates="nurse", cascade="all, delete-orphan")


class NurseShift(Base, TimestampMixin):
    __tablename__ = "nurse_shifts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    nurse_id: Mapped[int] = mapped_column(
        ForeignKey("nurses.id", ondelete="CASCADE"), index=True
    )
    shift_name: Mapped[str] = mapped_column(String(50), index=True)
    shift_date: Mapped[date] = mapped_column(Date, index=True)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    status: Mapped[str] = mapped_column(String(50), default="Scheduled", index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    nurse = relationship("Nurse", back_populates="shifts")
    handover_notes = relationship("NurseHandoverNote", back_populates="shift")


class NurseAttendance(Base, TimestampMixin):
    __tablename__ = "nurse_attendance"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    nurse_id: Mapped[int] = mapped_column(
        ForeignKey("nurses.id", ondelete="CASCADE"), index=True
    )
    attendance_date: Mapped[date] = mapped_column(Date, index=True)
    check_in_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    check_out_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="Present", index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    nurse = relationship("Nurse", back_populates="attendance")


class NurseHandoverNote(Base, TimestampMixin):
    __tablename__ = "nurse_handover_notes"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    nurse_id: Mapped[int] = mapped_column(
        ForeignKey("nurses.id", ondelete="CASCADE"), index=True
    )
    shift_id: Mapped[int | None] = mapped_column(
        ForeignKey("nurse_shifts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    handover_date: Mapped[date] = mapped_column(Date, index=True)
    summary: Mapped[str] = mapped_column(Text)
    pending_tasks: Mapped[str | None] = mapped_column(Text, nullable=True)
    patient_updates: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="Active", index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    nurse = relationship("Nurse", back_populates="handover_notes")
    shift = relationship("NurseShift", back_populates="handover_notes")


class NursePatientAssignment(Base, TimestampMixin):
    __tablename__ = "nurse_patient_assignments"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    nurse_id: Mapped[int] = mapped_column(
        ForeignKey("nurses.id", ondelete="CASCADE"), index=True
    )
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(50), default="Active", index=True)
    patient_status: Mapped[str] = mapped_column(String(50), default="Stable", index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    nurse = relationship("Nurse", back_populates="patient_assignments")
    patient = relationship("Patient")


class NurseNotification(Base, TimestampMixin):
    __tablename__ = "nurse_notifications"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    nurse_id: Mapped[int] = mapped_column(
        ForeignKey("nurses.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    notification_type: Mapped[str] = mapped_column(
        String(50), default="Notification", index=True
    )
    priority: Mapped[str] = mapped_column(String(50), default="Medium", index=True)
    status: Mapped[str] = mapped_column(String(50), default="Active", index=True)
    patient_id: Mapped[int | None] = mapped_column(
        ForeignKey("patients.id", ondelete="SET NULL"), nullable=True, index=True
    )
    shift_id: Mapped[int | None] = mapped_column(
        ForeignKey("nurse_shifts.id", ondelete="SET NULL"), nullable=True, index=True
    )

    nurse = relationship("Nurse", back_populates="notifications")


class PatientVital(Base, TimestampMixin):
    __tablename__ = "patient_vitals"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    nurse_id: Mapped[int] = mapped_column(
        ForeignKey("nurses.id", ondelete="CASCADE"), index=True
    )
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    temperature: Mapped[float] = mapped_column(Float)
    blood_pressure: Mapped[str] = mapped_column(String(20))
    pulse_rate: Mapped[int] = mapped_column(Integer)
    oxygen_saturation: Mapped[float] = mapped_column(Float)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, index=True)

    nurse = relationship("Nurse", back_populates="patient_vitals")
    patient = relationship("Patient")


class NurseTask(Base, TimestampMixin):
    __tablename__ = "nurse_tasks"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    nurse_id: Mapped[int] = mapped_column(
        ForeignKey("nurses.id", ondelete="CASCADE"), index=True
    )
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_date: Mapped[date] = mapped_column(Date, index=True)
    priority: Mapped[str] = mapped_column(String(50), default="Medium", index=True)
    status: Mapped[str] = mapped_column(String(50), default="Pending", index=True)

    nurse = relationship("Nurse", back_populates="tasks")
    patient = relationship("Patient")


__all__ = [
    "Nurse",
    "NurseShift",
    "NurseAttendance",
    "NurseHandoverNote",
    "NursePatientAssignment",
    "NurseNotification",
    "PatientVital",
    "NurseTask",
]
