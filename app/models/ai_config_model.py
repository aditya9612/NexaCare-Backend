from sqlalchemy import String, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
from app.models.mixins import TimestampMixin

class AIConfiguration(Base, TimestampMixin):
    __tablename__ = "ai_configurations"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    feature_name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    config_data: Mapped[str | None] = mapped_column(Text, nullable=True)
