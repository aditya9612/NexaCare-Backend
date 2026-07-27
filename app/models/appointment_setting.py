from sqlalchemy import Boolean, ForeignKey, Integer, Time, text, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import time

from app.core.database import Base
from app.models.hospital_model import Hospital
from app.models.mixins import TimestampMixin
from app.core.constants import OperationMode


class AppointmentSetting(Base, TimestampMixin):
    __tablename__ = "appointment_settings"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    hospital_id: Mapped[int] = mapped_column(
        ForeignKey("hospitals.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )

    operation_mode: Mapped[OperationMode] = mapped_column(
        SAEnum(
            OperationMode,
            values_callable=lambda enum: [e.value for e in enum],
        ),
        default=OperationMode.FIXED_HOURS,
        server_default=text("'fixed_hours'"),
    )

    slot_duration_minutes: Mapped[int] = mapped_column(
        Integer,
        default=30,
        server_default=text("30"),
    )
    working_start_time: Mapped[time] = mapped_column(Time, default=time(9, 0), server_default=text("'09:00:00'"))

    working_end_time: Mapped[time] = mapped_column(Time, default=time(18, 0), server_default=text("'18:00:00'"))

    lunch_break_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    lunch_start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    lunch_end_time: Mapped[time | None] = mapped_column(Time, nullable=True)

    max_advance_booking_days: Mapped[int] = mapped_column(Integer, default=30, server_default=text("30"))
    allow_overlapping: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    auto_cancel_no_show_minutes: Mapped[int] = mapped_column(
        Integer,
        default=30,
        server_default=text("30"),
    )
    weekend_booking_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))

    buffer_between_slots_minutes: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    allow_walk_in: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("1"))

    hospital: Mapped[Hospital] = relationship(
        back_populates="appointment_settings",
    )