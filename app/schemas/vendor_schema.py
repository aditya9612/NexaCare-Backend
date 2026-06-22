from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator
from app.schemas.common_schema import BaseSchema


class VendorCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    vendor_type: str = Field(..., pattern="^(expenses|inventory)$")
    contact_person: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=20)
    email: Optional[str] = Field(None, max_length=255)
    address: Optional[str] = Field(None)
    gst_number: Optional[str] = Field(None, max_length=50)
    service_type: Optional[str] = Field(None, max_length=100)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 1:
            raise ValueError("name cannot be empty or only spaces")
        return stripped

    @field_validator("contact_person", "phone", "email", "address", "gst_number", "service_type")
    @classmethod
    def strip_optional_strings(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            return value.strip()
        return value


class VendorUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    vendor_type: Optional[str] = Field(None, pattern="^(expenses|inventory)$")
    contact_person: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=20)
    email: Optional[str] = Field(None, max_length=255)
    address: Optional[str] = Field(None)
    gst_number: Optional[str] = Field(None, max_length=50)
    service_type: Optional[str] = Field(None, max_length=100)
    is_active: Optional[bool] = Field(None)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            stripped = value.strip()
            if len(stripped) < 1:
                raise ValueError("name cannot be empty or only spaces")
            return stripped
        return value

    @field_validator("contact_person", "phone", "email", "address", "gst_number", "service_type")
    @classmethod
    def strip_optional_strings(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            return value.strip()
        return value


class VendorResponse(BaseSchema):
    id: int
    name: str
    vendor_type: str
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    gst_number: Optional[str] = None
    service_type: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

