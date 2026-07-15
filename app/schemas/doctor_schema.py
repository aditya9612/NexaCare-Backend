from datetime import date, datetime, time
from enum import Enum
import re

from pydantic import EmailStr, Field, field_validator, model_validator

from app.schemas.auth_schema import GenderOption
from app.schemas.common_schema import BaseSchema, PaginatedResponse


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


def validate_password_strength(v: str) -> str:
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
        return v
    if not v.strip() or v.lower() == "null":
        raise ValueError("Bio cannot be empty or 'null'")
    if len(v) < 10:
        raise ValueError("Bio must be at least 10 characters in length")
    if len(v) > 500:
        raise ValueError("Bio must not exceed 500 characters in length")
    return v


def validate_dob_field(v: date | None) -> date | None:
    if v is None:
        return v
    today = date.today()
    if v >= today:
        raise ValueError("Date of birth must be in the past")
    age = today.year - v.year - ((today.month, today.day) < (v.month, v.day))
    if age < 18:
        raise ValueError("Doctor must be at least 18 years old")
    return v


def validate_name_field(v: str | None, field_name: str) -> str | None:
    if v is None:
        return v
    # Reject empty string, whitespace-only, "null", and "string"
    if not v or not v.strip() or v.lower() == "null" or v.lower() == "string":
        raise ValueError(f"{field_name} cannot be blank, 'null', or 'string'")
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


def validate_optional_string(v: str | None, field_name: str) -> str | None:
    if v is None:
        return v
    if not v.strip() or v.lower() == "null" or v.lower() == "string":
        raise ValueError(f"{field_name} cannot be empty, 'null', or 'string'")
    if v.startswith(" ") or v.endswith(" "):
        raise ValueError(f"{field_name} must not contain leading or trailing spaces")
    return v
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
    department_id: int | None = Field(None, gt=0)
    consultation_fee: float | None = Field(None, ge=0)
    license_number: str | None = None
    availability_status: str | None = None
    profile_image: str | None = None
    bio: str | None = None

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
