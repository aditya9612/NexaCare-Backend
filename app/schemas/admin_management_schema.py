from datetime import date, datetime
from pydantic import EmailStr, Field
from app.schemas.common_schema import BaseSchema

class AdminCreate(BaseSchema):
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=100)
    full_name: str = Field(..., min_length=2, max_length=255)
    phone: str | None = Field(None, max_length=20)
    hospital_id: int | None = None
    gender: str | None = Field(None, max_length=20)
    date_of_birth: date | None = None

class AdminUpdate(BaseSchema):
    full_name: str | None = Field(None, min_length=2, max_length=255)
    phone: str | None = Field(None, max_length=20)
    gender: str | None = Field(None, max_length=20)
    date_of_birth: date | None = None
    hospital_id: int | None = None
    is_active: bool | None = None

class AdminStatusUpdate(BaseSchema):
    is_active: bool

class AdminPasswordReset(BaseSchema):
    new_password: str = Field(..., min_length=6, max_length=100)

class AdminResponse(BaseSchema):
    id: int
    user_code: str
    email: EmailStr
    full_name: str
    phone: str | None
    role_id: int
    role_name: str | None = None
    hospital_id: int | None
    hospital_name: str | None = None
    profile_image: str | None
    gender: str | None
    date_of_birth: date | None
    is_active: bool
    is_verified: bool
    last_login: datetime | None
    created_at: datetime
    updated_at: datetime
