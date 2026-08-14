from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.core.constants import UserRole
from app.schemas.common_schema import BaseSchema
from app.utils.common_validators import (
    validate_full_name as common_validate_full_name,
    validate_mobile,
    validate_password,
    validate_not_future_date,
)

class RegisterRoleName(str, Enum):
    """All roles — use exact name in Swagger, or aliases like admin / super admin."""

    SUPER_ADMIN = UserRole.SUPER_ADMIN
    HOSPITAL_ADMIN = UserRole.HOSPITAL_ADMIN
    DOCTOR = UserRole.DOCTOR
    NURSE = UserRole.NURSE
    RECEPTIONIST = UserRole.RECEPTIONIST
    ACCOUNTANT = UserRole.ACCOUNTANT
    PHARMACIST = UserRole.PHARMACIST
    LAB_TECHNICIAN = UserRole.LAB_TECHNICIAN
    PATIENT = UserRole.PATIENT


_ROLE_NAME_ALIASES: dict[str, str] = {
    "admin": UserRole.HOSPITAL_ADMIN,
    "hospital admin": UserRole.HOSPITAL_ADMIN,
    "hospital_admin": UserRole.HOSPITAL_ADMIN,
    "super admin": UserRole.SUPER_ADMIN,
    "superadmin": UserRole.SUPER_ADMIN,
    "super_admin": UserRole.SUPER_ADMIN,
}


class GenderOption(str, Enum):
    MALE = "Male"
    FEMALE = "Female"
    OTHER = "Other"

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            val_upper = value.strip().upper()
            for member in cls:
                if member.value.upper() == val_upper or member.name == val_upper:
                    return member
        return None


class EmailOrPhoneRequest(BaseModel):
    email: EmailStr | None = None
    phone: str | None = Field(default=None, min_length=10, max_length=20)

    @model_validator(mode="after")
    def validate_identifier(self):
        if not self.email and not self.phone:
            raise ValueError("Either email or phone is required")
        if self.email and self.phone:
            raise ValueError("Provide either email or phone, not both")
        if self.phone:
            self.phone = validate_mobile(self.phone)
        return self


class LoginRequest(EmailOrPhoneRequest):
    password: str | None = None
    otp: str | None = None

    @model_validator(mode="after")
    def validate_login_credential(self):
        if not self.password and not self.otp:
            raise ValueError("Either password or otp is required")
        return self


class RegisterRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "email": "rahul.sharma@gmail.com",
                    "password": "SecurePass@123",
                    "full_name": "Rahul Sharma",
                    "phone": "9876543210",
                    "role_name": "Patient",
                    "gender": "Male",
                    "date_of_birth": "2001-08-15",
                }
            ]
        }
    )

    email: EmailStr = Field(..., description="Valid email address (used for login and OTP email)")
    password: str = Field(..., min_length=8, description="At least 8 characters")
    full_name: str = Field(..., min_length=2, max_length=255, description="Full legal name")
    phone: str | None = Field(
        default=None,
        min_length=10,
        max_length=20,
        description="Mobile number for SMS OTP (recommended). Example: 9876543210",
    )
    role_name: RegisterRoleName = Field(
        default=RegisterRoleName.PATIENT,
        description=(
            "Role from dropdown. Aliases: admin → Hospital Admin, super admin → Super Admin. "
            "Defaults to Patient."
        ),
    )
    role_id: int | None = Field(
        default=None,
        deprecated=True,
        description="Deprecated — use role_name instead. Must not be 0.",
    )
    gender: GenderOption | None = Field(default=None, description="Male, Female, or Other")
    date_of_birth: date | None = Field(
        default=None,
        description="Date of birth (YYYY-MM-DD). Must be in the past.",
    )

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str) -> str:
        return common_validate_full_name(value)

    @field_validator("phone")
    @classmethod
    def validate_phone_number(cls, v: str | None) -> str | None:
        if v is not None:
            return validate_mobile(v)
        return v

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        return validate_password(value)

    @field_validator("role_name", mode="before")
    @classmethod
    def normalize_role_name(cls, value):
        if isinstance(value, str):
            alias = _ROLE_NAME_ALIASES.get(value.strip().lower())
            if alias:
                return alias
        return value

    @field_validator("role_id")
    @classmethod
    def reject_invalid_role_id(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("role_id must be a positive number, or omit it and use role_name")
        return value

    @field_validator("date_of_birth")
    @classmethod
    def dob_in_past(cls, value: date | None) -> date | None:
        return validate_not_future_date(value, "date_of_birth")


class RegistrationRoleOption(BaseModel):
    id: int
    name: str
    description: str | None = None
    allowed_for_registration: bool


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class SendOTPRequest(EmailOrPhoneRequest):
    pass


class ForgotPasswordRequest(EmailOrPhoneRequest):
    pass


class ResetPasswordRequest(EmailOrPhoneRequest):
    otp: str
    new_password: str = Field(..., min_length=8)

    @field_validator("new_password")
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        return validate_password(value)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)

    @field_validator("new_password")
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        return validate_password(value)


class OTPVerifyRequest(EmailOrPhoneRequest):
    otp: str


class ActivateAccountRequest(EmailOrPhoneRequest):
    otp: str


class ProfileUpdateRequest(BaseModel):
    full_name: str | None = None
    phone: str | None = Field(default=None, min_length=10, max_length=20)
    gender: GenderOption | None = None
    date_of_birth: date | None = None
    profile_image: str | None = None

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return common_validate_full_name(value)

    @field_validator("profile_image")
    @classmethod
    def validate_profile_image(cls, value: str | None) -> str | None:
        if value is None:
            return None
        v_str = value.strip().lower()
        if v_str in ("", "null", "string", "none"):
            return None
        return value.strip()

    @field_validator("date_of_birth")
    @classmethod
    def dob_in_past(cls, value: date | None) -> date | None:
        return validate_not_future_date(value, "date_of_birth")

    @field_validator("phone")
    @classmethod
    def validate_phone_number(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return validate_mobile(value)



class UserProfileResponse(BaseSchema):
    id: int
    user_code: str
    full_name: str
    email: EmailStr
    phone: str | None
    role_id: int
    role_name: str | None = None
    profile_image: str | None
    gender: str | None
    date_of_birth: date | None
    is_active: bool
    is_verified: bool
    last_login: datetime | None
    created_at: datetime
    updated_at: datetime

class TOTPSetupResponse(BaseSchema):
    secret: str
    provisioning_uri: str

class TOTPEnableRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)

class TwoFAChallengeResponse(BaseSchema):
    challenge_token: str

class TOTPLoginRequest(BaseModel):
    challenge_token: str
    code: str = Field(..., min_length=6, max_length=10)

class Disable2FARequest(BaseModel):
    password: str = Field(..., min_length=8)
    code: str = Field(..., min_length=6, max_length=6)
