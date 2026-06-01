from datetime import datetime
from pydantic import EmailStr, Field
from app.schemas.common_schema import BaseSchema

class BranchBase(BaseSchema):
    name: str = Field(..., min_length=2, max_length=255)
    phone: str | None = Field(None, max_length=20)
    email: EmailStr | None = None
    address: str | None = Field(None, max_length=500)

class BranchCreate(BranchBase):
    hospital_id: int | None = None

class BranchUpdate(BaseSchema):
    name: str | None = Field(None, min_length=2, max_length=255)
    phone: str | None = Field(None, max_length=20)
    email: EmailStr | None = None
    address: str | None = Field(None, max_length=500)
    is_active: bool | None = None

class BranchResponse(BranchBase):
    id: int
    hospital_id: int
    code: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
