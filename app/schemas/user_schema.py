from datetime import date, datetime

from pydantic import EmailStr

from app.schemas.common_schema import BaseSchema


class UserCreate(BaseSchema):
    email: EmailStr
    password: str
    full_name: str
    phone: str | None = None
    role_id: int
    gender: str | None = None
    date_of_birth: date | None = None


class UserUpdate(BaseSchema):
    full_name: str | None = None
    phone: str | None = None
    gender: str | None = None
    date_of_birth: date | None = None
    profile_image: str | None = None
    is_active: bool | None = None


class UserResponse(BaseSchema):
    id: int
    user_code: str
    email: EmailStr
    full_name: str
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
