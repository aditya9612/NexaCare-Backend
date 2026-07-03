from datetime import date, datetime, time
from typing import Literal

from pydantic import Field, field_validator

from app.schemas.common_schema import BaseSchema, PaginatedResponse


class NurseCreate(BaseSchema):
    user_id: int = Field(..., gt=0)
    license_number: str = Field(..., min_length=1, max_length=100)
    department_id: int | None = Field(None, gt=0)
    shift: str | None = Field(None, min_length=1, max_length=50)

    @field_validator("license_number")
    @classmethod
    def validate_license(cls, v: str) -> str:
        stripped = v.strip()
        if len(stripped) < 1:
            raise ValueError("license_number cannot be empty or only spaces")
        return stripped

    @field_validator("shift")
    @classmethod
    def validate_shift(cls, v: str | None) -> str | None:
        if v is not None:
            stripped = v.strip()
            if len(stripped) < 1:
                raise ValueError("shift cannot be empty or only spaces")
            return stripped
        return v


class NurseUpdate(BaseSchema):
    license_number: str | None = Field(None, min_length=1, max_length=100)
    department_id: int | None = Field(None, gt=0)
    shift: str | None = Field(None, min_length=1, max_length=50)

    @field_validator("license_number")
    @classmethod
    def validate_license(cls, v: str | None) -> str | None:
        if v is not None:
            stripped = v.strip()
            if len(stripped) < 1:
                raise ValueError("license_number cannot be empty or only spaces")
            return stripped
        return v

    @field_validator("shift")
    @classmethod
    def validate_shift(cls, v: str | None) -> str | None:
        if v is not None:
            stripped = v.strip()
            if len(stripped) < 1:
                raise ValueError("shift cannot be empty or only spaces")
            return stripped
        return v


class NurseResponse(BaseSchema):
    id: int
    nurse_code: str
    user_id: int
    license_number: str
    department_id: int | None
    shift: str | None
    created_at: datetime
    updated_at: datetime


NurseListResponse = PaginatedResponse[NurseResponse]


class NurseShiftCreate(BaseSchema):
    shift_name: str = Field(..., description="Name of the shift (e.g. Morning, Afternoon, Night)", min_length=1, max_length=50)
    shift_date: date = Field(..., description="Date of the shift")
    start_time: time = Field(..., description="Start time of the shift")
    end_time: time = Field(..., description="End time of the shift")
    status: str = Field("Scheduled", description="Status of the shift", min_length=1, max_length=50)
    notes: str | None = Field(None, description="Optional notes for the shift")

    @field_validator("shift_name", "status")
    @classmethod
    def validate_required_strings(cls, v: str) -> str:
        stripped = v.strip()
        if len(stripped) < 1:
            raise ValueError("cannot be empty or only spaces")
        return stripped

    @field_validator("notes")
    @classmethod
    def validate_optional_strings(cls, v: str | None) -> str | None:
        if v is not None:
            return v.strip()
        return v


class NurseShiftUpdate(BaseSchema):
    shift_name: str | None = Field(None, min_length=1, max_length=50)
    shift_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    status: str | None = Field(None, min_length=1, max_length=50)
    notes: str | None = None

    @field_validator("shift_name", "status")
    @classmethod
    def validate_required_strings(cls, v: str | None) -> str | None:
        if v is not None:
            stripped = v.strip()
            if len(stripped) < 1:
                raise ValueError("cannot be empty or only spaces")
            return stripped
        return v

    @field_validator("notes")
    @classmethod
    def validate_optional_strings(cls, v: str | None) -> str | None:
        if v is not None:
            return v.strip()
        return v


class NurseShiftResponse(BaseSchema):
    id: int
    nurse_id: int
    shift_name: str
    shift_date: date
    start_time: time
    end_time: time
    status: str
    notes: str | None
    created_at: datetime
    updated_at: datetime


NurseShiftListResponse = PaginatedResponse[NurseShiftResponse]


class NurseShiftDetailsResponse(BaseSchema):
    shift_name: str
    shift_date: date
    start_time: time
    end_time: time
    status: str
    notes: str | None


class NurseAttendanceCreate(BaseSchema):
    attendance_date: date = Field(..., description="Date of attendance")
    check_in_time: time | None = Field(None, description="Check-in time")
    check_out_time: time | None = Field(None, description="Check-out time")
    status: str = Field("Present", description="Attendance status", min_length=1, max_length=50)
    notes: str | None = Field(None, description="Optional notes")

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        stripped = v.strip()
        if len(stripped) < 1:
            raise ValueError("status cannot be empty or only spaces")
        return stripped

    @field_validator("notes")
    @classmethod
    def validate_notes(cls, v: str | None) -> str | None:
        if v is not None:
            return v.strip()
        return v


class NurseAttendanceResponse(BaseSchema):
    id: int
    nurse_id: int
    attendance_date: date
    check_in_time: time | None
    check_out_time: time | None
    status: str
    notes: str | None
    created_at: datetime
    updated_at: datetime


NurseAttendanceListResponse = PaginatedResponse[NurseAttendanceResponse]


