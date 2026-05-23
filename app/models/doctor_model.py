from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin


class Doctor(Base, TimestampMixin):
    __tablename__ = "doctors"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    doctor_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, unique=True)
    first_name: Mapped[str] = mapped_column(String(100), index=True)
    last_name: Mapped[str] = mapped_column(String(100), index=True)
    specialization: Mapped[str] = mapped_column(String(100), index=True)
    qualification: Mapped[str | None] = mapped_column(String(255), nullable=True)
    experience: Mapped[int | None] = mapped_column(Integer, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    department: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    consultation_fee: Mapped[float | None] = mapped_column(Float, nullable=True)
    license_number: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    availability_status: Mapped[str] = mapped_column(String(50), default="available", index=True)
    profile_image: Mapped[str | None] = mapped_column(String(500), nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    appointments = relationship("Appointment", back_populates="doctor")
    schedules = relationship("DoctorSchedule", back_populates="doctor", cascade="all, delete-orphan")


class DoctorSchedule(Base, TimestampMixin):
    __tablename__ = "doctor_schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id", ondelete="CASCADE"), index=True)
    day_of_week: Mapped[int] = mapped_column(Integer, index=True)
    start_time: Mapped[Time] = mapped_column(Time)
    end_time: Mapped[Time] = mapped_column(Time)
    slot_duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    doctor = relationship("Doctor", back_populates="schedules")
