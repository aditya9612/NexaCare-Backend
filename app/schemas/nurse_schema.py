from datetime import date, datetime, time
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from app.schemas.common_schema import BaseSchema, PaginatedResponse
from app.schemas.department_schema import DepartmentResponse
from app.schemas.rbac_schema import RoleResponse


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


class NurseDetailResponse(NurseResponse):
    full_name: str
    email: str
    phone: str | None = None
    role_name: str | None = None
    status: int
    is_active: bool
    gender: str | None = None
    date_of_birth: date | None = None
    address: str | None = None
    profile_image: str | None = None

    department: DepartmentResponse | None = None
    role: RoleResponse | None = None


NurseListResponse = PaginatedResponse[NurseResponse]


class NurseShiftCreate(BaseSchema):
    shift_name: str = Field(..., description="Name of the shift (e.g. Morning, Afternoon, Night)", min_length=1, max_length=50)
    shift_date: date | None = Field(None, description="Date of the shift (for single day)")
    start_date: date | None = Field(None, description="Start date of the shift range")
    end_date: date | None = Field(None, description="End date of the shift range")
    start_time: time = Field(..., description="Start time of the shift")
    end_time: time = Field(..., description="End time of the shift")
    notes: str | None = Field(None, description="Optional notes for the shift")

    @field_validator("shift_name")
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
    notes: str | None = None

    @field_validator("shift_name")
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
    action: Literal["check_in", "check_out"] = Field(..., description="Action to perform: check_in or check_out")
    notes: str | None = Field(None, description="Optional notes")

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


class PatientHandoverItemCreate(BaseSchema):
    patient_id: int = Field(..., description="Patient ID", gt=0)
    incoming_nurse_id: int = Field(..., description="Incoming Nurse ID to assign the patient to", gt=0)
    patient_update: str = Field(..., description="Clinical update for the patient", min_length=1)
    pending_tasks: list[str] = Field(default_factory=list, description="Pending tasks for incoming nurse")

    @field_validator("patient_update")
    @classmethod
    def validate_patient_update(cls, v: str) -> str:
        stripped = v.strip()
        if len(stripped) < 1:
            raise ValueError("cannot be empty or only spaces")
        return stripped


class PatientHandoverItemResponse(BaseSchema):
    patient_id: int = Field(..., description="Patient ID")
    incoming_nurse_id: int = Field(..., description="Incoming Nurse ID")
    patient_update: str = Field(..., description="Clinical update for the patient")
    pending_tasks: list[str] = Field(default_factory=list, description="Pending tasks for incoming nurse")


class NurseHandoverNoteCreate(BaseSchema):
    shift_id: int = Field(..., description="Linked shift ID", gt=0)
    handover_date: date = Field(..., description="Date of the handover")
    summary: str = Field(..., description="Summary of the shift handover", min_length=1)
    notes: str | None = Field(None, description="Additional notes")
    patient_handovers: list[PatientHandoverItemCreate] = Field(
        default_factory=list, description="List of patient-specific handovers"
    )

    @field_validator("summary")
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


class NurseHandoverNoteUpdate(BaseSchema):
    shift_id: int | None = Field(None, gt=0)
    handover_date: date | None = None
    summary: str | None = Field(None, min_length=1)
    status: str | None = Field(None, min_length=1, max_length=50)
    notes: str | None = None
    patient_handovers: list[PatientHandoverItemCreate] | None = None

    @field_validator("summary", "status")
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