class NurseHandoverNoteCreate(BaseSchema):
    shift_id: int | None = Field(None, description="Optional linked shift ID", gt=0)
    handover_date: date = Field(..., description="Date of the handover")
    summary: str = Field(..., description="Summary of the shift handover", min_length=1)
    pending_tasks: str | None = Field(None, description="Tasks pending for the incoming nurse")
    patient_updates: str | None = Field(None, description="Patient status updates")
    status: str = Field("Active", description="Status of the handover note", min_length=1, max_length=50)
    notes: str | None = Field(None, description="Additional notes")

    @field_validator("summary", "status")
    @classmethod
    def validate_required_strings(cls, v: str) -> str:
        stripped = v.strip()
        if len(stripped) < 1:
            raise ValueError("cannot be empty or only spaces")
        return stripped

    @field_validator("pending_tasks", "patient_updates", "notes")
    @classmethod
    def validate_optional_strings(cls, v: str | None) -> str | None:
        if v is not None:
            return v.strip()
        return v


class NurseHandoverNoteUpdate(BaseSchema):
    shift_id: int | None = Field(None, gt=0)
    handover_date: date | None = None
    summary: str | None = Field(None, min_length=1)
    pending_tasks: str | None = None
    patient_updates: str | None = None
    status: str | None = Field(None, min_length=1, max_length=50)
    notes: str | None = None

    @field_validator("summary", "status")
    @classmethod
    def validate_required_strings(cls, v: str | None) -> str | None:
        if v is not None:
            stripped = v.strip()
            if len(stripped) < 1:
                raise ValueError("cannot be empty or only spaces")
            return stripped
        return v

    @field_validator("pending_tasks", "patient_updates", "notes")
    @classmethod
    def validate_optional_strings(cls, v: str | None) -> str | None:
        if v is not None:
            return v.strip()
        return v


class NurseHandoverNoteResponse(BaseSchema):
    id: int
    nurse_id: int
    shift_id: int | None
    handover_date: date
    summary: str
    pending_tasks: str | None
    patient_updates: str | None
    status: str
    notes: str | None
    created_at: datetime
    updated_at: datetime


NurseHandoverNoteListResponse = PaginatedResponse[NurseHandoverNoteResponse]


class NurseAssignedPatientStatusResponse(BaseSchema):
    patient_id: int
    patient_code: str
    first_name: str
    last_name: str
    patient_status: str = Field(
        ..., description="Clinical status of the assigned patient (Critical, Stable, Discharged)"
    )
    assignment_status: str = Field(..., description="Assignment status")
    notes: str | None
    updated_at: datetime


NurseAssignedPatientStatusListResponse = PaginatedResponse[NurseAssignedPatientStatusResponse]


class NurseAssignedPatientProfileResponse(BaseSchema):
    id: int
    patient_code: str
    first_name: str
    last_name: str
    gender: str | None
    dob: date | None
    blood_group: str | None
    marital_status: str | None
    phone: str | None
    email: str | None
    address: str | None
    city: str | None
    state: str | None
    pincode: str | None
    emergency_contact_name: str | None
    emergency_contact_number: str | None
    medical_history: str | None
    allergies: str | None
    diagnosis: str | None = Field(None, description="Diagnosis from chronic disease record if available")
    patient_status: str = Field(..., description="Current clinical status from nurse assignment")
    assignment_status: str
    status: str = Field(..., description="General patient account status")
    assignment_notes: str | None
    insurance_provider: str | None
    insurance_number: str | None
    created_at: datetime
    updated_at: datetime


class NurseNotificationResponse(BaseSchema):
    id: int
    nurse_id: int
    title: str
    message: str
    notification_type: str = Field(
        ..., description="Type of item: Alert or Notification"
    )
    priority: str
    status: str
    patient_id: int | None
    shift_id: int | None
    created_at: datetime
    updated_at: datetime


NurseNotificationListResponse = PaginatedResponse[NurseNotificationResponse]


class PatientVitalCreate(BaseSchema):
    temperature: float = Field(..., ge=0.0, description="Body temperature in Celsius")
    blood_pressure: str = Field(..., min_length=1, max_length=20, description="Blood pressure reading (e.g. 120/80)")
    pulse_rate: int = Field(..., ge=1, description="Pulse rate in beats per minute")
    oxygen_saturation: float = Field(..., ge=0.0, le=100.0, description="Oxygen saturation percentage")
    recorded_at: datetime = Field(..., description="When the vitals were recorded")

    @field_validator("blood_pressure")
    @classmethod
    def validate_bp(cls, v: str) -> str:
        stripped = v.strip()
        if len(stripped) < 1:
            raise ValueError("blood_pressure cannot be empty or only spaces")
        return stripped


class PatientVitalResponse(BaseSchema):
    id: int
    nurse_id: int
    patient_id: int
    temperature: float
    blood_pressure: str
    pulse_rate: int
    oxygen_saturation: float
    recorded_at: datetime
    created_at: datetime
    updated_at: datetime


class NurseTaskResponse(BaseSchema):
    id: int
    title: str
    description: str | None
    patient_id: int
    due_date: date
    priority: str
    status: str
    created_at: datetime
    updated_at: datetime


NurseTaskListResponse = PaginatedResponse[NurseTaskResponse]


class NurseTaskStatusUpdate(BaseSchema):
    status: Literal["Pending", "Completed", "Delayed"] = Field(
        ..., description="Task status (Pending, Completed, or Delayed)"
    )


class NursePatientLabTestResponse(BaseSchema):
    id: int
    order_number: str
    test_name: str
    test_code: str | None = None
    category: str | None = None
    sample_type: str | None = None
    request_date: datetime = Field(..., description="Date the lab test was requested")
    status: str = Field(..., description="Pending or Completed")
    priority: str
    notes: str | None = None
    completed_at: datetime | None = None
    result_summary: str | None = None
    created_at: datetime


NursePatientLabTestListResponse = PaginatedResponse[NursePatientLabTestResponse]
