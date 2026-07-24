from datetime import datetime, time
from typing import Optional
from pydantic import Field, field_validator, model_validator

from app.schemas.common_schema import BaseSchema
from app.core.constants import OperationMode

class AppointmentSettingsResponse(BaseSchema):
    id: int
    hospital_id: int
    operation_mode: OperationMode
    slot_duration_minutes: int
    working_start_time: time
    working_end_time: time
    lunch_break_enabled: bool
    lunch_start_time: Optional[time]
    lunch_end_time: Optional[time]
    max_advance_booking_days: int
    allow_overlapping: bool
    auto_cancel_no_show_minutes: int
    weekend_booking_enabled: bool
    buffer_between_slots_minutes: int
    allow_walk_in: bool
    created_at: datetime
    updated_at: datetime

class AppointmentSettingsUpdate(BaseSchema):
    operation_mode: Optional[OperationMode] = Field(None, description="Hospital operation mode")
    slot_duration_minutes: Optional[int] = Field(None, description="Slot duration in minutes")
    working_start_time: Optional[time] = Field(None, description="Start of working hours")
    working_end_time: Optional[time] = Field(None, description="End of working hours")
    lunch_break_enabled: Optional[bool] = Field(None, description="Is lunch break enabled")
    lunch_start_time: Optional[time] = Field(None, description="Start of lunch break")
    lunch_end_time: Optional[time] = Field(None, description="End of lunch break")
    max_advance_booking_days: Optional[int] = Field(None, ge=1, le=365, description="Maximum days in advance to book")
    allow_overlapping: Optional[bool] = Field(None, description="Allow overlapping appointments")
    auto_cancel_no_show_minutes: Optional[int] = Field(None, ge=0, le=240, description="Auto cancel no show after minutes")
    weekend_booking_enabled: Optional[bool] = Field(None, description="Allow weekend bookings")
    buffer_between_slots_minutes: Optional[int] = Field(None, ge=0, le=60, description="Buffer between slots in minutes")
    allow_walk_in: Optional[bool] = Field(None, description="Allow walk-in appointments")

    @field_validator("slot_duration_minutes")
    @classmethod
    def validate_slot_duration(cls, v: int | None) -> int | None:
        if v is not None and v not in (10, 15, 20, 30, 45, 60):
            raise ValueError("slot_duration_minutes must be one of 10, 15, 20, 30, 45, 60")
        return v

    @model_validator(mode="after")
    def validate_times(self) -> "AppointmentSettingsUpdate":
        ws = self.working_start_time
        we = self.working_end_time
        
        if self.operation_mode != OperationMode.TWENTY_FOUR_SEVEN:
            if ws is not None and we is not None:
                if ws >= we:
                    raise ValueError("working_start_time must be before working_end_time")

        if self.lunch_break_enabled:
            ls = self.lunch_start_time
            le = self.lunch_end_time
            if ls is None or le is None:
                raise ValueError("lunch_start_time and lunch_end_time are mandatory when lunch_break_enabled is True")
            
            if ls >= le:
                raise ValueError("lunch_start_time must be before lunch_end_time")

            if ws is not None and ls <= ws:
                raise ValueError("lunch_start_time must be after working_start_time")
            
            if we is not None and le >= we:
                raise ValueError("lunch_end_time must be before working_end_time")

        return self
