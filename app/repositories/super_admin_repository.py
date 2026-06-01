from datetime import datetime, timedelta
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hospital_model import Hospital
from app.models.branch_model import Branch
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

        # 2. Total Branches
        total_branches = await self.db.scalar(
            select(func.count(Branch.id)).where(Branch.is_deleted == False)
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
            "total_branches": total_branches,
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
