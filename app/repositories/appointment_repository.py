from datetime import date, datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.constants import AppointmentStatus
from app.models.appointment_model import Appointment


class AppointmentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all(
        self,
        skip: int = 0,
        limit: int = 20,
        patient_id: int | None = None,
        doctor_id: int | None = None,
        department_id: int | None = None,
        status: str | None = None,
        appointment_date: date | None = None,
        sort_by: str = "appointment_date",
        sort_order: str = "desc",
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[Appointment]:
        query = select(Appointment).options(joinedload(Appointment.patient))
        query = self._apply_filters(query, patient_id, doctor_id, department_id, status, appointment_date)
        query = select(Appointment)
        query = self._apply_filters(
            query, patient_id, doctor_id, department_id, status, appointment_date, start_date, end_date
        )
        column = getattr(Appointment, sort_by, Appointment.appointment_date)
        query = query.order_by(column.desc() if sort_order == "desc" else column.asc())
        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_all(
        self,
        patient_id: int | None = None,
        doctor_id: int | None = None,
        department_id: int | None = None,
        status: str | None = None,
        appointment_date: date | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> int:
        query = select(func.count()).select_from(Appointment)
        query = self._apply_filters(
            query, patient_id, doctor_id, department_id, status, appointment_date, start_date, end_date
        )
        return await self.db.scalar(query) or 0

    def _apply_filters(
        self, query, patient_id, doctor_id, department_id, status, appointment_date,
        start_date: date | None = None, end_date: date | None = None
    ):
        if patient_id:
            query = query.where(Appointment.patient_id == patient_id)
        if doctor_id:
            query = query.where(Appointment.doctor_id == doctor_id)
        if department_id:
            query = query.where(Appointment.department_id == department_id)
        if status:
            query = query.where(Appointment.appointment_status == status)
        if appointment_date:
            query = query.where(Appointment.appointment_date == appointment_date)
        if start_date:
            query = query.where(Appointment.appointment_date >= start_date)
        if end_date:
            query = query.where(Appointment.appointment_date <= end_date)
        return query

    async def get_by_id(self, appointment_id: int) -> Appointment | None:
        result = await self.db.execute(
            select(Appointment)
            .options(joinedload(Appointment.patient))
            .where(Appointment.id == appointment_id)
        )
        return result.scalar_one_or_none()

    async def exists_conflict(
        self,
        doctor_id: int,
        appointment_date: date,
        appointment_time,
        exclude_id: int | None = None,
    ) -> bool:
        query = select(Appointment).where(
            Appointment.doctor_id == doctor_id,
            Appointment.appointment_date == appointment_date,
            Appointment.appointment_time == appointment_time,
            Appointment.appointment_status.in_(list(AppointmentStatus.ACTIVE)),
        )
        if exclude_id:
            query = query.where(Appointment.id != exclude_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none() is not None

    async def get_next_token(self, doctor_id: int, appointment_date: date) -> int:
        result = await self.db.scalar(
            select(func.max(Appointment.token_number)).where(
                Appointment.doctor_id == doctor_id,
                Appointment.appointment_date == appointment_date,
            )
        )
        return (result or 0) + 1

    async def create(self, appointment: Appointment) -> Appointment:
        self.db.add(appointment)
        await self.db.flush()
        await self.db.refresh(appointment)
        result = await self.db.execute(
            select(Appointment)
            .options(joinedload(Appointment.patient))
            .where(Appointment.id == appointment.id)
        )
        return result.scalar_one()

    async def update(self, appointment: Appointment) -> Appointment:
        await self.db.flush()
        await self.db.refresh(appointment)
        result = await self.db.execute(
            select(Appointment)
            .options(joinedload(Appointment.patient))
            .where(Appointment.id == appointment.id)
        )
        return result.scalar_one()

    async def delete(self, appointment: Appointment) -> None:
        await self.db.delete(appointment)
        await self.db.flush()

    async def get_calendar(
        self,
        start_date: date,
        end_date: date,
        doctor_id: int | None = None,
    ) -> list[Appointment]:
        query = (
            select(Appointment)
            .options(joinedload(Appointment.patient))
            .where(
                Appointment.appointment_date >= start_date,
                Appointment.appointment_date <= end_date,
            )
        )
        if doctor_id:
            query = query.where(Appointment.doctor_id == doctor_id)
        query = query.order_by(Appointment.appointment_date, Appointment.appointment_time)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_today(self) -> list[Appointment]:
        today = date.today()
        result = await self.db.execute(
            select(Appointment)
            .options(joinedload(Appointment.patient))
            .where(Appointment.appointment_date == today)
            .order_by(Appointment.appointment_time)
        )
        return list(result.scalars().all())

    async def get_upcoming(self, limit: int = 20) -> list[Appointment]:
        today = date.today()
        result = await self.db.execute(
            select(Appointment)
            .options(joinedload(Appointment.patient))
            .where(
                Appointment.appointment_date >= today,
                Appointment.appointment_status.in_(list(AppointmentStatus.ACTIVE)),
            )
            .order_by(Appointment.appointment_date, Appointment.appointment_time)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_by_status(self, status: str, on_date: date | None = None) -> int:
        query = select(func.count()).select_from(Appointment).where(Appointment.appointment_status == status)
        if on_date:
            query = query.where(Appointment.appointment_date == on_date)
        return await self.db.scalar(query) or 0

    async def count_today(self) -> int:
        return (
            await self.db.scalar(
                select(func.count()).select_from(Appointment).where(Appointment.appointment_date == date.today())
            )
            or 0
        )

    async def list_needing_voice_reminder(self, target_date: date) -> list[Appointment]:
        result = await self.db.execute(
            select(Appointment).where(
                Appointment.appointment_date == target_date,
                Appointment.reminder_sent.is_(False),
                Appointment.appointment_status.in_(list(AppointmentStatus.ACTIVE)),
            )
        )
        return list(result.scalars().all())

    async def get_upcoming_appointments(self, doctor_id: int, limit: int = 10) -> list[Appointment]:
        now = datetime.now()
        current_date = now.date()
        current_time = now.time()
        query = (
            select(Appointment)
            .where(
                Appointment.doctor_id == doctor_id,
                Appointment.appointment_status == AppointmentStatus.CONFIRMED,
                or_(
                    Appointment.appointment_date > current_date,
                    and_(
                        Appointment.appointment_date == current_date,
                        Appointment.appointment_time >= current_time,
                    ),
                ),
            )
            .order_by(Appointment.appointment_date.asc(), Appointment.appointment_time.asc())
            .limit(limit)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_confirmed_appointments(
        self,
        skip: int = 0,
        limit: int = 20,
        search: str | None = None,
        doctor_id: int | None = None,
        department_id: int | None = None,
        appointment_date: date | None = None,
    ) -> list[Appointment]:
        from app.models.patient_model import Patient
        from sqlalchemy.orm import joinedload
        
        query = select(Appointment).where(
            Appointment.appointment_status == AppointmentStatus.CONFIRMED
        )
        
        if search:
            search_pattern = f"%{search.lower()}%"
            query = query.join(Patient, Appointment.patient_id == Patient.id).where(
                or_(
                    func.lower(Patient.first_name).like(search_pattern),
                    func.lower(Patient.last_name).like(search_pattern),
                    func.lower(Appointment.appointment_number).like(search_pattern),
                )
            )
            
        if doctor_id:
            query = query.where(Appointment.doctor_id == doctor_id)
        if department_id:
            query = query.where(Appointment.department_id == department_id)
        if appointment_date:
            query = query.where(Appointment.appointment_date == appointment_date)
            
        query = query.options(
            joinedload(Appointment.patient),
            joinedload(Appointment.doctor),
            joinedload(Appointment.department)
        ).order_by(
            Appointment.appointment_date.asc(),
            Appointment.appointment_time.asc()
        )
        
        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_confirmed_appointments(
        self,
        search: str | None = None,
        doctor_id: int | None = None,
        department_id: int | None = None,
        appointment_date: date | None = None,
    ) -> int:
        from app.models.patient_model import Patient
        
        query = select(func.count()).select_from(Appointment).where(
            Appointment.appointment_status == AppointmentStatus.CONFIRMED
        )
        
        if search:
            search_pattern = f"%{search.lower()}%"
            query = query.join(Patient, Appointment.patient_id == Patient.id).where(
                or_(
                    func.lower(Patient.first_name).like(search_pattern),
                    func.lower(Patient.last_name).like(search_pattern),
                    func.lower(Appointment.appointment_number).like(search_pattern),
                )
            )
            
        if doctor_id:
            query = query.where(Appointment.doctor_id == doctor_id)
        if department_id:
            query = query.where(Appointment.department_id == department_id)
        if appointment_date:
            query = query.where(Appointment.appointment_date == appointment_date)
            
        return await self.db.scalar(query) or 0

