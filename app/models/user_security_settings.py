from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.utils.helpers import utc_now


class UserSecuritySettings(Base):
    __tablename__ = "user_security_settings"

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    is_2fa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
    totp_secret_encrypted: Mapped[str | None] = mapped_column(String(500), nullable=True)
    recovery_codes_hashed: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)

    user = relationship("User", backref="security_settings")
