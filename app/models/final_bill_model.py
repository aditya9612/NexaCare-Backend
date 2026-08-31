from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import SoftDeleteMixin, TimestampMixin


class IPDFinalBill(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "ipd_final_bills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bill_number: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    
    discharge_id: Mapped[int] = mapped_column(Integer, ForeignKey("discharges.id"), index=True, nullable=False)
    patient_id: Mapped[int] = mapped_column(Integer, ForeignKey("patients.id"), index=True, nullable=False)
    appointment_id: Mapped[int] = mapped_column(Integer, ForeignKey("appointments.id"), index=True, nullable=False)
    doctor_id: Mapped[int] = mapped_column(Integer, ForeignKey("doctors.id"), index=True, nullable=False)
    bed_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("beds.id"), nullable=True)

    # Component subtotals
    bed_charges: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    doctor_charges: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    lab_charges: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    radiology_charges: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    pharmacy_charges: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    procedure_charges: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    prior_opd_charges: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # Financial calculations
    gross_total: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    discount_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    discount_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tax_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    tax_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    net_total: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    advance_adjusted: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    balance_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    refund_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # Status & Settlement
    status: Mapped[str] = mapped_column(String(50), default="pending", index=True, nullable=False)  # pending, paid, refunded
    payment_mode: Mapped[str | None] = mapped_column(String(50), default="Cash", nullable=True)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    settled_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    discharge = relationship("Discharge", foreign_keys=[discharge_id], backref="final_bills")
    patient = relationship("Patient", backref="ipd_final_bills")
    appointment = relationship("Appointment", backref="ipd_final_bills")
    doctor = relationship("Doctor", backref="ipd_final_bills")
    bed = relationship("Bed", backref="ipd_final_bills")
    settler = relationship("User", foreign_keys=[settled_by])
    
    items: Mapped[list["IPDFinalBillItem"]] = relationship(
        "IPDFinalBillItem", back_populates="final_bill", cascade="all, delete-orphan", lazy="selectin"
    )


class IPDFinalBillItem(Base):
    __tablename__ = "ipd_final_bill_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    final_bill_id: Mapped[int] = mapped_column(Integer, ForeignKey("ipd_final_bills.id", ondelete="CASCADE"), index=True, nullable=False)
    item_type: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    item_name: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    tax_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    total_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    reference_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    final_bill = relationship("IPDFinalBill", back_populates="items")
