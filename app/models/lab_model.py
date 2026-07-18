from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import SoftDeleteMixin, TimestampMixin


class LabTest(Base, TimestampMixin, SoftDeleteMixin):
    """Catalog of available lab tests."""

    __tablename__ = "lab_tests"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    test_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    test_name: Mapped[str] = mapped_column(String(255), index=True)
    category: Mapped[str] = mapped_column(String(100), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[float] = mapped_column(Float, default=0.0)
    sample_type: Mapped[str] = mapped_column(String(100), default="blood")
    turnaround_hours: Mapped[int] = mapped_column(Integer, default=24)
    normal_range: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.department_id"), nullable=True, index=True)
    doctor_id: Mapped[int | None] = mapped_column(ForeignKey("doctors.id"), nullable=True, index=True)

    orders: Mapped[list["TestOrder"]] = relationship(back_populates="lab_test")
    department = relationship("Department", back_populates="lab_tests")


class TestOrder(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "test_orders"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    order_number: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    doctor_id: Mapped[int | None] = mapped_column(ForeignKey("doctors.id"), nullable=True)
    lab_test_id: Mapped[int] = mapped_column(ForeignKey("lab_tests.id"), index=True)
    appointment_id: Mapped[int | None] = mapped_column(ForeignKey("appointments.id"), nullable=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.department_id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(50), default="ordered", index=True)
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    ordered_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    lab_test: Mapped["LabTest"] = relationship(back_populates="orders")
    samples: Mapped[list["Sample"]] = relationship(back_populates="test_order", cascade="all, delete-orphan")
    results: Mapped[list["TestResult"]] = relationship(back_populates="test_order", cascade="all, delete-orphan")
    reports: Mapped[list["LabReport"]] = relationship(back_populates="test_order", cascade="all, delete-orphan")
    department = relationship("Department", back_populates="test_orders")


class Sample(Base, TimestampMixin):
    __tablename__ = "samples"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    test_order_id: Mapped[int] = mapped_column(ForeignKey("test_orders.id"), index=True)
    sample_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    sample_type: Mapped[str] = mapped_column(String(100))
    collected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    collection_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    collected_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending", index=True)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    test_order: Mapped["TestOrder"] = relationship(back_populates="samples")


class TestResult(Base, TimestampMixin):
    __tablename__ = "test_results"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    test_order_id: Mapped[int] = mapped_column(ForeignKey("test_orders.id"), index=True)
    parameter_name: Mapped[str] = mapped_column(String(255))
    result_value: Mapped[str] = mapped_column(String(255))
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    normal_range: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(50), default="pending", index=True)
    entered_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    entered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    document_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    test_order: Mapped["TestOrder"] = relationship(back_populates="results")


class LabReport(Base, TimestampMixin):
    __tablename__ = "lab_reports"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    test_order_id: Mapped[int] = mapped_column(ForeignKey("test_orders.id"), index=True)
    report_number: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(50), default="draft", index=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    generated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    test_order: Mapped["TestOrder"] = relationship(back_populates="reports")
