from datetime import datetime
from typing import Optional

from app.schemas.common_schema import BaseSchema, PaginatedResponse


class ClinicalRecordCreate(BaseSchema):
    patient_id: int
    doctor_id: int
    appointment_id: Optional[int] = None
    symptoms: Optional[str] = None
    diagnosis: Optional[str] = None
    treatment_plan: Optional[str] = None
    notes: Optional[str] = None


class ClinicalRecordUpdate(BaseSchema):
    patient_id: Optional[int] = None
    doctor_id: Optional[int] = None
    appointment_id: Optional[int] = None
    symptoms: Optional[str] = None
    diagnosis: Optional[str] = None
    treatment_plan: Optional[str] = None
    notes: Optional[str] = None


class ClinicalRecordResponse(BaseSchema):
    id: int
    patient_id: int
    doctor_id: int
    appointment_id: Optional[int] = None
    symptoms: Optional[str] = None
    diagnosis: Optional[str] = None
    treatment_plan: Optional[str] = None
    notes: Optional[str] = None
    patient_name: Optional[str] = None
    doctor_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime


ClinicalRecordListResponse = PaginatedResponse[ClinicalRecordResponse]
