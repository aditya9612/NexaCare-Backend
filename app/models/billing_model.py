from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import SoftDeleteMixin, TimestampMixin


class Billing(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "billings"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    bill_number: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    subtotal: Mapped[float] = mapped_column(Float, default=0.0)
    discount_percent: Mapped[float] = mapped_column(Float, default=0.0)
    discount_amount: Mapped[float] = mapped_column(Float, default=0.0)
    gst_rate: Mapped[float] = mapped_column(Float, default=18.0)
    gst_amount: Mapped[float] = mapped_column(Float, default=0.0)
    tax_amount: Mapped[float] = mapped_column(Float, default=0.0)
    total_amount: Mapped[float] = mapped_column(Float, default=0.0)
    paid_amount: Mapped[float] = mapped_column(Float, default=0.0)
    balance_amount: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(50), default="pending", index=True)
    due_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    insurance_id: Mapped[int | None] = mapped_column(ForeignKey("insurances.id"), nullable=True)
    invoice_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    items: Mapped[list["BillItem"]] = relationship(back_populates="billing", cascade="all, delete-orphan")
    payments: Mapped[list["Payment"]] = relationship(back_populates="billing", cascade="all, delete-orphan")
    insurance: Mapped["Insurance | None"] = relationship(back_populates="billings")
    claims: Mapped[list["InsuranceClaim"]] = relationship(back_populates="billing")


class BillItem(Base, TimestampMixin):
    __tablename__ = "bill_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    billing_id: Mapped[int] = mapped_column(ForeignKey("billings.id"), index=True)
    description: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[float] = mapped_column(Float)
    gst_rate: Mapped[float] = mapped_column(Float, default=18.0)
    gst_amount: Mapped[float] = mapped_column(Float, default=0.0)
    line_total: Mapped[float] = mapped_column(Float, default=0.0)
    item_type: Mapped[str] = mapped_column(String(50), default="service")

    billing: Mapped["Billing"] = relationship(back_populates="items")


class Payment(Base, TimestampMixin):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    billing_id: Mapped[int] = mapped_column(ForeignKey("billings.id"), index=True)
    amount: Mapped[float] = mapped_column(Float)
    payment_method: Mapped[str] = mapped_column(String(50))
    transaction_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payment_date: Mapped[datetime] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(50), default="completed")
    is_refund: Mapped[bool] = mapped_column(Boolean, default=False)
    refund_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    billing: Mapped["Billing"] = relationship(back_populates="payments")


class Insurance(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "insurances"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    provider_name: Mapped[str] = mapped_column(String(255))
    policy_number: Mapped[str] = mapped_column(String(100), index=True)
    coverage_percent: Mapped[float] = mapped_column(Float, default=0.0)
    max_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    billings: Mapped[list["Billing"]] = relationship(back_populates="insurance")
    claims: Mapped[list["InsuranceClaim"]] = relationship(back_populates="insurance")


class InsuranceClaim(Base, TimestampMixin):
    __tablename__ = "insurance_claims"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    billing_id: Mapped[int] = mapped_column(ForeignKey("billings.id"), index=True)
    insurance_id: Mapped[int] = mapped_column(ForeignKey("insurances.id"), index=True)
    claim_number: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    claimed_amount: Mapped[float] = mapped_column(Float)
    approved_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="submitted", index=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    billing: Mapped["Billing"] = relationship(back_populates="claims")
    insurance: Mapped["Insurance"] = relationship(back_populates="claims")


# Backward-compatible alias
Bill = Billing
