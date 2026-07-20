from datetime import datetime
import re
from typing import Optional
from pydantic import Field, field_validator
from app.schemas.common_schema import BaseSchema


def validate_dept_name(value: str | None, required: bool = True) -> str | None:
    if value is None:
        if required:
            raise ValueError("Department name is required")
        return value
        
    # Check for empty / whitespace / null string
    if not value or not value.strip() or value.lower() == "null":
        raise ValueError("Department name cannot be blank or 'null'")
        
    # Check for leading/trailing spaces
    if value.startswith(" ") or value.endswith(" "):
        raise ValueError("Department name should not contain leading or trailing spaces")
        
    stripped = value.strip()
    
    # Check if only contains alphabets and spaces
    if not re.match(r"^[a-zA-Z\s]+$", stripped):
        raise ValueError("Department name must contain only alphabets and spaces")
        
    if "  " in stripped:
        raise ValueError("Department name should not contain consecutive spaces")
        
    return stripped


def validate_dept_code(value: str | None, required: bool = False) -> str | None:
    if value is None:
        return value

    if not value or not value.strip():
        raise ValueError("Department code cannot be blank")

    value = value.strip().upper()

    if not re.match(r"^[A-Z0-9\-]+$", value):
        raise ValueError("Department code must contain only letters, digits, or hyphens")

    if len(value) > 20:
        raise ValueError("Department code must not exceed 20 characters")

    return value


class DepartmentCreate(BaseSchema):
    department_code: Optional[str] = Field(None, max_length=20, description="Unique short code for the department (e.g. CARD, OPD-01)")
    department_name: str = Field(..., min_length=1, max_length=100, description="The name of the department")

    @field_validator("department_code")
    @classmethod
    def validate_department_code(cls, value: str | None) -> str | None:
        return validate_dept_code(value)

    @field_validator("department_name")
    @classmethod
    def validate_department_name(cls, value: str) -> str:
        res = validate_dept_name(value, required=True)
        if res is None:
            raise ValueError("Department name is required")
        return res


class DepartmentUpdate(BaseSchema):
    department_code: Optional[str] = Field(None, max_length=20, description="Unique short code for the department")
    department_name: str | None = Field(None, min_length=1, max_length=100, description="The name of the department")

    @field_validator("department_code")
    @classmethod
    def validate_department_code(cls, value: str | None) -> str | None:
        return validate_dept_code(value)

    @field_validator("department_name")
    @classmethod
    def validate_department_name(cls, value: str | None) -> str | None:
        return validate_dept_name(value, required=False)


class DepartmentResponse(BaseSchema):
    department_id: int
    department_code: Optional[str] = None
    department_name: str
    created_at: datetime
    updated_at: datetime
