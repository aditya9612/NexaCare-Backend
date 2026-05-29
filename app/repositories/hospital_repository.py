from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.hospital_model import Hospital
from app.models.user_model import User
from app.models.doctor_model import Doctor
from app.models.patient_model import Patient
from app.models.appointment_model import Appointment
from app.models.billing_model import Billing
from app.models.role_model import Role
from app.core.constants import UserRole

class HospitalRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, hospital: Hospital) -> Hospital:
        self.db.add(hospital)
        await self.db.flush()
        await self.db.refresh(hospital)
        return hospital

    async def get_by_id(self, id: int) -> Hospital | None:
        result = await self.db.execute(select(Hospital).where(Hospital.id == id, Hospital.is_deleted == False))
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Hospital | None:
        result = await self.db.execute(select(Hospital).where(Hospital.email == email, Hospital.is_deleted == False))
        return result.scalar_one_or_none()

    async def list_hospitals(self, skip: int = 0, limit: int = 100) -> list[Hospital]:
        result = await self.db.execute(
            select(Hospital).where(Hospital.is_deleted == False).offset(skip).limit(limit)
        )
        return list(result.scalars().all())

    async def count_hospitals(self) -> int:
        return await self.db.scalar(
            select(func.count()).select_from(Hospital).where(Hospital.is_deleted == False)
        ) or 0

    async def update(self, hospital: Hospital) -> Hospital:
        await self.db.flush()
        await self.db.refresh(hospital)
        return hospital

    async def delete(self, hospital: Hospital) -> None:
        hospital.is_deleted = True
        hospital.is_active = False
        await self.db.flush()

    async def get_stats(self, hospital_id: int) -> dict:
        # 1. Total Doctors
        doc_query = select(func.count(Doctor.id)).join(User, Doctor.user_id == User.id).where(
            User.hospital_id == hospital_id,
            Doctor.is_deleted == False
        )
        doctors_count = await self.db.scalar(doc_query) or 0

        # 2. Total Patients
        pat_query = select(func.count(Patient.id)).join(User, Patient.user_id == User.id).where(
            User.hospital_id == hospital_id,
            Patient.is_deleted == False
        )
        patients_count = await self.db.scalar(pat_query) or 0

        # 3. Total Appointments
        app_query = select(func.count(Appointment.id)).join(Doctor, Appointment.doctor_id == Doctor.id).join(User, Doctor.user_id == User.id).where(
            User.hospital_id == hospital_id
        )
        appointments_count = await self.db.scalar(app_query) or 0

        # 4. Total Revenue from Payments/Billing
        rev_query = select(func.sum(Billing.paid_amount)).join(Patient, Billing.patient_id == Patient.id).join(User, Patient.user_id == User.id).where(
            User.hospital_id == hospital_id
        )
        revenue_sum = await self.db.scalar(rev_query) or 0.0

        return {
            "hospital_id": hospital_id,
            "total_doctors": doctors_count,
            "total_patients": patients_count,
            "total_appointments": appointments_count,
            "revenue_summary": float(revenue_sum)
        }

    # Hospital Admin helpers
    async def create_admin_user(self, user: User) -> User:
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def list_admins(self) -> list[User]:
        result = await self.db.execute(
            select(User).join(Role).where(
                Role.name == UserRole.HOSPITAL_ADMIN,
                User.is_active == True
            )
        )
        return list(result.scalars().all())

    async def get_admin_by_id(self, admin_id: int) -> User | None:
        result = await self.db.execute(
            select(User).join(Role).where(
                User.id == admin_id,
                Role.name == UserRole.HOSPITAL_ADMIN
            )
        )
        return result.scalar_one_or_none()
