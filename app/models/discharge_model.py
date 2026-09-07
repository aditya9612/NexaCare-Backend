from datetime import date, datetime
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Discharge(Base):
    __tablename__ = "discharges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    discharge_number: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    
    appointment_id: Mapped[int] = mapped_column(Integer, ForeignKey("appointments.id"), index=True, nullable=False)
    patient_id: Mapped[int] = mapped_column(Integer, ForeignKey("patients.id"), index=True, nullable=False)
    doctor_id: Mapped[int] = mapped_column(Integer, ForeignKey("doctors.id"), index=True, nullable=False)
    bed_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("beds.id"), nullable=True)

    admission_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    discharge_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    diagnosis_at_admission: Mapped[str | None] = mapped_column(String(255), nullable=True)
    diagnosis_at_discharge: Mapped[str] = mapped_column(String(255), nullable=False)
    treatment_summary: Mapped[str] = mapped_column(Text, nullable=False)
    condition_on_discharge: Mapped[str] = mapped_column(String(100), default="Stable", nullable=False)
    post_medications: Mapped[str | None] = mapped_column(Text, nullable=True)
    home_care_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    follow_up_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Tri-Clearance Checkpoints
    pharmacy_cleared: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    pharmacy_cleared_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    pharmacy_cleared_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    pharmacy_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    billing_cleared: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    billing_cleared_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    billing_cleared_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    billing_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("billings.id"), nullable=True)
    final_bill_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("ipd_final_bills.id"), nullable=True)
    billing_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    payment_cleared: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    payment_cleared_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    payment_cleared_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    payment_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Doctor Final Sign-off
    doctor_approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    doctor_approved_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    doctor_approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    discharge_status: Mapped[str] = mapped_column(
        String(50), default="PENDING_CLEARANCES", index=True, nullable=False
    )  # PENDING_CLEARANCES, CLEARED, DISCHARGED, CANCELLED

    gate_pass_number: Mapped[str | None] = mapped_column(String(50), unique=True, index=True, nullable=True)
    discharge_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    appointment = relationship("Appointment", backref="discharges")
    patient = relationship("Patient", backref="discharges")
    doctor = relationship("Doctor", backref="discharges")
    bed = relationship("Bed", backref="discharges")
    billing = relationship("Billing", backref="discharges")
    final_bill = relationship("IPDFinalBill", foreign_keys=[final_bill_id], backref="discharge_record")
