from datetime import date, datetime, time
from enum import Enum
import re

from pydantic import EmailStr, Field, field_validator, model_validator

from app.schemas.auth_schema import GenderOption
from app.schemas.common_schema import BaseSchema, PaginatedResponse
from app.utils.common_validators import (
    validate_full_name as common_validate_full_name,
    validate_mobile as common_validate_mobile,
    validate_password as common_validate_password,
    validate_not_future_date as common_validate_not_future_date,
)


class DoctorGenderOption(str, Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"
    OTHER = "OTHER"

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            val_upper = value.strip().upper()
            for member in cls:
                if member.value == val_upper or member.name == val_upper:
                    return member
        return None


def validate_specialization_value(v: str | None) -> str | None:
    if v is None:
        return v
    if not v or v.lower() == "null" or v.lower() == "string":
        raise ValueError("Specialization cannot be blank, 'null', or 'string'")
    
    if v.startswith(" ") or v.endswith(" "):
        raise ValueError("Specialization should not contain leading or trailing spaces")
        
    if not v.strip():
        raise ValueError("Specialization cannot be only spaces")
        
    if not re.match(r"^[a-zA-Z\s\-/]+$", v):
        raise ValueError("Specialization must contain only letters, spaces, hyphens, or slashes")
        
    words = re.findall(r"[a-zA-Z]+", v)
    for w in words:
        is_title = w[0].isupper() and (len(w) == 1 or w[1:].islower())
        is_acronym = w.isupper() and len(w) <= 4
        if not (is_title or is_acronym):
            raise ValueError("Specialization must be properly formatted in Title Case or as a standard abbreviation (e.g., 'Cardiology', 'ENT')")
            
    return v


def validate_phone_number_india(v: str | None, required: bool = True) -> str | None:
    if v is None:
        if required:
            raise ValueError("Phone number is required")
        return v
    # Use common mobile validator, which returns exactly 10 digits
    res = common_validate_mobile(v, "Phone number")
    return res


def validate_password_strength(v: str) -> str:
    return common_validate_password(v)


def validate_availability_status(v: str | None, allow_unavailable: bool = True) -> str | None:
    if v is None:
        return v
    
    # Normalize to lowercase and strip all spaces/underscores
    v_norm = v.lower().strip().replace("_", "").replace(" ", "")
    if v_norm == "onleave":
        v = "onleave"
    elif v_norm == "available":
        v = "available"
    elif v_norm == "unavailable":
        v = "unavailable"

    allowed = {"available", "onleave"}
    if allow_unavailable:
        allowed.add("unavailable")
    if v not in allowed:
        raise ValueError(f"Availability status must be one of: {', '.join(sorted(allowed))}")
    return v


def validate_bio_field(v: str | None) -> str | None:
    if v is None:
        return None
    v_clean = v.strip()
    if not v_clean or v_clean.lower() in ("null", "string"):
        return None
    if len(v_clean) < 10:
        raise ValueError("Bio must be at least 10 characters in length")
    if len(v_clean) > 500:
        raise ValueError("Bio must not exceed 500 characters in length")
    return v_clean


def validate_dob_field(v: date | None) -> date | None:
    if v is None:
        return v
    # Use common past date check
    common_validate_not_future_date(v, "Date of birth")
    today = date.today()
    age = today.year - v.year - ((today.month, today.day) < (v.month, v.day))
    if age < 18:
        raise ValueError("Doctor must be at least 18 years old")
    return v


def validate_name_field(v: str | None, field_name: str) -> str | None:
    return common_validate_full_name(v, field_name)


def validate_license_number(v: str | None) -> str | None:
    if v is None:
        return v
    if not v or not v.strip() or v.lower() == "null" or v.lower() == "string":
        raise ValueError("License number cannot be blank, 'null', or 'string'")
    if v.startswith(" ") or v.endswith(" "):
        raise ValueError("License number must not contain leading or trailing spaces")
    if not v.isascii():
        raise ValueError("License number must contain only standard ASCII characters")
    # Allow only alphanumeric, hyphens, slashes
    if not re.match(r"^[a-zA-Z0-9\-\/]+$", v):
        raise ValueError("License number must contain only alphanumeric characters, hyphens, or slashes")
    return v


def validate_optional_string(v: str | None, field_name: str = "Field") -> str | None:
    if v is None:
        return None
    v_clean = v.strip()
    if not v_clean or v_clean.lower() in ("null", "string"):
        return None
    return v_clean
def trim_string_values(data: any) -> any:
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, str):
                data[k] = v.strip()
    return data


