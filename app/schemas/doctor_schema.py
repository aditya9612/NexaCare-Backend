from datetime import date, datetime, time

from pydantic import EmailStr, Field, field_validator

from app.schemas.auth_schema import GenderOption
from app.schemas.common_schema import BaseSchema, PaginatedResponse


class DoctorOnboardCreate(BaseSchema):
    """Create a login account and doctor profile in one request."""

    first_name: str
    last_name: str
    specialization: str
    qualification: str | None = None
    experience: int | None = None
    phone: str | None = None
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=100)
    department_id: int | None = None
    consultation_fee: float | None = None
    license_number: str
    availability_status: str = "available"
    profile_image: str | None = None
    bio: str | None = None
    gender: GenderOption | None = None
    date_of_birth: date | None = None

    @field_validator("date_of_birth")
    @classmethod
    def dob_in_past(cls, value: date | None) -> date | None:
        if value and value >= date.today():
            raise ValueError("date_of_birth must be in the past")
        return value


class DoctorOnboardUserSummary(BaseSchema):
    id: int
    user_code: str
    email: str
    full_name: str
    phone: str | None
    role_name: str | None
    hospital_id: int | None
    gender: str | None
    date_of_birth: date | None
    is_active: bool


class DoctorCreate(BaseSchema):
    first_name: str
    last_name: str
    specialization: str
    qualification: str | None = None
    experience: int | None = None
    phone: str | None = None
    email: EmailStr | None = None
    department_id: int | None = None
    consultation_fee: float | None = None
    license_number: str
    availability_status: str = "available"
    profile_image: str | None = None
    bio: str | None = None
    user_id: int | None = None


class DoctorUpdate(BaseSchema):
    first_name: str | None = None
    last_name: str | None = None
    specialization: str | None = None
    qualification: str | None = None
    experience: int | None = None
    phone: str | None = None
    email: EmailStr | None = None
    department_id: int | None = None
    consultation_fee: float | None = None
    license_number: str | None = None
    availability_status: str | None = None
    profile_image: str | None = None
    bio: str | None = None


class DoctorResponse(BaseSchema):
    id: int
    doctor_code: str
    first_name: str
    last_name: str
    specialization: str
    qualification: str | None
    experience: int | None
    phone: str | None
    email: str | None
    department_id: int | None
    consultation_fee: float | None
    license_number: str
    availability_status: str
    profile_image: str | None
    bio: str | None
    created_at: datetime
    updated_at: datetime


class DoctorOnboardResponse(BaseSchema):
    doctor: DoctorResponse
    user: DoctorOnboardUserSummary


class DoctorSearchQuery(BaseSchema):
    q: str = Field(..., min_length=1)
    page: int = 1
    size: int = 20


class DoctorAvailabilityUpdate(BaseSchema):
    availability_status: str


class DoctorScheduleCreate(BaseSchema):
    day_of_week: int = Field(..., ge=0, le=6)
    start_time: time
    end_time: time
    slot_duration_minutes: int = 30


class DoctorScheduleResponse(BaseSchema):
    id: int
    doctor_id: int
    day_of_week: int
    start_time: time
    end_time: time
    slot_duration_minutes: int
    is_active: bool


DoctorListResponse = PaginatedResponse[DoctorResponse]
