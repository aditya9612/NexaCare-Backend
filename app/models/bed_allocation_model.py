from datetime import datetime
from sqlalchemy import Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin
from app.models.patient_model import Patient


class Floor(Base, TimestampMixin):
    __tablename__ = "floors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    number: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    type: Mapped[str] = mapped_column(String(50))  # General, ICU, Emergency, Deluxe
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    rooms = relationship("Room", back_populates="floor", cascade="all, delete-orphan")


class Room(Base, TimestampMixin):
    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    floor_id: Mapped[int] = mapped_column(Integer, ForeignKey("floors.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(100))
    type: Mapped[str] = mapped_column(String(50))
    capacity: Mapped[int] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    floor = relationship("Floor", back_populates="rooms")
    beds = relationship("Bed", back_populates="room", cascade="all, delete-orphan")


class Bed(Base, TimestampMixin):
    __tablename__ = "beds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    room_id: Mapped[int] = mapped_column(Integer, ForeignKey("rooms.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    type: Mapped[str] = mapped_column(String(50))  # General, ICU, Ventilator, Deluxe, etc.
    status: Mapped[str] = mapped_column(String(50), default="Available")  # Available, Occupied, Reserved, Cleaning, Maintenance
    patient_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("patients.id", ondelete="SET NULL"), nullable=True, index=True
    )
    allocation_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    admission_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    room = relationship("Room", back_populates="beds")
    patient = relationship("Patient")


class BedActivityLog(Base, TimestampMixin):
    __tablename__ = "bed_activity_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    type: Mapped[str] = mapped_column(String(50))  # allocation, release, transfer, crud
    message: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    
    floor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    room_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bed_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    patient_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
