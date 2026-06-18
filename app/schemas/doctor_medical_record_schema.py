from datetime import datetime

from app.schemas.common_schema import BaseSchema


class MedicalRecordResponse(BaseSchema):
    id: int
    patient_id: int
    doctor_id: int | None
    patient_name: str
    report_title: str
    report_type: str
    diagnosis: str | None
    notes: str | None
    file_name: str
    file_type: str | None
    file_path: str
    created_at: datetime
    updated_at: datetime


class DiagnosisUpdate(BaseSchema):
    diagnosis: str
    symptoms: str | None = None
    notes: str | None = None


class DiagnosisResponse(BaseSchema):
    id: int
    patient_id: int
    doctor_id: int | None
    diagnosis: str
    symptoms: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class TreatmentNoteCreate(BaseSchema):
    note: str
    treatment_plan: str | None = None


class TreatmentNoteResponse(BaseSchema):
    id: int
    patient_id: int
    doctor_id: int | None
    note: str
    treatment_plan: str | None
    created_at: datetime
    updated_at: datetime