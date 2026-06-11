from sqlalchemy import func, or_, select, cast, String
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment_model import Appointment
from app.models.patient_model import FamilyMember, Patient, PatientDocument


class PatientRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _base_query(self):
        return select(Patient).where(Patient.is_deleted.is_(False))

    async def list_all(
        self,
        skip: int = 0,
        limit: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> list[Patient]:
        query = self._base_query()
        column = getattr(Patient, sort_by, Patient.created_at)
        query = query.order_by(column.desc() if sort_order == "desc" else column.asc())
        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_all(self) -> int:
        result = await self.db.scalar(
            select(func.count()).select_from(Patient).where(Patient.is_deleted.is_(False))
        )
        return result or 0

    async def get_by_id(self, patient_id: int) -> Patient | None:
        result = await self.db.execute(
            self._base_query().where(Patient.id == patient_id)
        )
        return result.scalar_one_or_none()

    async def get_by_phone(self, phone: str) -> Patient | None:
        result = await self.db.execute(
            self._base_query().where(Patient.phone == phone)
        )
        return result.scalar_one_or_none()

    def _search_filter(self, q: str):
        pattern = f"%{q.lower()}%"
        return or_(
            func.lower(Patient.first_name).like(pattern),
            func.lower(Patient.last_name).like(pattern),
            func.lower(Patient.patient_code).like(pattern),
            func.lower(cast(Patient.phone, String)).like(pattern),
            func.lower(cast(Patient.email, String)).like(pattern),
        )

    async def search(self, q: str, skip: int = 0, limit: int = 20) -> list[Patient]:
        query = self._base_query().where(self._search_filter(q))
        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_search(self, q: str) -> int:
        result = await self.db.scalar(
            select(func.count())
            .select_from(Patient)
            .where(Patient.is_deleted.is_(False), self._search_filter(q))
        )
        return result or 0

    async def filter_patients(
        self,
        gender: str | None = None,
        blood_group: str | None = None,
        city: str | None = None,
        state: str | None = None,
        status: str | None = None,
        skip: int = 0,
        limit: int = 20,
    ) -> list[Patient]:
        query = self._base_query()
        if gender:
            query = query.where(Patient.gender == gender)
        if blood_group:
            query = query.where(Patient.blood_group == blood_group)
        if city:
            query = query.where(Patient.city == city)
        if state:
            query = query.where(Patient.state == state)
        if status:
            query = query.where(Patient.status == status)
        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_filter(
        self,
        gender: str | None = None,
        blood_group: str | None = None,
        city: str | None = None,
        state: str | None = None,
        status: str | None = None,
    ) -> int:
        query = select(func.count()).select_from(Patient).where(Patient.is_deleted.is_(False))
        if gender:
            query = query.where(Patient.gender == gender)
        if blood_group:
            query = query.where(Patient.blood_group == blood_group)
        if city:
            query = query.where(Patient.city == city)
        if state:
            query = query.where(Patient.state == state)
        if status:
            query = query.where(Patient.status == status)
        return await self.db.scalar(query) or 0

    async def create(self, patient: Patient) -> Patient:
        self.db.add(patient)
        await self.db.flush()
        await self.db.refresh(patient)
        return patient

    async def update(self, patient: Patient) -> Patient:
        await self.db.flush()
        await self.db.refresh(patient)
        return patient

    async def soft_delete(self, patient: Patient) -> Patient:
        from app.utils.helpers import utc_now

        patient.is_deleted = True
        patient.deleted_at = utc_now()
        patient.status = "inactive"
        await self.db.flush()
        return patient

    async def get_appointments(self, patient_id: int) -> list[Appointment]:
        result = await self.db.execute(
            select(Appointment)
            .where(Appointment.patient_id == patient_id)
            .order_by(Appointment.appointment_date.desc(), Appointment.appointment_time.desc())
        )
        return list(result.scalars().all())

    async def add_family_member(self, member: FamilyMember) -> FamilyMember:
        self.db.add(member)
        await self.db.flush()
        await self.db.refresh(member)
        return member

    async def list_family_members(self, patient_id: int) -> list[FamilyMember]:
        result = await self.db.execute(
            select(FamilyMember).where(FamilyMember.patient_id == patient_id)
        )
        return list(result.scalars().all())

    async def add_document(self, document: PatientDocument) -> PatientDocument:
        self.db.add(document)
        await self.db.flush()
        await self.db.refresh(document)
        return document

    async def list_documents(self, patient_id: int) -> list[PatientDocument]:
        result = await self.db.execute(
            select(PatientDocument).where(PatientDocument.patient_id == patient_id)
        )
        return list(result.scalars().all())
