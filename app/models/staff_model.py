from sqlalchemy import ForeignKey, String, Integer
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
