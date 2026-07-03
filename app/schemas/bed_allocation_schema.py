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
def validate_bed_name(v: str | None) -> str | None:
    if v is None:
        return v
    stripped = v.strip()
    # Reject empty string, whitespace-only, and placeholders "null", "string"
    if not stripped or stripped.lower() == "null" or stripped.lower() == "string":
        raise ValueError("Bed name cannot be blank, 'null', or 'string'")
    # Reject multiple consecutive spaces
    if "  " in stripped:
        raise ValueError("Bed name must not contain multiple consecutive spaces")
    # Reject Unicode characters (must contain only ASCII)
    if not stripped.isascii():
        raise ValueError("Bed name must contain only standard ASCII characters")
    # Allow only ASCII alphabets, numbers, spaces, hyphens, or slashes
    import re
    if not re.match(r"^[a-zA-Z0-9\s\-\/]+$", stripped):
        raise ValueError("Bed name must contain only alphabetic characters, numbers, spaces, hyphens, or slashes")
    return stripped


def validate_description_or_notes(v: str | None, field_name: str) -> str | None:
    if v is None:
        return v
    stripped = v.strip()
    if not stripped or stripped.lower() == "null" or stripped.lower() == "string":
        raise ValueError(f"{field_name} cannot be blank, 'null', or 'string'")
    return stripped


def validate_date_range(v: datetime | None, field_name: str) -> datetime | None:
    if v is None:
        return v
    if v.year < 2000 or v.year > 2100:
        raise ValueError(f"{field_name} must be a valid date between 2000 and 2100")
    return v


class BedCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    type: BedType
    status: BedStatus = BedStatus.AVAILABLE

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        res = validate_bed_name(value)
        if res is None:
            raise ValueError("Bed name is required")
        return res


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
        return validate_bed_name(value)

    @field_validator("allocation_time", "admission_date")
    @classmethod
    def validate_dates(cls, value: Optional[datetime], info) -> Optional[datetime]:
        field_name = info.field_name.replace("_", " ").title()
        return validate_date_range(value, field_name)


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
def validate_room_name(v: str | None) -> str | None:
    if v is None:
        return v
    stripped = v.strip()
    # Reject empty string, whitespace-only, and placeholders "null", "string"
    if not stripped or stripped.lower() == "null" or stripped.lower() == "string":
        raise ValueError("Room name cannot be blank, 'null', or 'string'")
    # Reject multiple consecutive spaces
    if "  " in stripped:
        raise ValueError("Room name must not contain multiple consecutive spaces")
    # Reject Unicode characters (must contain only ASCII)
    if not stripped.isascii():
        raise ValueError("Room name must contain only standard ASCII characters")
    # Allow only ASCII alphabets and spaces
    import re
    if not re.match(r"^[a-zA-Z\s]+$", stripped):
        raise ValueError("Room name must contain only alphabetic characters and spaces")
    return stripped


class RoomCreate(BaseModel):
    number: int = Field(..., ge=1)
    name: str = Field(..., min_length=1, max_length=100)
    type: RoomType
    capacity: int = Field(..., ge=1)
    description: Optional[str] = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        res = validate_room_name(value)
        if res is None:
            raise ValueError("Room name is required")
        return res

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: Optional[str]) -> Optional[str]:
        return validate_description_or_notes(value, "Description")


class RoomUpdate(BaseModel):
    number: Optional[int] = Field(None, ge=1)
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    type: Optional[RoomType] = None
    capacity: Optional[int] = Field(None, ge=1)
    description: Optional[str] = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: Optional[str]) -> Optional[str]:
        return validate_room_name(value)

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: Optional[str]) -> Optional[str]:
        return validate_description_or_notes(value, "Description")


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
def validate_floor_name(v: str | None) -> str | None:
    if v is None:
        return v
    stripped = v.strip()
    # Reject empty string, whitespace-only, and placeholders "null", "string"
    if not stripped or stripped.lower() == "null" or stripped.lower() == "string":
        raise ValueError("Floor name cannot be blank, 'null', or 'string'")
    # Reject multiple consecutive spaces
    if "  " in stripped:
        raise ValueError("Floor name must not contain multiple consecutive spaces")
    # Reject Unicode characters (must contain only ASCII)
    if not stripped.isascii():
        raise ValueError("Floor name must contain only standard ASCII characters")
    # Allow only ASCII alphabets and spaces
    import re
    if not re.match(r"^[a-zA-Z\s]+$", stripped):
        raise ValueError("Floor name must contain only alphabetic characters and spaces")
    return stripped


class FloorCreate(BaseModel):
    number: int = Field(..., ge=0)
    name: str = Field(..., min_length=1, max_length=100)
    type: FloorType
    description: Optional[str] = None
    rooms: Optional[List[RoomCreate]] = []

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        res = validate_floor_name(value)
        if res is None:
            raise ValueError("Floor name is required")
        return res

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: Optional[str]) -> Optional[str]:
        return validate_description_or_notes(value, "Description")


class FloorUpdate(BaseModel):
    number: Optional[int] = Field(None, ge=0)
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    type: Optional[FloorType] = None
    description: Optional[str] = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: Optional[str]) -> Optional[str]:
        return validate_floor_name(value)

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: Optional[str]) -> Optional[str]:
        return validate_description_or_notes(value, "Description")


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
        return validate_description_or_notes(value, "Notes")

    @field_validator("admissionDate")
    @classmethod
    def validate_date(cls, value: datetime) -> datetime:
        res = validate_date_range(value, "admissionDate")
        if res is None:
            raise ValueError("admissionDate is required")
        return res


class BedReleaseRequest(BaseModel):
    dischargeNotes: Optional[str] = None

    @field_validator("dischargeNotes")
    @classmethod
    def strip_notes(cls, value: Optional[str]) -> Optional[str]:
        return validate_description_or_notes(value, "Discharge notes")


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
