from datetime import datetime

from pydantic import BaseModel

from app.schemas.appointment_schema import AppointmentResponse


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


class PrescriptionSummary(BaseModel):
    total_prescriptions: int
    pending_prescriptions: int
    dispensed_prescriptions: int
    recent_prescriptions: list[PrescriptionResponse]


from app.schemas.lab_schema import LabReportResponse

class DoctorDashboardResponse(BaseModel):
    today_patients: int
    upcoming_appointments: list[AppointmentResponse]
    completed_consultations: int
    prescription_summary: PrescriptionSummary
    upcoming_lab_reports: list[LabReportResponse]
    pending_lab_reports_count: int = 0
    pending_lab_reports: list[LabReportResponse] = []



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

