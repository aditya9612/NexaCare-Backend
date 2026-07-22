from datetime import datetime

from pydantic import BaseModel

from app.schemas.appointment_schema import AppointmentResponse
from app.schemas.lab_schema import LabReportResponse
from app.schemas.pharmacy_schema import PrescriptionResponse


class DepartmentStat(BaseModel):
    department: str
    count: int


class AdminDashboardResponse(BaseModel):
    total_patients: int
    total_doctors: int
    total_appointments: int
    today_appointments: int
    revenue_summary: float
    department_statistics: list[DepartmentStat]


class PendingLabReportItem(BaseModel):
    id: int
    patient_id: int
    lab_test_id: int
    appointment_id: int | None = None
    status: str
    priority: str | None = None
    created_at: datetime | None = None


class PendingLabReportsSummary(BaseModel):
    count: int
    recent: list[PendingLabReportItem]


class PrescriptionSummary(BaseModel):
    total_prescriptions: int = 0
    pending_prescriptions: int = 0
    dispensed_prescriptions: int = 0
    recent_prescriptions: list[PrescriptionResponse] = []


class DoctorDashboardResponse(BaseModel):
    today_patients: int
    upcoming_appointments: list[AppointmentResponse]
    completed_consultations: int
    pending_lab_reports: PendingLabReportsSummary
    prescription_summary: PrescriptionSummary
    upcoming_lab_reports: list[LabReportResponse] = []
    pending_lab_reports_count: int = 0



class PatientDashboardResponse(BaseModel):
    appointment_history: list[AppointmentResponse]
    upcoming_appointments: list[AppointmentResponse]


class ReceptionDashboardResponse(BaseModel):
    total_registered_patients: int
    today_scheduled_appointments: int
    checked_in_patients: int
    waiting_patients: int
    completed_visits: int
    cancelled_appointments: int
    available_doctors: int
    walk_in_patients: int
    pending_billing: int
    rescheduled_appointments: int
    total_patient_footfall: int

