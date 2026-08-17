from datetime import datetime
from typing import Optional

from pydantic import EmailStr, Field, field_validator
import zoneinfo

from app.schemas.common_schema import BaseSchema
from app.utils.phone_utils import validate_phone_field


# ---------------------------------------------------------
# HOSPITAL SETTINGS SCHEMAS
# ---------------------------------------------------------
class HospitalSettingResponse(BaseSchema):
    id: int
    hospital_id: int
    timezone: str
    currency: str
    gst_number: Optional[str] = None
    working_hours: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class HospitalSettingUpdate(BaseSchema):
    timezone: Optional[str] = Field(None, description="Timezone of the hospital")
    currency: Optional[str] = Field(None, description="Default currency code")
    gst_number: Optional[str] = Field(None, description="Hospital GST/Tax identifier")
    working_hours: Optional[str] = Field(None, description="Hospital working hours string")
    contact_email: Optional[EmailStr] = Field(None, description="Primary contact email")
    contact_phone: Optional[str] = Field(None, description="Primary contact phone number")

    @field_validator("timezone", mode="after")
    @classmethod
    def check_timezone(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in zoneinfo.available_timezones():
            raise ValueError(f"Invalid timezone: {v}")
        return v

    @field_validator("contact_phone", mode="after")
    @classmethod
    def check_phone(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return validate_phone_field(v)


# ---------------------------------------------------------
# NOTIFICATION SETTINGS SCHEMAS
# ---------------------------------------------------------
class NotificationSettingResponse(BaseSchema):
    id: int
    hospital_id: int
    sms_on_appointment: bool
    email_on_appointment: bool
    sms_on_billing: bool
    email_on_billing: bool
    created_at: datetime
    updated_at: datetime


class NotificationSettingUpdate(BaseSchema):
    sms_on_appointment: Optional[bool] = None
    email_on_appointment: Optional[bool] = None
    sms_on_billing: Optional[bool] = None
    email_on_billing: Optional[bool] = None


# ---------------------------------------------------------
# USER PREFERENCES SCHEMAS
# ---------------------------------------------------------
class UserPreferenceResponse(BaseSchema):
    id: int
    user_id: int
    theme: str
    language: str
    email_notifications: bool
    sms_notifications: bool
    compact_mode: bool
    push_notifications: bool
    critical_emergency_alerts: bool
    created_at: datetime
    updated_at: datetime


class UserPreferenceUpdate(BaseSchema):
    theme: Optional[str] = Field(None, description="UI theme preference, e.g., 'light' or 'dark'")
    language: Optional[str] = Field(None, description="Language code, e.g., 'en'")
    email_notifications: Optional[bool] = None
    sms_notifications: Optional[bool] = None
    compact_mode: Optional[bool] = None
    push_notifications: Optional[bool] = None
    critical_emergency_alerts: Optional[bool] = None

# ---------------------------------------------------------
# SYSTEM CONFIGURATION SCHEMAS (READ-ONLY)
# ---------------------------------------------------------
class SystemConfigResponse(BaseSchema):
    facility_name: Optional[str] = None
    network_node: Optional[str] = None
    platform_version: Optional[str] = None
    hipaa_enforced: Optional[bool] = None
