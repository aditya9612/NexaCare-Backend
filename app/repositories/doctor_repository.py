from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment_model import Appointment
from app.models.doctor_model import Doctor, DoctorSchedule
from app.models.department_model import Department


class DoctorRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _base_query(self):
        return select(Doctor).outerjoin(Doctor.department).where(Doctor.is_deleted.is_(False))

    async def list_all(
        self,
        skip: int = 0,
        limit: int = 20,
        department_id: int | None = None,
        availability_status: str | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> list[Doctor]:
        query = self._base_query()
        if department_id:
            query = query.where(Doctor.department_id == department_id)
        if availability_status:
            query = query.where(Doctor.availability_status == availability_status)
        column = getattr(Doctor, sort_by, Doctor.created_at)
        query = query.order_by(column.desc() if sort_order == "desc" else column.asc())
        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_all(
        self,
        department_id: int | None = None,
        availability_status: str | None = None,
    ) -> int:
        query = select(func.count()).select_from(Doctor).where(Doctor.is_deleted.is_(False))
        if department_id:
            query = query.where(Doctor.department_id == department_id)
        if availability_status:
            query = query.where(Doctor.availability_status == availability_status)
        return await self.db.scalar(query) or 0

    async def get_by_id(self, doctor_id: int) -> Doctor | None:
        result = await self.db.execute(self._base_query().where(Doctor.id == doctor_id))
        return result.scalar_one_or_none()

    def _search_filter(self, q: str):
        pattern = f"%{q.lower()}%"
        return or_(
            func.lower(Doctor.first_name).like(pattern),
            func.lower(Doctor.last_name).like(pattern),
            func.lower(Doctor.doctor_code).like(pattern),
            func.lower(Doctor.specialization).like(pattern),
            func.lower(Department.department_name).like(pattern),
        )

    async def search(self, q: str, skip: int = 0, limit: int = 20) -> list[Doctor]:
        query = self._base_query().where(self._search_filter(q))
        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_search(self, q: str) -> int:
        return (
            await self.db.scalar(
                select(func.count())
                .select_from(Doctor)
                .outerjoin(Doctor.department)
                .where(Doctor.is_deleted.is_(False), self._search_filter(q))
            )
            or 0
        )

    async def list_available(self) -> list[Doctor]:
        result = await self.db.execute(
            self._base_query().where(Doctor.availability_status == "available")
        )
        return list(result.scalars().all())

    async def get_by_license(self, license_number: str) -> Doctor | None:
        result = await self.db.execute(
            select(Doctor).where(Doctor.license_number == license_number, Doctor.is_deleted.is_(False))
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Doctor | None:
        result = await self.db.execute(
            select(Doctor).where(Doctor.email == email, Doctor.is_deleted.is_(False))
        )
        return result.scalar_one_or_none()

    async def get_by_user_id(self, user_id: int) -> Doctor | None:
        result = await self.db.execute(
            select(Doctor).where(Doctor.user_id == user_id, Doctor.is_deleted.is_(False))
        )
        return result.scalar_one_or_none()

    async def create(self, doctor: Doctor) -> Doctor:
        self.db.add(doctor)
        await self.db.flush()
        await self.db.refresh(doctor)
        return doctor

    async def update(self, doctor: Doctor) -> Doctor:
        await self.db.flush()
        await self.db.refresh(doctor)
        return doctor

    async def soft_delete(self, doctor: Doctor) -> Doctor:
        doctor.is_deleted = True
        doctor.availability_status = "unavailable"
        await self.db.flush()
        return doctor

    async def get_appointments(self, doctor_id: int) -> list[Appointment]:
        result = await self.db.execute(
            select(Appointment)
            .where(Appointment.doctor_id == doctor_id)
            .order_by(Appointment.appointment_date.desc(), Appointment.appointment_time.desc())
        )
        return list(result.scalars().all())

    async def get_schedule(self, doctor_id: int) -> list[DoctorSchedule]:
        result = await self.db.execute(
            select(DoctorSchedule)
            .where(DoctorSchedule.doctor_id == doctor_id, DoctorSchedule.is_active.is_(True))
            .order_by(DoctorSchedule.day_of_week)
        )
        return list(result.scalars().all())

    async def add_schedule(self, schedule: DoctorSchedule) -> DoctorSchedule:
        self.db.add(schedule)
        await self.db.flush()
        await self.db.refresh(schedule)
        return schedule
