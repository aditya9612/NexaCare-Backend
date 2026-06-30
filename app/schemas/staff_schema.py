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


def validate_staff_password(v: str) -> str:
    if not v:
        raise ValueError("Password is required")
    if len(v) < 8 or len(v) > 20:
        raise ValueError("Password must be between 8 and 20 characters in length")
    if v.startswith(" ") or v.endswith(" "):
        raise ValueError("Password must not contain leading or trailing spaces")
    if not v.strip():
        raise ValueError("Password must not be only whitespace")
    if not v.isascii():
        raise ValueError("Password must contain only standard ASCII characters")
        
    if not any(c.isupper() for c in v):
        raise ValueError("Password must contain at least one uppercase letter")
    if not any(c.islower() for c in v):
        raise ValueError("Password must contain at least one lowercase letter")
    if not any(c.isdigit() for c in v):
        raise ValueError("Password must contain at least one numeric digit")
    if not any(not (c.isalnum() or c.isspace()) for c in v):
        raise ValueError("Password must contain at least one special character")
        
    common_passwords = {
        "password@123",
        "admin@123",
        "welcome@123",
        "qwerty@123",
        "12345678",
    }
    if v.lower() in common_passwords:
        raise ValueError("Password is too common or easily guessable")
        
    return v


def validate_staff_code(v: str | None) -> str | None:
    if v is None:
        return v
    if not v.strip() or v.lower() == "null":
        raise ValueError("Staff code cannot be empty or 'null'")
    if v.startswith(" ") or v.endswith(" "):
        raise ValueError("Staff code must not contain leading or trailing spaces")
    if not v.isascii():
        raise ValueError("Staff code must contain only standard ASCII characters")
    if not re.match(r"^[a-zA-Z0-9\-\/]+$", v):
        raise ValueError("Staff code must contain only alphanumeric characters, hyphens, or slashes")
    return v


def validate_staff_role_name(v: str | None) -> str | None:
    if v is None:
        return v
    stripped = v.strip()
    if not stripped or stripped.lower() == "null":
        raise ValueError("Role name cannot be empty or 'null'")
    
    allowed_roles = {"Nurse", "Receptionist", "Accountant", "Pharmacist", "Lab Technician"}
    restricted_roles = {"Doctor", "Patient", "Super Admin", "Hospital Admin"}
    
    if stripped in restricted_roles:
        raise ValueError(f"Role '{stripped}' is not allowed to be created as staff. Please use specialized onboarding flows.")
    if stripped not in allowed_roles:
        raise ValueError(f"Invalid staff role '{stripped}'. Must be one of: {', '.join(sorted(allowed_roles))}")
        
    return stripped


class StaffCreate(BaseSchema):
    full_name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr
    phone: str | None = Field(None, max_length=20)
    password: str = Field(..., min_length=8, max_length=20)
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

    @field_validator("password")
    @classmethod
    def check_password(cls, value: str) -> str:
        return validate_staff_password(value)

    @field_validator("staff_code")
    @classmethod
    def check_staff_code(cls, value: str) -> str:
        res = validate_staff_code(value)
        if res is None:
            raise ValueError("Staff code cannot be empty")
        return res

    @field_validator("role_name")
    @classmethod
    def check_role_name(cls, value: str) -> str:
        res = validate_staff_role_name(value)
        if res is None:
            raise ValueError("Role name cannot be empty")
        return res


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

    @field_validator("staff_code")
    @classmethod
    def check_staff_code(cls, value: str | None) -> str | None:
        return validate_staff_code(value)

    @field_validator("role_name")
    @classmethod
    def check_role_name(cls, value: str | None) -> str | None:
        return validate_staff_role_name(value)


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
