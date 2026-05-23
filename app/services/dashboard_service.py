from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import AppointmentStatus
from app.models.appointment_model import Appointment
from app.models.billing_model import Billing
from app.models.doctor_model import Doctor
from app.models.patient_model import Patient
from app.models.user_model import User
from app.repositories.appointment_repository import AppointmentRepository
from app.schemas.appointment_schema import AppointmentResponse
from app.schemas.dashboard_schema import (
    AdminDashboardResponse,
    DepartmentStat,
    DoctorDashboardResponse,
    PatientDashboardResponse,
)


class DashboardService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.appointment_repo = AppointmentRepository(db)

    async def admin_dashboard(self) -> AdminDashboardResponse:
        total_patients = await self.db.scalar(
            select(func.count()).select_from(Patient).where(Patient.is_deleted.is_(False))
        ) or 0
        total_doctors = await self.db.scalar(
            select(func.count()).select_from(Doctor).where(Doctor.is_deleted.is_(False))
        ) or 0
        total_appointments = await self.db.scalar(select(func.count()).select_from(Appointment)) or 0
        today = date.today()
        today_appointments = await self.db.scalar(
            select(func.count()).select_from(Appointment).where(Appointment.appointment_date == today)
        ) or 0

        revenue = await self.db.scalar(
            select(func.coalesce(func.sum(Billing.paid_amount), 0.0)).where(Billing.is_deleted.is_(False))
        ) or 0.0

        dept_result = await self.db.execute(
            select(Doctor.department, func.count(Appointment.id))
            .join(Appointment, Appointment.doctor_id == Doctor.id)
            .where(Doctor.department.isnot(None))
            .group_by(Doctor.department)
        )
        department_statistics = [
            DepartmentStat(department=row[0] or "Unknown", count=row[1])
            for row in dept_result.all()
        ]

        return AdminDashboardResponse(
            total_patients=total_patients,
            total_doctors=total_doctors,
            total_appointments=total_appointments,
            today_appointments=today_appointments,
            revenue_summary=float(revenue),
            department_statistics=department_statistics,
        )

    async def doctor_dashboard(self, user: User) -> DoctorDashboardResponse:
        doctor_result = await self.db.execute(
            select(Doctor).where(Doctor.user_id == user.id, Doctor.is_deleted.is_(False))
        )
        doctor = doctor_result.scalar_one_or_none()
        if not doctor:
            return DoctorDashboardResponse(
                today_patients=0, upcoming_appointments=[], completed_consultations=0
            )

        today = date.today()
        today_appts = await self.appointment_repo.list_all(
            doctor_id=doctor.id, appointment_date=today, limit=100
        )
        patient_ids = {a.patient_id for a in today_appts}

        upcoming = await self.appointment_repo.list_all(
            doctor_id=doctor.id, status=AppointmentStatus.CONFIRMED, limit=10
        )
        completed = await self.appointment_repo.count_all(
            doctor_id=doctor.id, status=AppointmentStatus.COMPLETED
        )

        return DoctorDashboardResponse(
            today_patients=len(patient_ids),
            upcoming_appointments=[AppointmentResponse.model_validate(a) for a in upcoming],
            completed_consultations=completed,
        )

    async def patient_dashboard(self, user: User) -> PatientDashboardResponse:
        patient_result = await self.db.execute(
            select(Patient).where(Patient.user_id == user.id, Patient.is_deleted.is_(False))
        )
        patient = patient_result.scalar_one_or_none()
        if not patient:
            return PatientDashboardResponse(appointment_history=[], upcoming_appointments=[])

        all_appts = await self.appointment_repo.list_all(patient_id=patient.id, limit=100)
        history = [a for a in all_appts if a.appointment_status == AppointmentStatus.COMPLETED]
        upcoming = [
            a for a in all_appts
            if a.appointment_status in AppointmentStatus.ACTIVE and a.appointment_date >= date.today()
        ]

        return PatientDashboardResponse(
            appointment_history=[AppointmentResponse.model_validate(a) for a in history],
            upcoming_appointments=[AppointmentResponse.model_validate(a) for a in upcoming],
        )
