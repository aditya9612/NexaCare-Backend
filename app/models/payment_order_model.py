from datetime import datetime
from decimal import Decimal
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin


class RazorpayOrder(Base, TimestampMixin):
    __tablename__ = "razorpay_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hospital_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=True, index=True
    )
    bill_type: Mapped[str] = mapped_column(String(50), index=True, nullable=False)  # opd, pharmacy, ipd
    bill_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    razorpay_order_id: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    razorpay_payment_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount_inr: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="INR", nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="created", index=True, nullable=False)
    # created, authorized, pending, paid, failed, reconciliation_required, reconciliation_deferred, refunded
    settled_amount_inr: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    excess_amount_inr: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    signature: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Relationships
    hospital = relationship("Hospital")
    creator = relationship("User", foreign_keys=[created_by])


class RazorpayWebhookEvent(Base, TimestampMixin):
    __tablename__ = "razorpay_webhook_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
