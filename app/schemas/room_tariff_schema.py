from datetime import datetime
from pydantic import Field

from app.schemas.common_schema import BaseSchema


class RoomTariffCreate(BaseSchema):
    room_type: str = Field(..., description="e.g. ICU, Deluxe, Special, General Ward")
    daily_rate: float = Field(..., ge=0.0, description="Per day room charge in INR")
    nursing_charge_per_day: float = Field(default=0.0, ge=0.0, description="Per day nursing charge")
    doctor_visit_charge: float = Field(default=0.0, ge=0.0, description="Standard daily visiting doctor charge")
    description: str | None = None
    is_active: bool = True


class RoomTariffUpdate(BaseSchema):
    room_type: str | None = None
    daily_rate: float | None = Field(default=None, ge=0.0)
    nursing_charge_per_day: float | None = Field(default=None, ge=0.0)
    doctor_visit_charge: float | None = Field(default=None, ge=0.0)
    description: str | None = None
    is_active: bool | None = None


class RoomTariffResponse(BaseSchema):
    id: int
    room_type: str
    daily_rate: float
    nursing_charge_per_day: float
    doctor_visit_charge: float
    description: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