class NurseHandoverNoteResponse(BaseSchema):
    handover_id: int
    outgoing_nurse_id: int
    shift_id: int | None = None
    handover_date: date
    summary: str
    notes: str | None = None
    acceptance_status: str = "Pending"
    patient_handovers: list[PatientHandoverItemResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def populate_handover_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "handover_id" not in data and "id" in data:
                data["handover_id"] = data["id"]
            if "outgoing_nurse_id" not in data:
                if "nurse_id" in data:
                    data["outgoing_nurse_id"] = data["nurse_id"]
            if "acceptance_status" not in data:
                if "status" in data:
                    data["acceptance_status"] = data["status"]
            if not data.get("patient_handovers") and data.get("patient_updates"):
                try:
                    import json
                    parsed = json.loads(data["patient_updates"])
                    if isinstance(parsed, list):
                        data["patient_handovers"] = parsed
                except Exception:
                    pass
        return data


NurseHandoverNoteListResponse = PaginatedResponse[NurseHandoverNoteResponse]


class NurseMiniProfile(BaseSchema):
    id: int
    nurse_code: str | None = None
    full_name: str | None = None
    license_number: str | None = None
    shift: str | None = None


class NurseHandoverActionRequest(BaseSchema):
    action: str = Field(
        ..., description="Action to perform on the handover note: ACCEPT or REJECT"
    )
    remarks: str | None = Field(None, description="Optional remarks for the action")
    rejection_reason: str | None = Field(
        None, description="Mandatory reason if action is REJECT"
    )

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        stripped = v.strip().upper() if isinstance(v, str) else ""
        if stripped not in ("ACCEPT", "REJECT"):
            raise ValueError("action must be either 'ACCEPT' or 'REJECT'")
        return stripped

    @field_validator("rejection_reason")
    @classmethod
    def validate_rejection(cls, v: str | None, info) -> str | None:
        action = info.data.get("action")
        if action == "REJECT" and (not v or not v.strip()):
            raise ValueError("rejection_reason is required when action is REJECT")
        return v.strip() if v else None

    @field_validator("remarks")
    @classmethod
    def validate_remarks(cls, v: str | None) -> str | None:
        return v.strip() if v else None


class HandoverHistoryActionItem(BaseSchema):
    action: str
    performed_by: NurseMiniProfile | None = None
    action_timestamp: datetime
    status_before: str | None = None
    status_after: str | None = None
    remarks: str | None = None
    rejection_reason: str | None = None


class NurseHandoverHistoryResponse(BaseSchema):
    handover_id: int
    handover_date: date
    current_status: str
    creator: NurseMiniProfile
    incoming_nurse: NurseMiniProfile | None = None
    summary: str
    pending_tasks: str | None = None
    patient_updates: str | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime
    acceptance_or_rejection_action: str | None = None
    action_performed_by: NurseMiniProfile | None = None
    action_timestamp: datetime | None = None
    rejection_reason: str | None = None
    history: list[HandoverHistoryActionItem] = []


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
    temperature: float = Field(..., ge=0.0, description="Body temperature")
    temperature_unit: str = Field(
        default="C",
        description="Temperature unit: Celsius ('C', '°C', 'Celsius') or Fahrenheit ('F', '°F', 'Fahrenheit'). Defaults to 'C'."
    )
    blood_pressure: str = Field(..., min_length=1, max_length=20, description="Blood pressure reading (e.g. 120/80)")
    pulse_rate: int = Field(..., ge=1, description="Pulse rate in beats per minute")
    oxygen_saturation: float = Field(..., ge=0.0, le=100.0, description="Oxygen saturation percentage")
    recorded_at: datetime = Field(..., description="When the vitals were recorded")
    notes: str | None = Field(None, description="Optional supplementary instructions or clinical notes")

    @field_validator("temperature_unit")
    @classmethod
    def validate_temperature_unit(cls, v: str | None) -> str:
        if not v:
            return "C"
        cleaned = v.strip().lower()
        if cleaned in ("c", "°c", "celsius"):
            return "C"
        if cleaned in ("f", "°f", "fahrenheit"):
            return "F"
        raise ValueError("temperature_unit must be Celsius ('C', '°C', 'Celsius') or Fahrenheit ('F', '°F', 'Fahrenheit')")

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
    temperature_unit: str = "°C"
    blood_pressure: str
    pulse_rate: int
    oxygen_saturation: float
    recorded_at: datetime
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class PatientVitalUpdate(BaseSchema):
    temperature: float | None = Field(None, ge=0.0, description="Body temperature in Celsius")
    systolic_bp: int | None = Field(None, ge=1, description="Systolic blood pressure")
    diastolic_bp: int | None = Field(None, ge=1, description="Diastolic blood pressure")
    pulse_rate: int | None = Field(None, ge=1, description="Pulse rate in beats per minute")
    oxygen_level: float | None = Field(None, ge=0.0, le=100.0, description="Oxygen saturation level (SPO2)")
    notes: str | None = Field(None, description="Optional notes")


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


class NurseTaskListWithCountsResponse(PaginatedResponse[NurseTaskResponse]):
    total_tasks: int
    pending_tasks: int
    completed_tasks: int
    delayed_tasks: int



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


class NursePatientLabTestListResponse(BaseSchema):
    pass


class NursePrescriptionCreate(BaseSchema):
    patient_id: int
    doctor_id: int | None = None
    doctor_name: str | None = None
    medicine_name: str
    dosage: str
    frequency: str
    start_date: date | None = None
    end_date: date | None = None
    meal_timing: str | None = "after meal"
    time_of_day: list[str] | None = None
    times: dict[str, str] | None = None
    duration_value: str | int | None = None
    duration_unit: str | None = "days"
    special_instructions: str | None = None


class NursePrescriptionResponse(BaseSchema):
    id: int
    patient_id: int
    patient_name: str
    doctor_id: int
    doctor_name: str
    medicine_name: str
    dosage: str
    frequency: str
    start_date: date
    end_date: date
    meal_timing: str
    time_of_day: list[str] | None = None
    times: dict[str, str] | None = None
    duration_value: str | None = None
    duration_unit: str | None = None
    special_instructions: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime


class NurseMedicationLogCreate(BaseSchema):
    status: str
    time_of_day_slot: str | None = None
    notes: str | None = None
    timestamp: datetime | None = None


class NurseMedicationLogResponse(BaseSchema):
    id: int
    prescription_id: int
    nurse_id: int | None = None
    nurse_name: str | None = None
    status: str
    time_of_day_slot: str | None = None
    notes: str | None = None
    timestamp: datetime
    created_at: datetime


class UpcomingMedicationResponse(BaseSchema):
    patient_id: int
    patient_name: str
    medicine_name: str
    scheduled_time: str


class CriticalAlertResponse(BaseSchema):
    patient_id: int
    patient_name: str
    alert_type: str
    priority: str
    created_at: datetime


class RecentActivityResponse(BaseSchema):
    id: int
    action: str
    resource: str
    details: str | None = None
    created_at: datetime


class NurseDashboardResponse(BaseSchema):
    nurse_id: int | None = None
    nurse_code: str | None = None
    nurse_name: str | None = None
    assigned_patients: int
    today_patients: int
    pending_medications: int
    critical_patients: int
    doctor_instructions: int
    occupied_beds: int
    available_beds: int
    upcoming_medications: list[UpcomingMedicationResponse] = []
    critical_alerts: list[CriticalAlertResponse] = []
    recent_activities: list[RecentActivityResponse] = []
    assigned_patients_list: list[NurseAssignedPatientStatusResponse] = []
    shift_details: list[NurseShiftResponse] = []
    alerts: list[CriticalAlertResponse] = []


class NurseTaskCreate(BaseSchema):
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    patient_id: int
    due_date: date
    priority: Literal["Low", "Medium", "High"] = "Medium"


class NursePatientAssignmentCreate(BaseSchema):
    patient_id: int
    patient_status: str = "Stable"
    notes: str | None = None


class NursePatientAssignmentResponse(BaseSchema):
    id: int
    nurse_id: int
    patient_id: int
    status: str
    patient_status: str
    notes: str | None = None
    created_at: datetime
    updated_at: datetime
