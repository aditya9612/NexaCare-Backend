from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import SoftDeleteMixin, TimestampMixin


class Staff(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "staff"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    first_name: Mapped[str] = mapped_column(String(100), index=True)
    last_name: Mapped[str] = mapped_column(String(100), index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    employee_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.department_id"), index=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), index=True)
    status: Mapped[str] = mapped_column(String(50), default="active", index=True)

    department = relationship("Department")
    role = relationship("Role")
