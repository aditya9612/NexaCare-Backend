from datetime import datetime

from pydantic import Field

from app.schemas.common_schema import BaseSchema, PaginatedResponse


class NurseCreate(BaseSchema):
    user_id: int
    license_number: str
    department_id: int | None = None
    shift: str | None = None


class NurseUpdate(BaseSchema):
    license_number: str | None = None
    department_id: int | None = None
    shift: str | None = None


class NurseResponse(BaseSchema):
    id: int
    nurse_code: str
    user_id: int
    license_number: str
    department_id: int | None
    shift: str | None
    created_at: datetime
    updated_at: datetime


NurseListResponse = PaginatedResponse[NurseResponse]
