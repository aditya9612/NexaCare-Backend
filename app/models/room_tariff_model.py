from datetime import datetime
from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class RoomTariff(Base):
    __tablename__ = "room_tariffs"
    __table_args__ = (
        UniqueConstraint("hospital_id", "room_type", name="uq_room_tariffs_hospital_room_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hospital_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=True, index=True
    )
    room_type: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    daily_rate: Mapped[float] = mapped_column(Float, nullable=False)
    nursing_charge_per_day: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    doctor_visit_charge: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    hospital = relationship("Hospital")
