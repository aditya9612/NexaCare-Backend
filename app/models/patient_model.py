from datetime import date

from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import SoftDeleteMixin, TimestampMixin


class Patient(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    patient_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    first_name: Mapped[str] = mapped_column(String(100), index=True)
    last_name: Mapped[str] = mapped_column(String(100), index=True)
    gender: Mapped[str | None] = mapped_column(String(20), nullable=True)
    dob: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    blood_group: Mapped[str | None] = mapped_column(String(10), nullable=True)
    marital_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    pincode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    emergency_contact_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    emergency_contact_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    allergies: Mapped[str | None] = mapped_column(Text, nullable=True)
    medical_history: Mapped[str | None] = mapped_column(Text, nullable=True)
    chronic_disease: Mapped[str | None] = mapped_column(Text, nullable=True)
    insurance_provider: Mapped[str | None] = mapped_column(String(255), nullable=True)
    insurance_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="active", index=True)

    appointments = relationship("Appointment", back_populates="patient")
    documents = relationship("PatientDocument", back_populates="patient", cascade="all, delete-orphan")
    family_members = relationship("FamilyMember", back_populates="patient", cascade="all, delete-orphan")


class PatientDocument(Base, TimestampMixin):
    __tablename__ = "patient_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    document_name: Mapped[str] = mapped_column(String(255))
    document_type: Mapped[str] = mapped_column(String(50))
    file_path: Mapped[str] = mapped_column(String(500))
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    patient = relationship("Patient", back_populates="documents")


class FamilyMember(Base, TimestampMixin):
    __tablename__ = "family_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    relationship_type: Mapped[str] = mapped_column(String(50))
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    patient = relationship("Patient", back_populates="family_members")
