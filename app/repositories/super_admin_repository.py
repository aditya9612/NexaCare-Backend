from datetime import datetime, timedelta
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.hospital_model import Hospital
from app.models.user_model import User
from app.models.role_model import Role
from app.models.doctor_model import Doctor
from app.models.patient_model import Patient
from app.models.appointment_model import Appointment
from app.models.refresh_token_model import RefreshToken
from app.core.constants import UserRole
from app.models.billing_model import Payment

class SuperAdminRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_dashboard_stats(self) -> dict:
        now = datetime.utcnow()
        online_threshold = now - timedelta(minutes=15)

        # 1. Total Hospitals
        total_hospitals = await self.db.scalar(
            select(func.count(Hospital.id)).where(Hospital.is_deleted == False)
        ) or 0

        # 3. Admins Query (Hospital Admin)
        admin_query = select(
            func.count(User.id).label("total"),
            func.sum(case((User.is_active == True, 1), else_=0)).label("active"),
            func.sum(case((User.is_active == False, 1), else_=0)).label("inactive"),
            func.sum(case((User.last_login >= online_threshold, 1), else_=0)).label("online")
        ).join(Role, User.role_id == Role.id).where(Role.name == UserRole.HOSPITAL_ADMIN)
        
        admin_res = await self.db.execute(admin_query)
        admin_row = admin_res.fetchone()
        
        total_admins = admin_row[0] if admin_row and admin_row[0] is not None else 0
        active_admins = admin_row[1] if admin_row and admin_row[1] is not None else 0
        inactive_admins = admin_row[2] if admin_row and admin_row[2] is not None else 0
        online_admins = admin_row[3] if admin_row and admin_row[3] is not None else 0

        # 4. Total Doctors
        total_doctors = await self.db.scalar(
            select(func.count(Doctor.id)).where(Doctor.is_deleted == False)
        ) or 0

        # 5. Total Staff
        staff_roles = [
            UserRole.NURSE,
            UserRole.RECEPTIONIST,
            UserRole.ACCOUNTANT,
            UserRole.PHARMACIST,
            UserRole.LAB_TECHNICIAN
        ]
        total_staff = await self.db.scalar(
            select(func.count(User.id)).join(Role, User.role_id == Role.id).where(Role.name.in_(staff_roles))
        ) or 0

        # 6. Total Patients
        total_patients = await self.db.scalar(
            select(func.count(Patient.id)).where(Patient.is_deleted == False)
        ) or 0

        # 7. Total Appointments
        total_appointments = await self.db.scalar(
            select(func.count(Appointment.id))
        ) or 0

        # 8. Active Sessions
        active_sessions = await self.db.scalar(
            select(func.count(RefreshToken.id)).where(
                RefreshToken.is_revoked == False,
                RefreshToken.expires_at > now
            )
        ) or 0

        return {
            "total_hospitals": total_hospitals,
            "total_admins": total_admins,
            "active_admins": active_admins,
            "inactive_admins": inactive_admins,
            "online_admins": online_admins,
            "total_doctors": total_doctors,
            "total_staff": total_staff,
            "total_patients": total_patients,
            "total_appointments": total_appointments,
            "active_sessions": active_sessions,
            "system_health": "ok"
        }

    async def get_hospital_growth(self) -> list[dict]:
        query = select(
            func.year(Hospital.created_at).label("year"),
            func.month(Hospital.created_at).label("month"),
            func.count(Hospital.id).label("count")
        ).where(Hospital.is_deleted == False).group_by(
            func.year(Hospital.created_at),
            func.month(Hospital.created_at)
        ).order_by(
            func.year(Hospital.created_at),
            func.month(Hospital.created_at)
        )
        res = await self.db.execute(query)
        rows = res.all()
        return [
            {"year": r.year, "month": r.month, "count": r.count}
            for r in rows
        ]

    async def get_revenue_trends(self) -> list[dict]:
        query = select(
            func.year(Payment.payment_date).label("year"),
            func.month(Payment.payment_date).label("month"),
            func.sum(Payment.amount).label("amount")
        ).where(
            Payment.status == "completed",
            Payment.is_refund == False
        ).group_by(
            func.year(Payment.payment_date),
            func.month(Payment.payment_date)
        ).order_by(
            func.year(Payment.payment_date),
            func.month(Payment.payment_date)
        )
        res = await self.db.execute(query)
        rows = res.all()
        return [
            {"year": r.year, "month": r.month, "amount": float(r.amount) if r.amount is not None else 0.0}
            for r in rows
        ]

    # Extended Dashboard Repository Methods

    async def get_dashboard_overview_data(self, current_month_start: datetime, prev_month_start: datetime, prev_month_end: datetime) -> dict:
        now = datetime.utcnow()
        
        # 1. Patients total and MoM counts
        total_patients = await self.db.scalar(
            select(func.count(Patient.id)).where(Patient.is_deleted == False)
        ) or 0
        current_patients = await self.db.scalar(
            select(func.count(Patient.id)).where(
                Patient.is_deleted == False, 
                Patient.created_at >= current_month_start
            )
        ) or 0
        prev_patients = await self.db.scalar(
            select(func.count(Patient.id)).where(
                Patient.is_deleted == False, 
                Patient.created_at >= prev_month_start, 
                Patient.created_at <= prev_month_end
            )
        ) or 0

        # 2. Appointments total and MoM counts
        total_appointments = await self.db.scalar(
            select(func.count(Appointment.id))
        ) or 0
        current_appointments = await self.db.scalar(
            select(func.count(Appointment.id)).where(Appointment.created_at >= current_month_start)
        ) or 0
        prev_appointments = await self.db.scalar(
            select(func.count(Appointment.id)).where(
                Appointment.created_at >= prev_month_start, 
                Appointment.created_at <= prev_month_end
            )
        ) or 0

        # 3. Sessions total and MoM counts (unrevoked, unexpired tokens)
        active_sessions = await self.db.scalar(
            select(func.count(RefreshToken.id)).where(
                RefreshToken.is_revoked == False, 
                RefreshToken.expires_at > now
            )
        ) or 0
        current_sessions = await self.db.scalar(
            select(func.count(RefreshToken.id)).where(RefreshToken.created_at >= current_month_start)
        ) or 0
        prev_sessions = await self.db.scalar(
            select(func.count(RefreshToken.id)).where(
                RefreshToken.created_at >= prev_month_start, 
                RefreshToken.created_at <= prev_month_end
            )
        ) or 0

        return {
            "total_patients": total_patients,
            "current_patients": current_patients,
            "prev_patients": prev_patients,
            "total_appointments": total_appointments,
            "current_appointments": current_appointments,
            "prev_appointments": prev_appointments,
            "active_sessions": active_sessions,
            "current_sessions": current_sessions,
            "prev_sessions": prev_sessions
        }

    async def get_patients_last_6_months(self, start_date: datetime) -> list[dict]:
        query = select(
            func.year(Patient.created_at).label("year"),
            func.month(Patient.created_at).label("month"),
            func.count(Patient.id).label("count")
        ).where(
            Patient.is_deleted == False,
            Patient.created_at >= start_date
        ).group_by(
            func.year(Patient.created_at),
            func.month(Patient.created_at)
        ).order_by(
            func.year(Patient.created_at),
            func.month(Patient.created_at)
        )
        res = await self.db.execute(query)
        rows = res.all()
        return [
            {"year": r.year, "month": r.month, "count": r.count}
            for r in rows
        ]

    async def get_users_distribution_data(self) -> list[dict]:
        query = select(
            Role.name.label("role_name"),
            func.count(User.id).label("count")
        ).join(Role, User.role_id == Role.id).group_by(Role.name)
        res = await self.db.execute(query)
        rows = res.all()
        return [
            {"role_name": r.role_name, "count": r.count}
            for r in rows
        ]

    async def get_recent_admins(self, limit: int = 10) -> list[User]:
        query = select(User).join(Role, User.role_id == Role.id).where(
            Role.name == UserRole.HOSPITAL_ADMIN
        ).options(
            joinedload(User.hospital)
        ).order_by(
            User.created_at.desc()
        ).limit(limit)
        res = await self.db.execute(query)
        return list(res.scalars().all())
