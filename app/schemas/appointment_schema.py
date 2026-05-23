from datetime import date, datetime, time

from pydantic import Field

from app.schemas.common_schema import BaseSchema, PaginatedResponse


class AppointmentCreate(BaseSchema):
    patient_id: int
    doctor_id: int
    department_id: int | None = None
    appointment_date: date
    appointment_time: time
    appointment_type: str | None = None
    symptoms: str | None = None
    notes: str | None = None
    consultation_type: str | None = None


class AppointmentUpdate(BaseSchema):
    department_id: int | None = None
    appointment_date: date | None = None
    appointment_time: time | None = None
    appointment_type: str | None = None
    appointment_status: str | None = None
    symptoms: str | None = None
    notes: str | None = None
    consultation_type: str | None = None


class AppointmentResponse(BaseSchema):
    id: int
    appointment_number: str
    patient_id: int
    doctor_id: int
    department_id: int | None
    appointment_date: date
    appointment_time: time
    appointment_type: str | None
    appointment_status: str
    symptoms: str | None
    notes: str | None
    token_number: int | None
    consultation_type: str | None
    reminder_sent: bool
    created_at: datetime
    updated_at: datetime | None = None


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
    appointment_date: date | None = None
    page: int = 1
    size: int = 20


AppointmentListResponse = PaginatedResponse[AppointmentResponse]
