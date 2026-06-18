from datetime import datetime
from sqlalchemy import DateTime, Float, String, Text, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin, SoftDeleteMixin


class TransactionHistory(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "transaction_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    event_type: Mapped[str] = mapped_column(String(50), index=True)  # e.g., EXPENSE_RECORDED, INVOICE_CREATED, etc.
    reference_no: Mapped[str] = mapped_column(String(100), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(50), default="completed", index=True)
    source_module: Mapped[str] = mapped_column(String(50), index=True)  # e.g., expenses, billing, payments, insurance, refunds
    source_id: Mapped[int] = mapped_column(Integer, index=True)
    event_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
