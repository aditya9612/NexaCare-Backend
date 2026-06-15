from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin


class DoctorMedicalRecord(Base, TimestampMixin):
    __tablename__ = "doctor_medical_records"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    doctor_id: Mapped[int | None] = mapped_column(ForeignKey("doctors.id"), nullable=True, index=True)

    patient_name: Mapped[str] = mapped_column(String(255))
    report_title: Mapped[str] = mapped_column(String(255))
    report_type: Mapped[str] = mapped_column(String(100))
    diagnosis: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    file_path: Mapped[str] = mapped_column(String(500))
    file_name: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str | None] = mapped_column(String(100), nullable=True)

    patient = relationship("Patient")
    doctor = relationship("Doctor")


class PatientDiagnosis(Base, TimestampMixin):
    __tablename__ = "patient_diagnoses"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), unique=True, index=True)
    doctor_id: Mapped[int | None] = mapped_column(ForeignKey("doctors.id"), nullable=True)

    diagnosis: Mapped[str] = mapped_column(Text)
    symptoms: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    patient = relationship("Patient")
    doctor = relationship("Doctor")


class TreatmentNote(Base, TimestampMixin):
    __tablename__ = "treatment_notes"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    doctor_id: Mapped[int | None] = mapped_column(ForeignKey("doctors.id"), nullable=True)

    note: Mapped[str] = mapped_column(Text)
    treatment_plan: Mapped[str | None] = mapped_column(Text, nullable=True)

    patient = relationship("Patient")
    doctor = relationship("Doctor")