from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field, field_validator
from app.schemas.common_schema import BaseSchema
from app.utils.validators import validate_gst_number


class VendorCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    vendor_type: str = Field(..., pattern="^(expense|expenses|inventory)$")
    contact_person: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=20)
    email: Optional[EmailStr] = Field(None, max_length=255)
    address: Optional[str] = Field(None)
    gst_number: Optional[str] = Field(None, max_length=50)
    service_type: Optional[str] = Field(None, max_length=100)

    @field_validator("vendor_type")
    @classmethod
    def validate_vendor_type(cls, value: str) -> str:
        if value == "expense":
            return "expenses"
        return value

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        import re
        stripped = value.strip()
        if len(stripped) < 1:
            raise ValueError("Vendor name cannot be empty or only spaces")
        if re.match(r"^[0-9\s]+$", stripped):
            raise ValueError("Vendor name must not be numeric-only")
        if not re.match(r"^[a-zA-Z0-9\s\-\&\.\(\)]+$", stripped):
            raise ValueError("Vendor name contains invalid characters")
        return stripped

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            stripped = value.strip()
            if stripped != "":
                from app.utils.phone_utils import validate_phone_field
                return validate_phone_field(stripped)
            return None
        return value

    @field_validator("email")
    @classmethod
    def strip_email(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            return value.strip()
        return value

    @field_validator("contact_person")
    @classmethod
    def validate_contact_person(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            import re
            stripped = value.strip()
            if len(stripped) < 1:
                raise ValueError("Contact person cannot be empty or only spaces")
            if re.match(r"^[0-9\s]+$", stripped):
                raise ValueError("Contact person must not be numeric-only")
            if not re.match(r"^[a-zA-Z\s\.\'\-]+$", stripped):
                raise ValueError("Contact person name contains invalid characters")
            return stripped
        return value

    @field_validator("address")
    @classmethod
    def validate_address(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            import re
            stripped = value.strip()
            if len(stripped) < 1:
                raise ValueError("Address cannot be empty or only spaces")
            if re.match(r"^[0-9\s]+$", stripped):
                raise ValueError("Address must not be numeric-only")
            if not re.match(r"^[a-zA-Z0-9\s\,\-\/\.\(\)]+$", stripped):
                raise ValueError("Address contains invalid characters")
            return stripped
        return value

    @field_validator("service_type")
    @classmethod
    def validate_service_type(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            import re
            stripped = value.strip()
            if len(stripped) < 1:
                raise ValueError("Service type cannot be empty or only spaces")
            if re.match(r"^[0-9\s]+$", stripped):
                raise ValueError("Service type must not be numeric-only")
            if not re.match(r"^[a-zA-Z0-9\s\-\&\(\)]+$", stripped):
                raise ValueError("Service type contains invalid characters")
            return stripped
        return value

    @field_validator("gst_number")
    @classmethod
    def validate_gst(cls, value: Optional[str]) -> Optional[str]:
        return validate_gst_number(value)


class VendorUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    vendor_type: Optional[str] = Field(None, pattern="^(expense|expenses|inventory)$")
    contact_person: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=20)
    email: Optional[EmailStr] = Field(None, max_length=255)
    address: Optional[str] = Field(None)
    gst_number: Optional[str] = Field(None, max_length=50)
    service_type: Optional[str] = Field(None, max_length=100)
    is_active: Optional[bool] = Field(None)

    @field_validator("vendor_type")
    @classmethod
    def validate_vendor_type(cls, value: Optional[str]) -> Optional[str]:
        if value == "expense":
            return "expenses"
        return value

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            import re
            stripped = value.strip()
            if len(stripped) < 1:
                raise ValueError("Vendor name cannot be empty or only spaces")
            if re.match(r"^[0-9\s]+$", stripped):
                raise ValueError("Vendor name must not be numeric-only")
            if not re.match(r"^[a-zA-Z0-9\s\-\&\.\(\)]+$", stripped):
                raise ValueError("Vendor name contains invalid characters")
            return stripped
        return value

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            stripped = value.strip()
            if stripped != "":
                from app.utils.phone_utils import validate_phone_field
                return validate_phone_field(stripped)
            return None
        return value

    @field_validator("email")
    @classmethod
    def strip_email(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            return value.strip()
        return value

    @field_validator("contact_person")
    @classmethod
    def validate_contact_person(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            import re
            stripped = value.strip()
            if len(stripped) < 1:
                raise ValueError("Contact person cannot be empty or only spaces")
            if re.match(r"^[0-9\s]+$", stripped):
                raise ValueError("Contact person must not be numeric-only")
            if not re.match(r"^[a-zA-Z\s\.\'\-]+$", stripped):
                raise ValueError("Contact person name contains invalid characters")
            return stripped
        return value

    @field_validator("address")
    @classmethod
    def validate_address(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            import re
            stripped = value.strip()
            if len(stripped) < 1:
                raise ValueError("Address cannot be empty or only spaces")
            if re.match(r"^[0-9\s]+$", stripped):
                raise ValueError("Address must not be numeric-only")
            if not re.match(r"^[a-zA-Z0-9\s\,\-\/\.\(\)]+$", stripped):
                raise ValueError("Address contains invalid characters")
            return stripped
        return value

    @field_validator("service_type")
    @classmethod
    def validate_service_type(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            import re
            stripped = value.strip()
            if len(stripped) < 1:
                raise ValueError("Service type cannot be empty or only spaces")
            if re.match(r"^[0-9\s]+$", stripped):
                raise ValueError("Service type must not be numeric-only")
            if not re.match(r"^[a-zA-Z0-9\s\-\&\(\)]+$", stripped):
                raise ValueError("Service type contains invalid characters")
            return stripped
        return value

    @field_validator("gst_number")
    @classmethod
    def validate_gst(cls, value: Optional[str]) -> Optional[str]:
        return validate_gst_number(value)


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

