from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    resource: Mapped[str] = mapped_column(String(50), index=True)
    action: Mapped[str] = mapped_column(String(50), index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    role_permissions = relationship("RolePermission", back_populates="permission")
