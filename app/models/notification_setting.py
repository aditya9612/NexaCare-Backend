from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin


class NotificationSetting(Base, TimestampMixin):
    __tablename__ = "notification_settings"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    hospital_id: Mapped[int] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), unique=True)
    sms_on_appointment: Mapped[bool] = mapped_column(Boolean, default=True)
    email_on_appointment: Mapped[bool] = mapped_column(Boolean, default=True)
    sms_on_billing: Mapped[bool] = mapped_column(Boolean, default=False)
    email_on_billing: Mapped[bool] = mapped_column(Boolean, default=True)
