from datetime import datetime
from enum import Enum
import re
from pydantic import EmailStr, Field, field_validator

from app.schemas.common_schema import BaseSchema
from app.schemas.department_schema import DepartmentResponse
from app.schemas.rbac_schema import RoleResponse


class StaffStatus(int, Enum):
    ACTIVE = 1
    INACTIVE = 0


def validate_staff_name(v: str | None, field_name: str = "Full name") -> str | None:
    if v is None:
        return v
    # Reject empty string, whitespace-only, and "null"
    if not v or not v.strip() or v.lower() == "null":
        raise ValueError(f"{field_name} cannot be blank or 'null'")
    # Reject leading/trailing spaces
    if v.startswith(" ") or v.endswith(" "):
        raise ValueError(f"{field_name} must not contain leading or trailing spaces")
    # Reject multiple consecutive spaces
    if "  " in v:
        raise ValueError(f"{field_name} must not contain multiple consecutive spaces")
    # Reject Unicode characters (must contain only ASCII)
    if not v.isascii():
        raise ValueError(f"{field_name} must contain only standard ASCII characters")
    # Allow only ASCII alphabets, spaces, apostrophe, hyphen and dot
    if not re.match(r"^[a-zA-Z\s\-\'\.]+$", v):
        raise ValueError(f"{field_name} must contain only alphabetic characters, spaces, hyphens, dots, or apostrophes")
    return v


def validate_staff_phone(v: str | None) -> str | None:
    if v is None:
        raise ValueError("Phone number cannot be null")
    # Reject empty string and whitespace-only
    if not v or not v.strip() or v.lower() == "null":
        raise ValueError("Phone number cannot be blank or 'null'")
    # Reject leading/trailing spaces or in-between spaces
    if v.startswith(" ") or v.endswith(" "):
        raise ValueError("Phone number should not contain leading or trailing spaces")
    if " " in v:
        raise ValueError("Phone number should not contain spaces")
        
    raw_num = v
    if v.startswith("+91"):
        raw_num = v[3:]
    elif v.startswith("91") and len(v) == 12:
        raw_num = v[2:]
        
    if len(raw_num) != 10:
        raise ValueError("Phone number must contain exactly 10 digits")
        
    if not raw_num.isdigit():
        raise ValueError("Phone number must contain only numeric digits")
        
    if raw_num[0] not in {"6", "7", "8", "9"}:
        raise ValueError("Phone number must start with 6, 7, 8, or 9")
        
    if len(set(raw_num)) == 1:
        raise ValueError("Phone number cannot consist of repeated identical digits")
        
    return "+91" + raw_num


class StaffCreate(BaseSchema):
    full_name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr
    phone: str | None = Field(None, max_length=20)
    password: str = Field(..., min_length=6, max_length=100)
    staff_code: str = Field(..., min_length=1, max_length=50)
    department_id: int = Field(..., gt=0)
    role_name: str = Field(..., min_length=1, max_length=50)
    status: StaffStatus = StaffStatus.ACTIVE

    @field_validator("full_name")
    @classmethod
    def check_full_name(cls, value: str) -> str:
        return validate_staff_name(value)

    @field_validator("phone")
    @classmethod
    def check_phone(cls, value: str) -> str:
        return validate_staff_phone(value)

    @field_validator("staff_code", "role_name")
    @classmethod
    def strip_strings(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 1:
            raise ValueError("Field cannot be empty or only spaces")
        return stripped


class StaffUpdate(BaseSchema):
    full_name: str | None = Field(None, min_length=1, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=20)
    staff_code: str | None = Field(None, min_length=1, max_length=50)
    department_id: int | None = Field(None, gt=0)
    role_name: str | None = Field(None, min_length=1, max_length=50)
    status: StaffStatus | None = None

    @field_validator("full_name")
    @classmethod
    def check_full_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return validate_staff_name(value)

    @field_validator("phone")
    @classmethod
    def check_phone(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("Phone number cannot be null")
        return validate_staff_phone(value)

    @field_validator("staff_code", "role_name")
    @classmethod
    def strip_strings(cls, value: str | None) -> str | None:
        if value is not None:
            stripped = value.strip()
            if len(stripped) < 1:
                raise ValueError("Field cannot be empty or only spaces")
            return stripped
        return value


class StaffStatusUpdate(BaseSchema):
    status: StaffStatus


class StaffResponse(BaseSchema):
    id: int
    full_name: str
    email: str
    phone: str | None
    staff_code: str
    department_id: int
    role_name: str
    status: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None

    department: DepartmentResponse | None = None
    role: RoleResponse | None = None
