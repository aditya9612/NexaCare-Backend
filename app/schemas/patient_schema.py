from datetime import date, datetime

from pydantic import EmailStr, Field

from app.schemas.common_schema import BaseSchema, PaginatedResponse


class PatientCreate(BaseSchema):
    first_name: str
    last_name: str
    gender: str | None = None
    dob: date | None = None
    blood_group: str | None = None
    marital_status: str | None = None
    phone: str | None = None
    email: EmailStr | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    pincode: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_number: str | None = None
    allergies: str | None = None
    medical_history: str | None = None
    chronic_disease: str | None = None
    insurance_provider: str | None = None
    insurance_number: str | None = None
    status: str = "active"


class PatientUpdate(BaseSchema):
    first_name: str | None = None
    last_name: str | None = None
    gender: str | None = None
    dob: date | None = None
    blood_group: str | None = None
    marital_status: str | None = None
    phone: str | None = None
    email: EmailStr | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    pincode: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_number: str | None = None
    allergies: str | None = None
    medical_history: str | None = None
    chronic_disease: str | None = None
    insurance_provider: str | None = None
    insurance_number: str | None = None
    status: str | None = None


class PatientResponse(BaseSchema):
    id: int
    patient_code: str
    first_name: str
    last_name: str
    gender: str | None
    dob: date | None
    blood_group: str | None
    marital_status: str | None
    phone: str | None
    email: str | None
    address: str | None
    city: str | None
    state: str | None
    pincode: str | None
    emergency_contact_name: str | None
    emergency_contact_number: str | None
    allergies: str | None
    medical_history: str | None
    chronic_disease: str | None
    insurance_provider: str | None
    insurance_number: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class PatientSearchQuery(BaseSchema):
    q: str = Field(..., min_length=1)
    page: int = 1
    size: int = 20


class PatientFilterQuery(BaseSchema):
    gender: str | None = None
    blood_group: str | None = None
    city: str | None = None
    state: str | None = None
    status: str | None = None
    page: int = 1
    size: int = 20


class FamilyMemberCreate(BaseSchema):
    full_name: str
    relationship_type: str
    phone: str | None = None
    email: EmailStr | None = None


class FamilyMemberResponse(BaseSchema):
    id: int
    patient_id: int
    full_name: str
    relationship_type: str
    phone: str | None
    email: str | None


class PatientDocumentResponse(BaseSchema):
    id: int
    patient_id: int
    document_name: str
    document_type: str
    file_path: str
    created_at: datetime


PatientListResponse = PaginatedResponse[PatientResponse]
