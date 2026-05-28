from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin


class Nurse(Base, TimestampMixin):
    __tablename__ = "nurses"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    nurse_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    license_number: Mapped[str] = mapped_column(String(100), unique=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.department_id"), nullable=True, index=True)
    shift: Mapped[str | None] = mapped_column(String(50), nullable=True)

    department = relationship("Department", back_populates="nurses")
