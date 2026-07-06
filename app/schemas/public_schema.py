from datetime import date, time
from typing import List, Optional
from pydantic import Field

from app.schemas.common_schema import BaseSchema


class SuggestedSlotPublic(BaseSchema):
    appointment_date: date
    appointment_time: time


class PublicDoctorWorkingDay(BaseSchema):
    day_of_week: int = Field(..., ge=0, le=6, description="0=Monday … 6=Sunday")
    day_name: str = Field(..., description="MONDAY, TUESDAY, …")
    start_time: time
    end_time: time
    slot_duration_minutes: int = 30


class PublicDoctorResponse(BaseSchema):
    id: int
    name: str
    specialty: str
    department: Optional[str] = None
    department_id: Optional[int] = None
    rating: float = 4.8
    experience: Optional[int] = None
    working_days: List[str] = Field(
        default_factory=list,
        description="Active working days, e.g. MONDAY, TUESDAY",
    )
    weekly_schedule: List[PublicDoctorWorkingDay] = Field(
        default_factory=list,
        description="Per-day schedule with day_name for UI display",
    )
    availability_slots: List[str] = []
    is_available_on_date: bool = Field(
        default=False,
        description="True when the doctor has an active schedule on the queried date",
    )


class QuickBookingRequest(BaseSchema):
    patient_name: str
    patient_phone: str
    doctor_id: int
    date: date
    time_slot: time
    symptoms: Optional[str] = None


class SymptomAnalysisRequest(BaseSchema):
    symptoms: str
    patient_name: Optional[str] = None
    patient_phone: Optional[str] = None
    gender: Optional[str] = None
    dob: Optional[date] = None


class SymptomAnalysisResponse(BaseSchema):
    urgency_level: str
    confidence_score: float
    specialty: str
    department: Optional[str] = None
    department_id: Optional[int] = None
    suggested_doctor_id: Optional[int] = None
    suggested_doctor_name: Optional[str] = None
    available_slots: List[SuggestedSlotPublic] = []
    insights: str


class ReportUploadResponse(BaseSchema):
    document_id: int
    file_name: str
    file_url: str


class AdvancedBookingRequest(BaseSchema):
    patient_name: str
    patient_phone: str
    gender: Optional[str] = None
    dob: Optional[date] = None
    email: Optional[str] = None
    urgency_level: str
    specialty: str
    confidence_score: float
    insights: str
    doctor_id: int
    booking_date: date
    booking_time: time
    document_id: Optional[int] = None
