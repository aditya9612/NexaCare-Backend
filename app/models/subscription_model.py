from datetime import datetime
from sqlalchemy import String, Float, Integer, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
from app.models.mixins import TimestampMixin

class SubscriptionPlan(Base, TimestampMixin):
    __tablename__ = "subscription_plans"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    price: Mapped[float] = mapped_column(Float, default=0.0)
    duration_days: Mapped[int] = mapped_column(Integer, default=30)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    max_doctors: Mapped[int] = mapped_column(Integer, default=5)
    max_patients: Mapped[int] = mapped_column(Integer, default=100)
    features: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    subscriptions = relationship("Subscription", back_populates="plan", cascade="all, delete-orphan")


class Subscription(Base, TimestampMixin):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    plan_id: Mapped[int] = mapped_column(
        ForeignKey("subscription_plans.id", ondelete="CASCADE"),
        index=True
    )

    status: Mapped[str] = mapped_column(
        String(50),
        default="active",
        index=True
    )

    start_date: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow
    )

    end_date: Mapped[datetime] = mapped_column(DateTime)

    price_paid: Mapped[float] = mapped_column(
        Float,
        default=0.0
    )

    transaction_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True
    )

    plan = relationship(
        "SubscriptionPlan",
        back_populates="subscriptions"
    )


