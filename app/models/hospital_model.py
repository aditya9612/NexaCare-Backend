from sqlalchemy import String, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
from app.models.mixins import TimestampMixin, SoftDeleteMixin

class Hospital(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "hospitals"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    users = relationship("User", back_populates="hospital")
    appointment_settings = relationship("AppointmentSetting", back_populates="hospital", uselist=False, cascade="all, delete-orphan")
    # subscriptions = relationship("Subscription", back_populates="hospital", cascade="all, delete-orphan")

