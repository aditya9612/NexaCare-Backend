from datetime import date, datetime, time

from pydantic import Field, field_validator, model_validator

from app.core.constants import BookingSource
from app.schemas.common_schema import BaseSchema, PaginatedResponse


class AppointmentCreate(BaseSchema):
    patient_id: int
    doctor_id: int
    department_id: int | None = None
    appointment_date: date
    appointment_time: time
    appointment_type: str | None = None
    booking_source: BookingSource | None = Field(
        default=None,
        description="Booking channel: staff, patient_portal, ai_chat, or ai_voice",
    )
    symptoms: str | None = None
    notes: str | None = None
    consultation_type: str | None = None
    patient_name: str | None = None
    age: int | None = None
    patient_mobile_number: str | None = None
    admission_status: str | None = None
    admission_recommended: bool | None = False
    admission_reason: str | None = None
    expected_los: int | None = None
    recommended_ward: str | None = None

    @field_validator("booking_source", mode="before")
    @classmethod
    def normalize_booking_source(cls, v):
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        if isinstance(v, str):
            return v.strip().lower()
        return v


class AppointmentUpdate(BaseSchema):
    department_id: int | None = None
    appointment_date: date | None = None
    appointment_time: time | None = None
    appointment_type: str | None = None
    booking_source: BookingSource | None = Field(
        default=None,
        description="Booking channel: staff, patient_portal, ai_chat, or ai_voice",
    )
    appointment_status: str | None = None
    symptoms: str | None = None
    notes: str | None = None
    consultation_type: str | None = None
    admission_status: str | None = None
    admission_recommended: bool | None = None
    admission_reason: str | None = None
    expected_los: int | None = None
    recommended_ward: str | None = None

    @field_validator("booking_source", mode="before")
    @classmethod
    def normalize_booking_source(cls, v):
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        if isinstance(v, str):
            return v.strip().lower()
        return v

    @field_validator("appointment_time")
    @classmethod
    def validate_time_not_null(cls, v):
        if v is None:
            raise ValueError("appointment_time cannot be null. Omit the field if you do not want to update the appointment time.")
        return v


class AppointmentResponse(BaseSchema):
    id: int
    appointment_number: str
    patient_id: int
    doctor_id: int
    department_id: int | None
    appointment_date: date
    appointment_time: time
    appointment_type: str | None
    booking_source: str | None = None
    appointment_status: str
    symptoms: str | None
    notes: str | None
    token_number: int | None
    consultation_type: str | None
    reminder_sent: bool
    created_at: datetime
    updated_at: datetime | None = None
    patient_name: str | None = None
    age: int | None = None
    patient_mobile_number: str | None = None
    
    # Receptionist Queue fields
    check_in_time: datetime | None = None
    check_out_time: datetime | None = None
    queue_token: str | None = None
    queue_status: str | None = None

    # Admission Recommendation fields
    admission_status: str | None = None
    admission_recommended: bool = False
    admission_reason: str | None = None
    expected_los: int | None = None
    recommended_ward: str | None = None

    cancellation_reason: str | None = None

    @field_validator("admission_recommended", mode="before")
    @classmethod
    def coerce_admission_recommended(cls, v):
        return bool(v) if v is not None else False

    @model_validator(mode="after")
    def populate_cancellation_reason(self) -> "AppointmentResponse":
        from app.core.constants import AppointmentStatus
        if self.appointment_status in ("cancelled", AppointmentStatus.CANCELLED):
            self.cancellation_reason = self.notes
        return self


class AdmitRecommendationRequest(BaseSchema):
    diagnosis: str | None = None
    admission_reason: str = Field(..., min_length=1)
    expected_los: int | None = Field(None, ge=1)
    recommended_ward: str | None = None
    notes: str | None = None


class AdmitRecommendationResponse(BaseSchema):
    appointment_id: int
    patient_id: int
    doctor_id: int
    appointment_status: str
    admission_status: str | None = None
    admission_recommended: bool
    admission_reason: str | None = None
    expected_los: int | None = None
    recommended_ward: str | None = None
    diagnosis: str | None = None
    notes: str | None = None


class PendingAdmissionPatientInfo(BaseSchema):
    id: int
    patient_code: str
    first_name: str
    last_name: str
    gender: str | None = None
    age: int | None = None
    phone: str | None = None


class PendingAdmissionDoctorInfo(BaseSchema):
    id: int
    first_name: str
    last_name: str
    specialization: str | None = None
    department_name: str | None = None


class PendingAdmissionItem(BaseSchema):
    appointment_id: int
    patient_id: int
    appointment_number: str
    appointment_date: date
    appointment_status: str
    admission_status: str | None = None
    admission_recommended: bool
    admission_reason: str | None = None
    expected_los: int | None = None
    recommended_ward: str | None = None
    diagnosis: str | None = None
    patient: PendingAdmissionPatientInfo
    doctor: PendingAdmissionDoctorInfo
    created_at: datetime



class AppointmentCheckInResponse(BaseSchema):
    id: int
    appointment_number: str
    check_in_time: datetime
    appointment_status: str


class AppointmentCheckOutResponse(BaseSchema):
    id: int
    appointment_number: str
    check_out_time: datetime
    appointment_status: str


class QueueTokenResponse(BaseSchema):
    appointment_id: int
    queue_token: str
    queue_status: str


class QueueStatusResponse(BaseSchema):
    appointment_id: int
    queue_token: str | None = None
    queue_status: str


class TokenResponse(BaseSchema):
    appointment_id: int
    token_number: int    


class RescheduleRequest(BaseSchema):
    appointment_id: int
    appointment_date: date
    appointment_time: time
    notes: str | None = None


class CancelRequest(BaseSchema):
    appointment_id: int
    reason: str | None = None


class ConfirmRequest(BaseSchema):
    appointment_id: int


class CalendarQuery(BaseSchema):
    doctor_id: int | None = None
    start_date: date
    end_date: date


class AppointmentFilterQuery(BaseSchema):
    patient_id: int | None = None
    doctor_id: int | None = None
    department_id: int | None = None
    status: str | None = None
    admission_status: str | None = None
    appointment_date: date | None = None
    appointment_type: str | None = None
    booking_source: BookingSource | None = None
    page: int = 1
    size: int = 20


AppointmentListResponse = PaginatedResponse[AppointmentResponse]


class DoctorAppointmentListResponse(BaseSchema):
    items: list[AppointmentResponse]
    total: int



class AppointmentListWithCountsResponse(PaginatedResponse[AppointmentResponse]):
    total_appointments: int
    today_appointments: int
    total_scheduled: int
    completed: int
    cancelled: int
    pending: int = 0
    confirmed: int = 0
    in_progress: int = 0
    checked_in: int = 0
    checked_out: int = 0
    admitted: int = 0

class ConfirmedVisitResponse(BaseSchema):
    appointment_id: int
    appointment_number: str
    patient_id: int
    patient_name: str
    doctor_id: int
    doctor_name: str
    department_name: str | None = None
    appointment_date: date
    appointment_time: time
    status: str
    check_in_time: datetime | None = None
    queue_token: str | None = None
    queue_status: str | None = None


ConfirmedVisitListResponse = PaginatedResponse[ConfirmedVisitResponse]


class ScheduledDoctorResponse(BaseSchema):
    doctor_id: int
    first_name: str
    last_name: str
    specialization: str | None = None
    department_id: int | None = None
    consultation_fee: float | None = None
    day_of_week: int
    start_time: time
    end_time: time
    slot_duration_minutes: int
    is_available: bool


