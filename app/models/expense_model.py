from datetime import date, datetime
from sqlalchemy import String, Float, Integer, Boolean, ForeignKey, DateTime, Date, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
from app.models.mixins import TimestampMixin, SoftDeleteMixin
from app.utils.helpers import utc_now


class ExpenseCategory(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "expense_categories"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    expenses: Mapped[list["Expense"]] = relationship("Expense", back_populates="category")


class Expense(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("expense_categories.id", ondelete="RESTRICT"), index=True)
    vendor_id: Mapped[int | None] = mapped_column(ForeignKey("vendors.id", ondelete="SET NULL"), nullable=True, index=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    expense_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="Pending", index=True) # Paid, Pending

    category: Mapped["ExpenseCategory"] = relationship("ExpenseCategory", back_populates="expenses")
    vendor: Mapped["Vendor | None"] = relationship("Vendor", back_populates="expenses")
    payments: Mapped[list["VendorPayment"]] = relationship("VendorPayment", back_populates="expense", cascade="all, delete-orphan")


class VendorPayment(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "vendor_payments"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id", ondelete="CASCADE"), index=True)
    expense_id: Mapped[int] = mapped_column(ForeignKey("expenses.id", ondelete="CASCADE"), index=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    payment_method: Mapped[str] = mapped_column(String(50), nullable=False) # Cash, Card, UPI, Bank Transfer, etc.
    payment_date: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    vendor: Mapped["Vendor"] = relationship("Vendor", back_populates="payments")
    expense: Mapped["Expense"] = relationship("Expense", back_populates="payments")