class DoctorOnboardCreate(BaseSchema):
    """Create a login account and doctor profile in one request."""

    @model_validator(mode="before")
    @classmethod
    def trim_spaces(cls, data: any) -> any:
        return trim_string_values(data)

    first_name: str
    last_name: str
    specialization: str
    qualification: str | None = None
    experience: int = Field(..., ge=0, le=60)
    phone: str
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=20)
    department_id: int | None = Field(None, gt=0)
    consultation_fee: float | None = Field(None, ge=0)
    license_number: str
    availability_status: str = "available"
    profile_image: str | None = None
    bio: str | None = None
    gender: DoctorGenderOption | None = None
    date_of_birth: date | None = None

    @field_validator("date_of_birth")
    @classmethod
    def dob_validation(cls, value: date | None) -> date | None:
        return validate_dob_field(value)

    @field_validator("specialization")
    @classmethod
    def validate_spec(cls, v: str) -> str:
        res = validate_specialization_value(v)
        if res is None:
            raise ValueError("Specialization cannot be blank")
        return res

    @field_validator("phone")
    @classmethod
    def validate_doctor_phone(cls, v: str) -> str:
        res = validate_phone_number_india(v, required=True)
        if res is None:
            raise ValueError("Phone number is required")
        return res

    @field_validator("password")
    @classmethod
    def validate_doctor_password(cls, v: str) -> str:
        return validate_password_strength(v)

    @field_validator("availability_status")
    @classmethod
    def validate_availability(cls, v: str) -> str:
        res = validate_availability_status(v, allow_unavailable=False)
        if res is None:
            raise ValueError("Availability status is required")
        return res

    @field_validator("bio")
    @classmethod
    def validate_bio(cls, v: str | None) -> str | None:
        return validate_bio_field(v)

    @field_validator("first_name")
    @classmethod
    def validate_first_name(cls, v: str) -> str:
        res = validate_name_field(v, "First name")
        if res is None:
            raise ValueError("First name cannot be blank")
        return res

    @field_validator("last_name")
    @classmethod
    def validate_last_name(cls, v: str) -> str:
        res = validate_name_field(v, "Last name")
        if res is None:
            raise ValueError("Last name cannot be blank")
        return res

    @field_validator("qualification")
    @classmethod
    def validate_qualification(cls, v: str | None) -> str | None:
        return validate_optional_string(v, "Qualification")

    @field_validator("license_number")
    @classmethod
    def validate_license(cls, v: str) -> str:
        res = validate_license_number(v)
        if res is None:
            raise ValueError("License number cannot be blank")
        return res

    @field_validator("profile_image")
    @classmethod
    def validate_profile_img(cls, v: str | None) -> str | None:
        return validate_optional_string(v, "Profile image")


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
    @model_validator(mode="before")
    @classmethod
    def trim_spaces(cls, data: any) -> any:
        return trim_string_values(data)

    first_name: str
    last_name: str
    specialization: str
    qualification: str | None = None
    experience: int = Field(..., ge=0, le=60)
    phone: str | None = None
    email: EmailStr | None = None
    department_id: int | None = Field(None, gt=0)
    consultation_fee: float | None = Field(None, ge=0)
    license_number: str
    availability_status: str = "available"
    profile_image: str | None = None
    bio: str | None = None
    user_id: int | None = Field(None, gt=0)

    @field_validator("specialization")
    @classmethod
    def validate_spec(cls, v: str) -> str:
        res = validate_specialization_value(v)
        if res is None:
            raise ValueError("Specialization cannot be blank")
        return res

    @field_validator("phone")
    @classmethod
    def validate_doctor_phone(cls, v: str | None) -> str | None:
        return validate_phone_number_india(v, required=False)

    @field_validator("availability_status")
    @classmethod
    def validate_availability(cls, v: str | None) -> str | None:
        return validate_availability_status(v, allow_unavailable=False)

    @field_validator("bio")
    @classmethod
    def validate_bio(cls, v: str | None) -> str | None:
        return validate_bio_field(v)

    @field_validator("first_name")
    @classmethod
    def validate_first_name(cls, v: str) -> str:
        res = validate_name_field(v, "First name")
        if res is None:
            raise ValueError("First name cannot be blank")
        return res

    @field_validator("last_name")
    @classmethod
    def validate_last_name(cls, v: str) -> str:
        res = validate_name_field(v, "Last name")
        if res is None:
            raise ValueError("Last name cannot be blank")
        return res

    @field_validator("qualification")
    @classmethod
    def validate_qualification(cls, v: str | None) -> str | None:
        return validate_optional_string(v, "Qualification")

    @field_validator("license_number")
    @classmethod
    def validate_license(cls, v: str) -> str:
        res = validate_license_number(v)
        if res is None:
            raise ValueError("License number cannot be blank")
        return res

    @field_validator("profile_image")
    @classmethod
    def validate_profile_img(cls, v: str | None) -> str | None:
        return validate_optional_string(v, "Profile image")


