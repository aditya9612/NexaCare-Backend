from datetime import datetime
from pydantic import EmailStr, Field
from app.schemas.common_schema import BaseSchema

class HospitalBase(BaseSchema):
    name: str = Field(..., min_length=2, max_length=255)
    email: EmailStr
    phone: str | None = Field(None, max_length=20)
    address: str | None = Field(None, max_length=500)
    website: str | None = Field(None, max_length=255)

class HospitalCreate(HospitalBase):
    pass

class HospitalUpdate(BaseSchema):
    name: str | None = Field(None, min_length=2, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=20)
    address: str | None = Field(None, max_length=500)
    website: str | None = Field(None, max_length=255)
    is_active: bool | None = None

class HospitalResponse(HospitalBase):
    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

class HospitalStatsResponse(BaseSchema):
    hospital_id: int
    total_doctors: int
    total_patients: int
    total_appointments: int
    revenue_summary: float
