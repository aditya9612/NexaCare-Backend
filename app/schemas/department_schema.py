from datetime import datetime
import re
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


class DepartmentCreate(BaseSchema):
    department_name: str = Field(..., min_length=1, max_length=100, description="The name of the department")

    @field_validator("department_name")
    @classmethod
    def validate_department_name(cls, value: str) -> str:
        res = validate_dept_name(value, required=True)
        if res is None:
            raise ValueError("Department name is required")
        return res


class DepartmentUpdate(BaseSchema):
    department_name: str | None = Field(None, min_length=1, max_length=100, description="The name of the department")

    @field_validator("department_name")
    @classmethod
    def validate_department_name(cls, value: str | None) -> str | None:
        return validate_dept_name(value, required=False)


class DepartmentResponse(BaseSchema):
    department_id: int
    department_name: str
    created_at: datetime
    updated_at: datetime
