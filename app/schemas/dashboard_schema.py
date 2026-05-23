from datetime import datetime

from pydantic import BaseModel

from app.schemas.appointment_schema import AppointmentResponse


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


class DoctorDashboardResponse(BaseModel):
    today_patients: int
    upcoming_appointments: list[AppointmentResponse]
    completed_consultations: int


class PatientDashboardResponse(BaseModel):
    appointment_history: list[AppointmentResponse]
    upcoming_appointments: list[AppointmentResponse]
