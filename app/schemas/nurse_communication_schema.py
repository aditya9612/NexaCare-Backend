from datetime import datetime
from typing import Literal
from pydantic import Field

from app.schemas.common_schema import BaseSchema


class PatientUpdateCreate(BaseSchema):
    patient_id: int
    update_type: str
    message: str
    severity: Literal["NORMAL", "WARNING", "CRITICAL"]


class PatientUpdateResponse(BaseSchema):
    update_id: int
    patient_id: int
    nurse_name: str
    update_type: str
    message: str
    severity: str
    created_at: datetime


class EmergencyAlertCreate(BaseSchema):
    patient_id: int
    appointment_id: int = Field(..., description="Appointment ID (Required, cannot be null)")
    emergency_type: str = Field(..., min_length=1, max_length=100)
    message: str = Field(..., min_length=1)


class EmergencyAlertUpdate(BaseSchema):
    appointment_id: int | None = None
    emergency_type: str | None = None
    message: str | None = None


class EmergencyAlertResponse(BaseSchema):
    id: int
    patient_id: int
    nurse_id: int
    appointment_id: int | None = None
    appointment_number: str | None = None
    doctor_id: int | None = None
    doctor_name: str | None = None
    emergency_type: str
    message: str
    status: str = "pending"
    acknowledged_at: datetime | None = None
    acknowledged_by: int | None = None
    created_at: datetime
