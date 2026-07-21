from sqlalchemy import ForeignKey, String, Integer, Time, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import SoftDeleteMixin, TimestampMixin


class Staff(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "staff"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200), index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    staff_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.department_id"), index=True)
    role_name: Mapped[str] = mapped_column(ForeignKey("roles.name"), index=True)
    status: Mapped[int] = mapped_column(Integer, default=1, index=True)

    department = relationship("Department")
    role = relationship("Role")
    schedules = relationship("StaffSchedule", back_populates="staff", cascade="all, delete-orphan")


class StaffSchedule(Base, TimestampMixin):
    __tablename__ = "staff_schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff.id", ondelete="CASCADE"), index=True)
    day_of_week: Mapped[int] = mapped_column(Integer, index=True)
    start_time: Mapped[Time] = mapped_column(Time)
    end_time: Mapped[Time] = mapped_column(Time)
    slot_duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    staff = relationship("Staff", back_populates="schedules")
