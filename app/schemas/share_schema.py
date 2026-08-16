from typing import Optional
from pydantic import Field, field_validator, EmailStr
from app.schemas.common_schema import BaseSchema


class ShareEmailRequest(BaseSchema):
    purpose: str = Field(..., description="Type of document to share: 'lab_report'")
    resource_id: int = Field(..., gt=0, description="Database ID of the resource")
    custom_email: Optional[EmailStr] = Field(None, description="Alternative recipient email address")

    @field_validator("purpose")
    @classmethod
    def validate_purpose(cls, value: str) -> str:
        cleaned = value.strip().lower()
        allowed_purposes = {"lab_report"}
        if cleaned not in allowed_purposes:
            raise ValueError(f"Invalid purpose. Supported: {', '.join(allowed_purposes)}")
        return cleaned
