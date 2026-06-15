from datetime import date, datetime
from pydantic import EmailStr, Field, field_validator, model_validator
from app.schemas.common_schema import BaseSchema
from app.schemas.auth_schema import GenderOption
from app.utils.phone_utils import validate_phone_field

class UserCreate(BaseSchema):
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=100)
    full_name: str = Field(..., min_length=2, max_length=255)
    phone: str | None = Field(None, max_length=20)
    role_id: int = Field(..., gt=0)
    hospital_id: int | None = Field(None, gt=0)
    gender: GenderOption | None = None
    date_of_birth: date | None = None

    @field_validator("full_name", "password")
    @classmethod
    def strip_strings(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 1:
            raise ValueError("Field cannot be empty or only spaces")
        return stripped

    @model_validator(mode="after")
    def validate_phone(self):
        if self.phone:
            self.phone = validate_phone_field(self.phone)
        return self


class UserUpdate(BaseSchema):
    full_name: str | None = Field(None, min_length=2, max_length=255)
    phone: str | None = Field(None, max_length=20)
    gender: GenderOption | None = None
    date_of_birth: date | None = None
    profile_image: str | None = None
    is_active: bool | None = None
    hospital_id: int | None = Field(None, gt=0)

    @field_validator("full_name")
    @classmethod
    def strip_strings(cls, value: str | None) -> str | None:
        if value is not None:
            stripped = value.strip()
            if len(stripped) < 1:
                raise ValueError("Field cannot be empty or only spaces")
            return stripped
        return value

    @model_validator(mode="after")
    def validate_phone(self):
        if self.phone:
            self.phone = validate_phone_field(self.phone)
        return self



class UserResponse(BaseSchema):
    id: int
    user_code: str
    email: EmailStr
    full_name: str
    phone: str | None
    role_id: int
    role_name: str | None = None
    hospital_id: int | None = None
    profile_image: str | None
    gender: str | None
    date_of_birth: date | None
    is_active: bool
    is_verified: bool
    last_login: datetime | None
    created_at: datetime
    updated_at: datetime