class DoctorUpdate(BaseSchema):
    @model_validator(mode="before")
    @classmethod
    def trim_spaces(cls, data: any) -> any:
        return trim_string_values(data)

    first_name: str | None = None
    last_name: str | None = None
    specialization: str | None = None
    qualification: str | None = None
    experience: int | None = Field(None, ge=0, le=60)
    phone: str | None = None
    email: EmailStr | None = None
    password: str | None = Field(None, min_length=8, max_length=20)
    department_id: int | None = Field(None, gt=0)
    consultation_fee: float | None = Field(None, ge=0)
    license_number: str | None = None
    availability_status: str | None = None
    profile_image: str | None = None
    bio: str | None = None
    gender: DoctorGenderOption | None = None
    date_of_birth: date | None = None

    @field_validator("date_of_birth")
    @classmethod
    def dob_validation(cls, value: date | None) -> date | None:
        return validate_dob_field(value)

    @field_validator("password")
    @classmethod
    def validate_doctor_password(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return validate_password_strength(v)

    @field_validator("specialization")
    @classmethod
    def validate_spec(cls, v: str | None) -> str | None:
        return validate_specialization_value(v)

    @field_validator("phone")
    @classmethod
    def validate_doctor_phone(cls, v: str | None) -> str | None:
        return validate_phone_number_india(v, required=False)

    @field_validator("availability_status")
    @classmethod
    def validate_availability(cls, v: str | None) -> str | None:
        return validate_availability_status(v, allow_unavailable=False)

    @field_validator("bio")
    @classmethod
    def validate_bio(cls, v: str | None) -> str | None:
        return validate_bio_field(v)

    @field_validator("first_name")
    @classmethod
    def validate_first_name(cls, v: str | None) -> str | None:
        return validate_name_field(v, "First name")

    @field_validator("last_name")
    @classmethod
    def validate_last_name(cls, v: str | None) -> str | None:
        return validate_name_field(v, "Last name")

    @field_validator("qualification")
    @classmethod
    def validate_qualification(cls, v: str | None) -> str | None:
        return validate_optional_string(v, "Qualification")

    @field_validator("license_number")
    @classmethod
    def validate_license(cls, v: str | None) -> str | None:
        return validate_license_number(v)

    @field_validator("profile_image")
    @classmethod
    def validate_profile_img(cls, v: str | None) -> str | None:
        return validate_optional_string(v, "Profile image")


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

    @field_validator("availability_status", mode="before")
    @classmethod
    def serialize_availability(cls, v: str | None) -> str | None:
        if v == "on_leave":
            return "onleave"
        return v


class DoctorOnboardResponse(BaseSchema):
    doctor: DoctorResponse
    user: DoctorOnboardUserSummary


class DoctorSearchQuery(BaseSchema):
    q: str = Field(..., min_length=1)
    page: int = 1
    size: int = 20


class DoctorAvailabilityUpdate(BaseSchema):
    availability_status: str

    @field_validator("availability_status")
    @classmethod
    def validate_availability(cls, v: str) -> str:
        res = validate_availability_status(v, allow_unavailable=False)
        if res is None:
            raise ValueError("Availability status is required")
        return res


class DoctorScheduleCreate(BaseSchema):
    day_of_week: int = Field(..., ge=1, le=7)
    start_time: time
    end_time: time
    slot_duration_minutes: int = Field(30, gt=0, le=180)

    @field_validator("start_time", "end_time", mode="after")
    @classmethod
    def strip_timezone(cls, v: time) -> time:
        if v.tzinfo is not None:
            return v.replace(tzinfo=None)
        return v

    @field_validator("day_of_week")
    @classmethod
    def map_day_of_week_to_db(cls, v: int) -> int:
        return v - 1

    @model_validator(mode="after")
    def validate_duration(self) -> "DoctorScheduleCreate":
        # Calculate duration in minutes
        dt_start = datetime.combine(date.today(), self.start_time)
        dt_end = datetime.combine(date.today(), self.end_time)

        if self.start_time >= self.end_time:
            raise ValueError("Start time must be before end time")

        duration = (dt_end - dt_start).total_seconds() / 60
        if duration < self.slot_duration_minutes:
            raise ValueError(
                f"Schedule duration must be at least the slot duration of {self.slot_duration_minutes} minutes"
            )
        return self


class DoctorScheduleUpdate(BaseSchema):
    day_of_week: int | None = Field(None, ge=1, le=7)
    start_time: time | None = None
    end_time: time | None = None
    slot_duration_minutes: int | None = Field(None, gt=0, le=180)
    is_active: bool | None = None

    @field_validator("start_time", "end_time", mode="after")
    @classmethod
    def strip_timezone(cls, v: time | None) -> time | None:
        if v is not None and v.tzinfo is not None:
            return v.replace(tzinfo=None)
        return v

    @field_validator("day_of_week")
    @classmethod
    def map_day_of_week_to_db(cls, v: int | None) -> int | None:
        if v is None:
            return v
        return v - 1



class DoctorScheduleResponse(BaseSchema):
    id: int
    doctor_id: int
    day_of_week: int
    start_time: time
    end_time: time
    slot_duration_minutes: int
    is_active: bool

    @field_validator("day_of_week", mode="before")
    @classmethod
    def map_day_of_week_to_ui(cls, v: int) -> int:
        return v + 1


DoctorListResponse = PaginatedResponse[DoctorResponse]


class DoctorPaginatedResult(BaseSchema):
    items: list[DoctorResponse]
    total: int
    page: int
    size: int
    pages: int
    total_doctors: int
    available_doctors: int
    on_leave_doctors: int


