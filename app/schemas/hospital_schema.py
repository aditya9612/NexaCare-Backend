from datetime import datetime
from pydantic import EmailStr, Field, field_validator, model_validator
from app.schemas.common_schema import BaseSchema
from app.utils.phone_utils import validate_phone_field

class HospitalBase(BaseSchema):
    name: str = Field(..., min_length=2, max_length=255)
    email: EmailStr
    phone: str | None = Field(None, max_length=20)
    address: str | None = Field(None, max_length=500)
    website: str | None = Field(None, max_length=255)

    @field_validator("name", "address", "website")
    @classmethod
    def strip_strings(cls, value: str | None) -> str | None:
        if value is not None:
            stripped = value.strip()
            if len(stripped) < 1:
                raise ValueError("Field cannot be empty or only spaces")
            return stripped
        return value

    @model_validator(mode="after")
    def validate_phone(self):
        if self.phone:
            self.phone = validate_phone_field(self.phone)
        return self

class HospitalCreate(HospitalBase):
    pass

class HospitalUpdate(BaseSchema):
    name: str | None = Field(None, min_length=2, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=20)
    address: str | None = Field(None, max_length=500)
    website: str | None = Field(None, max_length=255)
    is_active: bool | None = None

    @field_validator("name", "address", "website")
    @classmethod
    def strip_strings(cls, value: str | None) -> str | None:
        if value is not None:
            stripped = value.strip()
            if len(stripped) < 1:
                raise ValueError("Field cannot be empty or only spaces")
            return stripped
        return value

    @model_validator(mode="after")
    def validate_phone(self):
        if self.phone:
            self.phone = validate_phone_field(self.phone)
        return self

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

