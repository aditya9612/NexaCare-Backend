from datetime import datetime
import re
from pydantic import Field, field_validator
from app.schemas.common_schema import BaseSchema


class MedicalRecordUploadValidator(BaseSchema):
    patient_id: int
    appointment_id: int
    doctor_id: int
    diagnosis: str
    report_title: str | None = None
    report_type: str | None = None
    notes: str | None = None
    symptoms: str | None = None

    @field_validator("diagnosis")
    @classmethod
    def check_diagnosis(cls, v: str) -> str:
        if not v or not v.strip() or v.lower() == "null":
            raise ValueError("Diagnosis cannot be blank or 'null'")
        if v.strip().lower() == "string":
            raise ValueError("Diagnosis cannot contain placeholder value 'string'")
        return v.strip()

    @field_validator("report_title", "report_type")
    @classmethod
    def check_optional_string_fields(cls, v: str | None, info) -> str | None:
        if v is None:
            return v
        field_name = info.field_name.replace("_", " ").title()
        if not v.strip() or v.lower() == "null":
            raise ValueError(f"{field_name} cannot be blank or 'null'")
        if v.strip().lower() == "string":
            raise ValueError(f"{field_name} cannot contain placeholder value 'string'")
        cleaned = v.strip()
        if not re.match(r"^[a-zA-Z0-9\s\-\'\.]+$", cleaned):
            raise ValueError(f"{field_name} must contain only alphanumeric characters, spaces, hyphens, dots, or apostrophes")
        return cleaned

    @field_validator("notes", "symptoms")
    @classmethod
    def check_optional_fields(cls, v: str | None, info) -> str | None:
        if v is None:
            return v
        field_name = info.field_name.replace("_", " ").title()
        if not v.strip() or v.lower() == "null":
            raise ValueError(f"{field_name} cannot be blank or 'null'")
        if v.strip().lower() == "string":
            raise ValueError(f"{field_name} cannot contain placeholder value 'string'")
        return v.strip()


class MedicalRecordResponse(BaseSchema):
    id: int
    patient_id: int
    doctor_id: int | None
    patient_name: str
    report_title: str
    report_type: str
    diagnosis: str | None
    symptoms: str | None = None
    notes: str | None
    file_name: str
    file_type: str | None
    file_path: str
    created_at: datetime
    updated_at: datetime


class MedicalRecordUpdate(BaseSchema):
    report_title: str | None = None
    report_type: str | None = None
    diagnosis: str | None = None
    notes: str | None = None

    @field_validator("report_title", "report_type")
    @classmethod
    def check_optional_string_fields(cls, v: str | None, info) -> str | None:
        if v is None:
            return v
        field_name = info.field_name.replace("_", " ").title()
        if not v.strip() or v.lower() == "null":
            raise ValueError(f"{field_name} cannot be blank or 'null'")
        if v.strip().lower() == "string":
            raise ValueError(f"{field_name} cannot contain placeholder value 'string'")
        cleaned = v.strip()
        if not re.match(r"^[a-zA-Z0-9\s\-\'\.]+$", cleaned):
            raise ValueError(f"{field_name} must contain only alphanumeric characters, spaces, hyphens, dots, or apostrophes")
        return cleaned

    @field_validator("diagnosis", "notes")
    @classmethod
    def check_optional_fields(cls, v: str | None, info) -> str | None:
        if v is None:
            return v
        field_name = info.field_name.replace("_", " ").title()
        if not v.strip() or v.lower() == "null":
            raise ValueError(f"{field_name} cannot be blank or 'null'")
        if v.strip().lower() == "string":
            raise ValueError(f"{field_name} cannot contain placeholder value 'string'")
        return v.strip()


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