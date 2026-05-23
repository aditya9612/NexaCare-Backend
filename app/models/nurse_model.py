from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Nurse(Base):
    __tablename__ = "nurses"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    license_number: Mapped[str] = mapped_column(String(100), unique=True)
    department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    shift: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
