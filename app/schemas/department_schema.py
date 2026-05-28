from datetime import datetime
from pydantic import Field
from app.schemas.common_schema import BaseSchema

class DepartmentCreate(BaseSchema):
    department_name: str = Field(..., min_length=1, max_length=100, description="The name of the department")

class DepartmentUpdate(BaseSchema):
    department_name: str | None = Field(None, min_length=1, max_length=100, description="The name of the department")

class DepartmentResponse(BaseSchema):
    department_id: int
    department_name: str
    created_at: datetime
    updated_at: datetime
