from datetime import datetime
from sqlalchemy import Boolean, Float, Integer, String, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RoomTariff(Base):
    __tablename__ = "room_tariffs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    room_type: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    daily_rate: Mapped[float] = mapped_column(Float, nullable=False)
    nursing_charge_per_day: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    doctor_visit_charge: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
