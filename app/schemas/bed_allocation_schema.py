from datetime import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator

from app.schemas.common_schema import BaseSchema
from app.schemas.patient_schema import PatientResponse


# Enums for validation
class BedStatus(str, Enum):
    AVAILABLE = "Available"
    OCCUPIED = "Occupied"
    RESERVED = "Reserved"
    CLEANING = "Cleaning"
    MAINTENANCE = "Maintenance"


class FloorType(str, Enum):
    GENERAL = "General"
    ICU = "ICU"
    EMERGENCY = "Emergency"
    DELUXE = "Deluxe"


class RoomType(str, Enum):
    GENERAL = "General"
    ICU = "ICU"
    EMERGENCY = "Emergency"
    DELUXE = "Deluxe"


class BedType(str, Enum):
    GENERAL = "General"
    ICU = "ICU"
    VENTILATOR = "Ventilator"
    DELUXE = "Deluxe"


# Bed Schemas
class BedCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    type: BedType
    status: BedStatus = BedStatus.AVAILABLE

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 1:
            raise ValueError("name cannot be empty or only spaces")
        return stripped


class BedUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    type: Optional[BedType] = None
    status: Optional[BedStatus] = None
    patient_id: Optional[int] = Field(None, gt=0)
    allocation_time: Optional[datetime] = None
    admission_date: Optional[datetime] = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            stripped = value.strip()
            if len(stripped) < 1:
                raise ValueError("name cannot be empty or only spaces")
            return stripped
        return value


class BedResponse(BaseSchema):
    id: int
    room_id: int
    name: str
    type: str
    status: str
    patient_id: Optional[int] = None
    allocation_time: Optional[datetime] = None
    admission_date: Optional[datetime] = None
    patient: Optional[PatientResponse] = None
    created_at: datetime
    updated_at: datetime


# Room Schemas
class RoomCreate(BaseModel):
    number: int = Field(..., ge=1)
    name: str = Field(..., min_length=1, max_length=100)
    type: RoomType
    capacity: int = Field(..., ge=1)
    description: Optional[str] = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 1:
            raise ValueError("name cannot be empty or only spaces")
        return stripped

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            return value.strip()
        return value


class RoomUpdate(BaseModel):
    number: Optional[int] = Field(None, ge=1)
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    type: Optional[RoomType] = None
    capacity: Optional[int] = Field(None, ge=1)
    description: Optional[str] = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            stripped = value.strip()
            if len(stripped) < 1:
                raise ValueError("name cannot be empty or only spaces")
            return stripped
        return value

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            return value.strip()
        return value


class RoomResponse(BaseSchema):
    id: int
    floor_id: int
    number: int
    name: str
    type: str
    capacity: int
    description: Optional[str] = None
    beds: List[BedResponse] = []
    created_at: datetime
    updated_at: datetime


# Floor Schemas
class FloorCreate(BaseModel):
    number: int = Field(..., ge=0)
    name: str = Field(..., min_length=1, max_length=100)
    type: FloorType
    description: Optional[str] = None
    rooms: Optional[List[RoomCreate]] = []

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 1:
            raise ValueError("name cannot be empty or only spaces")
        return stripped

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            return value.strip()
        return value


class FloorUpdate(BaseModel):
    number: Optional[int] = Field(None, ge=0)
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    type: Optional[FloorType] = None
    description: Optional[str] = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            stripped = value.strip()
            if len(stripped) < 1:
                raise ValueError("name cannot be empty or only spaces")
            return stripped
        return value

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            return value.strip()
        return value


class FloorResponse(BaseSchema):
    id: int
    number: int
    name: str
    type: str
    description: Optional[str] = None
    rooms: List[RoomResponse] = []
    created_at: datetime
    updated_at: datetime


# Bed Allocation Operations
class BedAllocationRequest(BaseModel):
    patientId: int = Field(..., gt=0)
    admissionDate: datetime
    notes: Optional[str] = None

    @field_validator("notes")
    @classmethod
    def strip_notes(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            return value.strip()
        return value

    @field_validator("admissionDate")
    @classmethod
    def validate_date(cls, value: datetime) -> datetime:
        if value.year < 2000 or value.year > 2100:
            raise ValueError("admissionDate must be a valid date between 2000 and 2100")
        return value


class BedReleaseRequest(BaseModel):
    dischargeNotes: Optional[str] = None

    @field_validator("dischargeNotes")
    @classmethod
    def strip_notes(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            return value.strip()
        return value


class BedTransferRequest(BaseModel):
    sourceBedId: int = Field(..., gt=0)
    targetBedId: int = Field(..., gt=0)


# Bed Activity Log Schemas
class BedActivityLogResponse(BaseSchema):
    id: int
    type: str
    message: str
    timestamp: datetime
    floor_id: Optional[int] = None
    room_id: Optional[int] = None
    bed_id: Optional[int] = None
    patient_id: Optional[int] = None


# Analytics Schemas
class BedAnalyticsSummaryResponse(BaseModel):
    total_floors: int
    total_rooms: int
    total_beds: int
    occupied_beds: int
    available_beds: int
    utilization_percentage: float


class ICUAnalyticsResponse(BaseModel):
    total_icu_beds: int
    occupied_icu_beds: int
    available_icu_beds: int
    icu_utilization_percentage: float
