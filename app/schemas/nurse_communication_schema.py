from datetime import datetime
from typing import Literal

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
    emergency_type: str
    message: str


class EmergencyAlertResponse(BaseSchema):
    id: int
    patient_id: int
    nurse_id: int
    emergency_type: str
    message: str
    created_at: datetime
