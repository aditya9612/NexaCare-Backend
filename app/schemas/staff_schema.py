from datetime import datetime, time
from enum import Enum
import re
from pydantic import EmailStr, Field, field_validator

from app.schemas.common_schema import BaseSchema, PaginatedResponse
from app.schemas.department_schema import DepartmentResponse
from app.schemas.rbac_schema import RoleResponse
from app.utils.common_validators import (
    validate_full_name as common_validate_full_name,
    validate_mobile as common_validate_mobile,
    validate_password as common_validate_password,
    validate_code_identifier as common_validate_code_identifier,
    validate_start_end_times as common_validate_start_end_times,
)

class StaffStatus(int, Enum):
    ACTIVE = 1
    INACTIVE = 0


def validate_staff_name(v: str | None, field_name: str = "Full name") -> str | None:
    return common_validate_full_name(v, field_name)


def validate_staff_phone(v: str | None) -> str | None:
    if v is not None:
        return common_validate_mobile(v, "Phone number")
    return v


def validate_staff_password(v: str) -> str:
    return common_validate_password(v)


def validate_staff_code(v: str | None) -> str | None:
    return common_validate_code_identifier(v, "Staff code")


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


class StaffListWithCountsResponse(PaginatedResponse[StaffResponse]):
    total_staff: int
    active_staff: int
    inactive_staff: int


class StaffScheduleCreate(BaseSchema):
    day_of_week: int = Field(..., ge=0, le=6, description="0=Monday, 6=Sunday")
    start_time: time
    end_time: time
    slot_duration_minutes: int = Field(30, ge=5, le=1440)
    is_active: bool = True

    @field_validator("end_time")
    @classmethod
    def validate_time_range(cls, v, info):
        start = info.data.get("start_time")
        if start:
            return common_validate_start_end_times(start, v)
        return v


class StaffScheduleResponse(BaseSchema):
    id: int
    staff_id: int
    day_of_week: int
    start_time: time
    end_time: time
    slot_duration_minutes: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
