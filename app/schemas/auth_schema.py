from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.core.constants import UserRole
from app.schemas.common_schema import BaseSchema
from app.utils.phone_utils import validate_phone_field


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
            self.phone = validate_phone_field(self.phone)
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
        import re
        if value is None:
            raise ValueError("Full name cannot be empty")
        name = value.strip()
        if len(name) < 1:
            raise ValueError("Full name cannot be empty or only spaces")
        if not re.match(r"^[a-zA-Z]+(?:\s[a-zA-Z]+)*$", name):
            raise ValueError("Full name must contain only alphabetic characters and single spaces between words")
        return name

    @field_validator("phone")
    @classmethod
    def validate_phone_number(cls, v: str | None) -> str | None:
        if v is not None:
            if " " in v:
                raise ValueError("Phone number must not contain spaces")
            import re
            if not re.match(r"^[0-9]+$", v):
                raise ValueError("Phone number must contain only numeric digits")
            if len(v) != 10:
                raise ValueError("Phone number must be exactly 10 digits")
            if v[0] not in ("6", "7", "8", "9"):
                raise ValueError("Phone number must start with 6, 7, 8, or 9")
            return v
        return v

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        has_upper = any(c.isupper() for c in value)
        has_lower = any(c.islower() for c in value)
        has_digit = any(c.isdigit() for c in value)
        import string
        has_special = any(c in string.punctuation or not c.isalnum() for c in value)
        
        if not (has_upper and has_lower and has_digit and has_special):
            raise ValueError("Password must include at least one uppercase letter, one lowercase letter, one number, and one special character")
        return value

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
        if value and value >= date.today():
            raise ValueError("date_of_birth must be in the past")
        return value

    @model_validator(mode="after")
    def validate_phone(self):
        if self.phone:
            self.phone = validate_phone_field(self.phone)
        return self


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
        has_upper = any(c.isupper() for c in value)
        has_lower = any(c.islower() for c in value)
        has_digit = any(c.isdigit() for c in value)
        import string
        has_special = any(c in string.punctuation or not c.isalnum() for c in value)
        
        if not (has_upper and has_lower and has_digit and has_special):
            raise ValueError("Password must include at least one uppercase letter, one lowercase letter, one number, and one special character")
        return value


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)

    @field_validator("new_password")
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        has_upper = any(c.isupper() for c in value)
        has_lower = any(c.islower() for c in value)
        has_digit = any(c.isdigit() for c in value)
        import string
        has_special = any(c in string.punctuation or not c.isalnum() for c in value)
        
        if not (has_upper and has_lower and has_digit and has_special):
            raise ValueError("Password must include at least one uppercase letter, one lowercase letter, one number, and one special character")
        return value


class OTPVerifyRequest(EmailOrPhoneRequest):
    otp: str


class ActivateAccountRequest(EmailOrPhoneRequest):
    otp: str


class ProfileUpdateRequest(BaseModel):
    full_name: str | None = None
    phone: str | None = Field(default=None, min_length=10, max_length=20)
    gender: str | None = None
    date_of_birth: date | None = None
    profile_image: str | None = None

    @field_validator("date_of_birth")
    @classmethod
    def dob_in_past(cls, value: date | None) -> date | None:
        if value and value >= date.today():
            raise ValueError("date_of_birth must be in the past")
        return value

    @model_validator(mode="after")
    def validate_phone(self):
        if self.phone:
            self.phone = validate_phone_field(self.phone)
        return self


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
