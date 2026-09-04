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
        appointment_type: str | None = None,
        booking_source: str | None = None,
        sort_by: str = "appointment_date",
        sort_order: str = "desc",
        admission_status: str | None = None,
        triage_level: int | None = None,
        disposition: str | None = None,
    ) -> list[Appointment]:
        query = select(Appointment).options(joinedload(Appointment.patient))
        query = self._apply_filters(
            query,
            patient_id,
            doctor_id,
            department_id,
            status,
            appointment_date,
            appointment_type,
            booking_source,
            admission_status,
            triage_level=triage_level,
            disposition=disposition,
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
        appointment_type: str | None = None,
        booking_source: str | None = None,
        admission_status: str | None = None,
        triage_level: int | None = None,
        disposition: str | None = None,
    ) -> int:
        query = select(func.count()).select_from(Appointment)
        query = self._apply_filters(
            query,
            patient_id,
            doctor_id,
            department_id,
            status,
            appointment_date,
            appointment_type,
            booking_source,
            admission_status,
            triage_level=triage_level,
            disposition=disposition,
        )
        return await self.db.scalar(query) or 0

    def _apply_filters(
        self,
        query,
        patient_id,
        doctor_id,
        department_id,
        status,
        appointment_date,
        appointment_type=None,
        booking_source=None,
        admission_status=None,
        triage_level=None,
        disposition=None,
    ):
        if patient_id:
            query = query.where(Appointment.patient_id == patient_id)
        if doctor_id:
            query = query.where(Appointment.doctor_id == doctor_id)
        if department_id:
            query = query.where(Appointment.department_id == department_id)
        if status:
            if isinstance(status, (list, tuple, set)):
                query = query.where(Appointment.appointment_status.in_(status))
            else:
                s_lower = str(status).strip().lower().replace("_", "-")
                if s_lower in ("check-in", "checked-in"):
                    query = query.where(
                        or_(
                            Appointment.appointment_status.in_(["Checked-In", "Check-in", "checked-in", "checked_in", "Check-In"]),
                            Appointment.check_in_time.isnot(None),
                        )
                    )
                elif s_lower in ("check-out", "checked-out"):
                    query = query.where(
                        Appointment.appointment_status.in_(["Checked-Out", "Checked-out", "checked-out", "Check-out", "Check-Out"])
                    )
                elif s_lower in ("in-progress", "in-consultation", "in_consultation"):
                    query = query.where(
                        or_(
                            Appointment.appointment_status.in_(["In-Progress", "in-progress", "In-progress", "in_progress", "In_Progress"]),
                            Appointment.queue_status.in_(["IN_CONSULTATION", "in_consultation", "IN-PROGRESS", "in-progress"]),
                        )
                    )
                elif s_lower == "waiting":
                    query = query.where(func.upper(Appointment.queue_status) == "WAITING")
                elif s_lower == "pending":
                    query = query.where(Appointment.appointment_status.in_(["Pending", "pending", "PENDING"]))
                elif s_lower == "confirmed":
                    query = query.where(Appointment.appointment_status.in_(["Confirmed", "confirmed", "CONFIRMED"]))
                elif s_lower == "completed":
                    query = query.where(Appointment.appointment_status.in_(["Completed", "completed", "COMPLETED"]))
                elif s_lower in ("cancelled", "canceled"):
                    query = query.where(Appointment.appointment_status.in_(["Cancelled", "cancelled", "CANCELLED", "Canceled", "canceled"]))
                elif s_lower in ("no-show", "no show"):
                    query = query.where(Appointment.appointment_status.in_(["No Show", "no show", "NO SHOW", "No-Show", "no-show"]))
                elif s_lower in ("admit-recommended", "admit recommended", "admit_recommended"):
                    query = query.where(
                        or_(
                            Appointment.admission_status.in_(["Admit Recommended", "admit recommended", "Admit-Recommended", "admit-recommended", "admit_recommended"]),
                            Appointment.appointment_status.in_(["Admit Recommended", "admit recommended", "Admit-Recommended", "admit-recommended", "admit_recommended"]),
                            Appointment.admission_recommended.is_(True),
                        )
                    )
                elif s_lower in ("admitted", "admit"):
                    query = query.where(
                        or_(
                            Appointment.admission_status.in_(["Admitted", "admitted", "ADMITTED"]),
                            Appointment.appointment_status.in_(["Admitted", "admitted", "ADMITTED"]),
                        )
                    )
                else:
                    query = query.where(func.lower(Appointment.appointment_status) == func.lower(status))
        if admission_status:
            if isinstance(admission_status, (list, tuple, set)):
                query = query.where(Appointment.admission_status.in_(admission_status))
            else:
                adm_lower = str(admission_status).strip().lower().replace("_", "-")
                if adm_lower in ("admit-recommended", "admit recommended", "admit_recommended"):
                    query = query.where(
                        or_(
                            Appointment.admission_status.in_(["Admit Recommended", "admit recommended", "Admit-Recommended", "admit-recommended", "admit_recommended"]),
                            Appointment.admission_recommended.is_(True),
                        )
                    )
                elif adm_lower in ("admitted", "admit"):
                    query = query.where(
                        Appointment.admission_status.in_(["Admitted", "admitted", "ADMITTED"])
                    )
                else:
                    query = query.where(func.lower(Appointment.admission_status) == func.lower(admission_status))
        if appointment_date:
            query = query.where(Appointment.appointment_date == appointment_date)
        if appointment_type:
            query = query.where(
                func.lower(Appointment.appointment_type) == func.lower(appointment_type.strip())
            )
        if booking_source:
            query = query.where(
                func.lower(Appointment.booking_source) == func.lower(str(booking_source).strip())
            )
        if triage_level is not None:
            query = query.where(Appointment.triage_level == triage_level)
        if disposition:
            query = query.where(func.lower(Appointment.disposition) == func.lower(str(disposition).strip()))
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

    async def get_next_token(self, doctor_id: int | None, appointment_date: date) -> int:
        result = await self.db.scalar(
            select(func.max(Appointment.token_number)).where(
                Appointment.appointment_date == appointment_date,
            )
        )
        return (result or 0) + 1

    async def get_next_queue_token(self, appointment_date: date) -> str:
        result = await self.db.execute(
            select(Appointment.queue_token).where(
                Appointment.appointment_date == appointment_date,
                Appointment.queue_token.isnot(None)
            )
        )
        tokens = []
        if hasattr(result, "scalars"):
            sc = result.scalars()
            if hasattr(sc, "all") and not hasattr(sc.all, "__await__"):
                tokens = list(sc.all())
            elif hasattr(sc, "__iter__"):
                tokens = list(sc)
        
        max_num = 0
        for t in tokens:
            if isinstance(t, str) and t.startswith("T-"):
                try:
                    num = int(t[2:])
                    if num > max_num:
                        max_num = num
                except ValueError:
                    pass
        return f"T-{max_num + 1}"

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
        from app.utils.helpers import get_today_ist
        today = get_today_ist()
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
        from app.utils.helpers import get_today_ist
        from sqlalchemy.orm import joinedload
        current_date = get_today_ist()
        
        excluded_statuses = [
            AppointmentStatus.CANCELLED,
            AppointmentStatus.COMPLETED,
            "Cancelled",
            "Completed",
            "Checked-Out",
            "checked-out",
            "No Show",
            "no-show",
        ]
        query = (
            select(Appointment)
            .options(joinedload(Appointment.patient))
            .where(
                Appointment.doctor_id == doctor_id,
                Appointment.appointment_date >= current_date,
                Appointment.appointment_status.notin_(excluded_statuses),
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

