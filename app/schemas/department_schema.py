from datetime import datetime
from pydantic import Field, field_validator
from app.schemas.common_schema import BaseSchema

class DepartmentCreate(BaseSchema):
    department_name: str = Field(..., min_length=1, max_length=100, description="The name of the department")

    @field_validator("department_name")
    @classmethod
    def validate_department_name(cls, value: str | None) -> str | None:
        if value is not None:
            stripped = value.strip()
            if len(stripped) < 1:
                raise ValueError("Department name cannot be empty or only spaces")
            return stripped
        return value

class DepartmentUpdate(BaseSchema):
    department_name: str | None = Field(None, min_length=1, max_length=100, description="The name of the department")

    @field_validator("department_name")
    @classmethod
    def validate_department_name(cls, value: str | None) -> str | None:
        if value is not None:
            stripped = value.strip()
            if len(stripped) < 1:
                raise ValueError("Department name cannot be empty or only spaces")
            return stripped
        return value

class DepartmentResponse(BaseSchema):
    department_id: int
    department_name: str
    created_at: datetime
    updated_at: datetime

