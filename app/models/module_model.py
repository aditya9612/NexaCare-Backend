from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin
from app.utils.helpers import utc_now


class Module(Base, TimestampMixin):
    __tablename__ = "modules"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    tier: Mapped[str] = mapped_column(String(20), default="FOUNDATIONAL", index=True)  # FOUNDATIONAL | COMMERCIAL
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    hospital_modules = relationship("HospitalModule", back_populates="module", cascade="all, delete-orphan")


class HospitalModule(Base, TimestampMixin):
    __tablename__ = "hospital_modules"
    __table_args__ = (UniqueConstraint("hospital_id", "module_code", name="uq_hospital_module"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    hospital_id: Mapped[int] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), index=True)
    module_code: Mapped[str] = mapped_column(ForeignKey("modules.code", ondelete="CASCADE"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", index=True)  # TRIAL, ACTIVE, SUSPENDED, EXPIRED, CANCELLED
    activated_at: Mapped[datetime | None] = mapped_column(DateTime, default=utc_now, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    module = relationship("Module", back_populates="hospital_modules")
