from datetime import datetime
from typing import Optional

from app.schemas.common_schema import BaseSchema, PaginatedResponse


import re
from pydantic import field_validator

def validate_clinical_text(v: str | None, field_name: str) -> str | None:
    if v is None:
        return v
    cleaned = v.strip()
    if not cleaned or cleaned.lower() == "null":
        raise ValueError(f"{field_name} cannot be blank or 'null'")
    
    val_lower = cleaned.lower()
    placeholders = {"string", "yes", "no", "none", "nil", "test", "temp", "placeholder", "xyz", "abc", "testing"}
    if val_lower in placeholders:
        raise ValueError(f"{field_name} cannot contain placeholder value '{cleaned}'")
        
    words = cleaned.split()
    for w in words:
        if len(w) > 25:
            raise ValueError(f"{field_name} cannot contain words longer than 25 characters (invalid format or keyboard mashing)")
            
    if not re.search(r"[a-zA-Z]", cleaned):
        raise ValueError(f"{field_name} must contain at least one alphabetic character")
        
    return cleaned


class ClinicalRecordCreate(BaseSchema):
    patient_id: int
    doctor_id: int
    appointment_id: Optional[int] = None
    symptoms: Optional[str] = None
    diagnosis: Optional[str] = None
    treatment_plan: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("symptoms", "diagnosis", "treatment_plan", "notes")
    @classmethod
    def validate_fields(cls, v: str | None, info) -> str | None:
        field_name = info.field_name.replace("_", " ").title()
        return validate_clinical_text(v, field_name)


class ClinicalRecordUpdate(BaseSchema):
    patient_id: Optional[int] = None
    doctor_id: Optional[int] = None
    appointment_id: Optional[int] = None
    symptoms: Optional[str] = None
    diagnosis: Optional[str] = None
    treatment_plan: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("symptoms", "diagnosis", "treatment_plan", "notes")
    @classmethod
    def validate_fields(cls, v: str | None, info) -> str | None:
        field_name = info.field_name.replace("_", " ").title()
        return validate_clinical_text(v, field_name)


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
