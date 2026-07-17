from datetime import date, timedelta
from sqlalchemy import func, select, and_, or_
from app.utils.helpers import utc_now
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import AppointmentStatus
from app.models.appointment_model import Appointment
from app.models.billing_model import Billing
from app.models.doctor_model import Doctor
from app.models.patient_model import Patient
from app.models.user_model import User
from app.models.department_model import Department
from app.repositories.appointment_repository import AppointmentRepository
from app.schemas.appointment_schema import AppointmentResponse
from app.schemas.dashboard_schema import (
    AdminDashboardResponse,
    DepartmentStat,
    DoctorDashboardResponse,
    PatientDashboardResponse,
    ReceptionDashboardResponse,
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

        dept_query = (
            select(Department.department_name, func.count(Appointment.id))
            .select_from(Department)
            .join(Doctor, Doctor.department_id == Department.department_id)
            .join(Appointment, Appointment.doctor_id == Doctor.id)
            .group_by(Department.department_name)
        )
        dept_result = await self.db.execute(dept_query)
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
        from app.models.lab_model import TestOrder
        from app.core.constants import LabOrderStatus
        from app.schemas.dashboard_schema import PendingLabReportsSummary, PendingLabReportItem

        doctor_result = await self.db.execute(
            select(Doctor).where(Doctor.user_id == user.id, Doctor.is_deleted.is_(False))
        )
        doctor = doctor_result.scalar_one_or_none()
        if not doctor:
            return DoctorDashboardResponse(
                today_patients=0,
                upcoming_appointments=[],
                completed_consultations=0,
                pending_lab_reports=PendingLabReportsSummary(
                    count=0,
                    recent=[]
                )
            )

        now = utc_now()
        today = now.date()
        tomorrow = today + timedelta(days=1)
        current_time = now.time()

        today_appts = await self.appointment_repo.list_all(
            doctor_id=doctor.id, appointment_date=today, limit=100
        )
        patient_ids = {a.patient_id for a in today_appts}

        upcoming_query = (
            select(Appointment)
            .where(
                Appointment.doctor_id == doctor.id,
                ~Appointment.appointment_status.in_(list(AppointmentStatus.TERMINAL)),
                or_(
                    and_(Appointment.appointment_date == today, Appointment.appointment_time >= current_time),
                    Appointment.appointment_date == tomorrow
                )
            )
            .order_by(Appointment.appointment_date.asc(), Appointment.appointment_time.asc())
            .limit(10)
        )
        upcoming_result = await self.db.execute(upcoming_query)
        upcoming = list(upcoming_result.scalars().all())

        completed = await self.appointment_repo.count_all(
            doctor_id=doctor.id, status=AppointmentStatus.COMPLETED
        )

        pending_statuses = [LabOrderStatus.ORDERED, LabOrderStatus.SAMPLE_COLLECTED, LabOrderStatus.IN_PROGRESS]

        # Count total pending test orders
        total_pending_labs = await self.db.scalar(
            select(func.count()).select_from(TestOrder).where(
                TestOrder.doctor_id == doctor.id,
                TestOrder.is_deleted.is_(False),
                TestOrder.status.in_(pending_statuses)
            )
        ) or 0

        # Fetch 5 most recent pending test orders
        recent_labs_result = await self.db.execute(
            select(TestOrder)
            .where(
                TestOrder.doctor_id == doctor.id,
                TestOrder.is_deleted.is_(False),
                TestOrder.status.in_(pending_statuses)
            )
            .order_by(TestOrder.created_at.desc())
            .limit(5)
        )
        recent_labs = list(recent_labs_result.scalars().all())

        recent_lab_items = [
            PendingLabReportItem(
                id=o.id,
                patient_id=o.patient_id,
                lab_test_id=o.lab_test_id,
                appointment_id=o.appointment_id,
                status=o.status,
                priority=o.priority,
                created_at=o.created_at
            )
            for o in recent_labs
        ]

        return DoctorDashboardResponse(
            today_patients=len(patient_ids),
            upcoming_appointments=[AppointmentResponse.model_validate(a) for a in upcoming],
            completed_consultations=completed,
            pending_lab_reports=PendingLabReportsSummary(
                count=total_pending_labs,
                recent=recent_lab_items
            )
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

    async def reception_dashboard(self, target_date: date | None = None) -> ReceptionDashboardResponse:
        from datetime import datetime, time
        from app.models.audit_log_model import AuditLog
        from app.core.constants import DoctorAvailability

        t_date = target_date or date.today()
        start_of_day = datetime.combine(t_date, time.min)
        end_of_day = datetime.combine(t_date, time.max)

        # 1. total_registered_patients
        try:
            total_registered_patients = await self.db.scalar(
                select(func.count(Patient.id)).where(
                    Patient.is_deleted.is_(False)
                )
            ) or 0
        except Exception:
            total_registered_patients = 0

        # 2. today_scheduled_appointments
        try:
            today_scheduled_appointments = await self.db.scalar(
                select(func.count(Appointment.id)).where(
                    Appointment.appointment_date == t_date
                )
            ) or 0
        except Exception:
            today_scheduled_appointments = 0

        # 3. checked_in_patients
        try:
            checked_in_patients = await self.db.scalar(
                select(func.count(Appointment.id)).where(
                    Appointment.appointment_date == t_date,
                    Appointment.appointment_status.in_(["Checked In", "Checked-In", "checked_in", "checked-in"])
                )
            ) or 0
        except Exception:
            checked_in_patients = 0

        # 4. waiting_patients
        try:
            waiting_patients = await self.db.scalar(
                select(func.count(Appointment.id)).where(
                    Appointment.appointment_date == t_date,
                    Appointment.appointment_status.in_(["Waiting", "waiting", "Pending", "pending"])
                )
            ) or 0
        except Exception:
            waiting_patients = 0

        # 5. completed_visits
        try:
            completed_visits = await self.db.scalar(
                select(func.count(Appointment.id)).where(
                    Appointment.appointment_date == t_date,
                    Appointment.appointment_status == AppointmentStatus.COMPLETED
                )
            ) or 0
        except Exception:
            completed_visits = 0

        # 6. cancelled_appointments
        try:
            cancelled_appointments = await self.db.scalar(
                select(func.count(Appointment.id)).where(
                    Appointment.appointment_date == t_date,
                    Appointment.appointment_status == AppointmentStatus.CANCELLED
                )
            ) or 0
        except Exception:
            cancelled_appointments = 0

        # 7. available_doctors
        try:
            available_doctors = await self.db.scalar(
                select(func.count(Doctor.id)).where(
                    Doctor.availability_status == DoctorAvailability.AVAILABLE,
                    Doctor.is_deleted.is_(False)
                )
            ) or 0
        except Exception:
            available_doctors = 0

        # 8. walk_in_patients
        try:
            walk_in_patients = await self.db.scalar(
                select(func.count(Appointment.id)).where(
                    Appointment.appointment_date == t_date,
                    Appointment.appointment_type.in_(["walk-in", "walk_in", "walk in", "Walk-In", "Walk_In", "Walk In"])
                )
            ) or 0
        except Exception:
            walk_in_patients = 0

        # 9. pending_billing
        try:
            pending_billing = await self.db.scalar(
                select(func.count(Billing.id)).where(
                    Billing.is_deleted.is_(False),
                    Billing.status == "pending",
                    Billing.created_at >= start_of_day,
                    Billing.created_at <= end_of_day
                )
            ) or 0
        except Exception:
            pending_billing = 0

        # 10. rescheduled_appointments
        try:
            rescheduled_appointments = await self.db.scalar(
                select(func.count(AuditLog.id)).where(
                    AuditLog.action == "reschedule",
                    AuditLog.resource == "appointments",
                    AuditLog.created_at >= start_of_day,
                    AuditLog.created_at <= end_of_day
                )
            ) or 0
        except Exception:
            rescheduled_appointments = 0

        # 11. total_patient_footfall
        try:
            total_patient_footfall = await self.db.scalar(
                select(func.count(func.distinct(Appointment.patient_id))).where(
                    Appointment.appointment_date == t_date,
                    Appointment.appointment_status.in_(["Checked In", "Checked-In", "checked_in", "checked-in", "Waiting", "waiting", "Completed", "completed"])
                )
            ) or 0
        except Exception:
            total_patient_footfall = 0

        return ReceptionDashboardResponse(
            total_registered_patients=total_registered_patients,
            today_scheduled_appointments=today_scheduled_appointments,
            checked_in_patients=checked_in_patients,
            waiting_patients=waiting_patients,
            completed_visits=completed_visits,
            cancelled_appointments=cancelled_appointments,
            available_doctors=available_doctors,
            walk_in_patients=walk_in_patients,
            pending_billing=pending_billing,
            rescheduled_appointments=rescheduled_appointments,
            total_patient_footfall=total_patient_footfall,
        )

