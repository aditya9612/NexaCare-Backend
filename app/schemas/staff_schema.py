from datetime import datetime
from enum import Enum
from pydantic import EmailStr, Field, field_validator, model_validator

from app.schemas.common_schema import BaseSchema
from app.schemas.department_schema import DepartmentResponse
from app.schemas.rbac_schema import RoleResponse
from app.utils.phone_utils import validate_phone_field


class StaffStatus(int, Enum):
    ACTIVE = 1
    INACTIVE = 0


class StaffCreate(BaseSchema):
    full_name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr
    phone: str | None = Field(None, max_length=20)
    staff_code: str = Field(..., min_length=1, max_length=50)
    department_id: int = Field(..., gt=0)
    role_name: str = Field(..., min_length=1, max_length=50)
    status: StaffStatus = StaffStatus.ACTIVE

    @field_validator("full_name", "staff_code", "role_name")
    @classmethod
    def strip_strings(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 1:
            raise ValueError("Field cannot be empty or only spaces")
        return stripped

    @model_validator(mode="after")
    def validate_phone(self):
        if self.phone:
            self.phone = validate_phone_field(self.phone)
        return self


class StaffUpdate(BaseSchema):
    full_name: str | None = Field(None, min_length=1, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=20)
    staff_code: str | None = Field(None, min_length=1, max_length=50)
    department_id: int | None = Field(None, gt=0)
    role_name: str | None = Field(None, min_length=1, max_length=50)
    status: StaffStatus | None = None

    @field_validator("full_name", "staff_code", "role_name")
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
