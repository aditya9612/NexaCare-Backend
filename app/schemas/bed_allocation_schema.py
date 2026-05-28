from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field

from app.schemas.common_schema import BaseSchema
from app.schemas.patient_schema import PatientResponse


# Bed Schemas
class BedCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    type: str = Field(..., min_length=1, max_length=50)  # General, ICU, Ventilator, Deluxe, etc.
    status: Optional[str] = "Available"  # Available, Occupied, Reserved, Cleaning, Maintenance


class BedUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    type: Optional[str] = Field(None, min_length=1, max_length=50)
    status: Optional[str] = None
    patient_id: Optional[int] = None
    allocation_time: Optional[datetime] = None
    admission_date: Optional[datetime] = None


class BedResponse(BaseSchema):
    id: str
    room_id: str
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
    type: str = Field(..., min_length=1, max_length=50)
    capacity: int = Field(..., ge=1)
    description: Optional[str] = None


class RoomUpdate(BaseModel):
    number: Optional[int] = Field(None, ge=1)
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    type: Optional[str] = Field(None, min_length=1, max_length=50)
    capacity: Optional[int] = Field(None, ge=1)
    description: Optional[str] = None


class RoomResponse(BaseSchema):
    id: str
    floor_id: str
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
    type: str = Field(..., min_length=1, max_length=50)  # General, ICU, Emergency, Deluxe
    description: Optional[str] = None
    rooms: Optional[List[RoomCreate]] = []


class FloorUpdate(BaseModel):
    number: Optional[int] = Field(None, ge=0)
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    type: Optional[str] = Field(None, min_length=1, max_length=50)
    description: Optional[str] = None


class FloorResponse(BaseSchema):
    id: str
    number: int
    name: str
    type: str
    description: Optional[str] = None
    rooms: List[RoomResponse] = []
    created_at: datetime
    updated_at: datetime


# Bed Allocation Operations
class BedAllocationRequest(BaseModel):
    patientId: int
    admissionDate: datetime
    notes: Optional[str] = None


class BedReleaseRequest(BaseModel):
    dischargeNotes: Optional[str] = None


class BedTransferRequest(BaseModel):
    sourceBedId: str
    targetBedId: str


# Bed Activity Log Schemas
class BedActivityLogResponse(BaseSchema):
    id: str
    type: str
    message: str
    timestamp: datetime
    floor_id: Optional[str] = None
    room_id: Optional[str] = None
    bed_id: Optional[str] = None
    patient_id: Optional[str] = None


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
