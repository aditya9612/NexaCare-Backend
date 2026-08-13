from datetime import date
from sqlalchemy import func, or_, select, cast, String, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment_model import Appointment
from app.models.patient_model import FamilyMember, Patient, PatientDocument


class PatientRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _base_query(self, nurse_id: int | None = None):
        query = select(Patient).where(Patient.is_deleted.is_(False))
        if nurse_id is not None:
            from app.models.nurse_model import NursePatientAssignment
            query = query.join(
                NursePatientAssignment,
                NursePatientAssignment.patient_id == Patient.id
            ).where(
                NursePatientAssignment.nurse_id == nurse_id,
                NursePatientAssignment.status == "Active"
            )
        return query

    async def list_all(
        self,
        skip: int = 0,
        limit: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        start_date: date | None = None,
        end_date: date | None = None,
        nurse_id: int | None = None,
    ) -> list[Patient]:
        from datetime import datetime, time
        query = self._base_query(nurse_id)
        if start_date:
            start_dt = datetime.combine(start_date, time.min)
            query = query.where(Patient.created_at >= start_dt)
        if end_date:
            end_dt = datetime.combine(end_date, time.max)
            query = query.where(Patient.created_at <= end_dt)

        column = getattr(Patient, sort_by, Patient.created_at)
        query = query.order_by(column.desc() if sort_order == "desc" else column.asc())
        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_all(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        nurse_id: int | None = None,
    ) -> int:
        from datetime import datetime, time
        query = select(func.count()).select_from(Patient).where(Patient.is_deleted.is_(False))
        if nurse_id is not None:
            from app.models.nurse_model import NursePatientAssignment
            query = query.join(
                NursePatientAssignment,
                NursePatientAssignment.patient_id == Patient.id
            ).where(
                NursePatientAssignment.nurse_id == nurse_id,
                NursePatientAssignment.status == "Active"
            )
        if start_date:
            start_dt = datetime.combine(start_date, time.min)
            query = query.where(Patient.created_at >= start_dt)
        if end_date:
            end_dt = datetime.combine(end_date, time.max)
            query = query.where(Patient.created_at <= end_dt)

        result = await self.db.scalar(query)
        return result or 0

    async def get_by_id(self, patient_id: int) -> Patient | None:
        result = await self.db.execute(
            self._base_query().where(Patient.id == patient_id)
        )
        return result.scalar_one_or_none()

    async def get_by_phone(self, phone: str) -> Patient | None:
        from app.utils.phone_utils import indian_mobile_last10

        last10 = indian_mobile_last10(phone)
        if not last10:
            return None
        # Exact match first — prefer account holders (no guardian)
        result = await self.db.execute(
            self._base_query()
            .where(Patient.phone == phone)
            .order_by(Patient.guardian_patient_id.is_(None).desc(), Patient.id.asc())
        )
        hit = result.scalars().first()
        if hit:
            return hit
        # Match any stored format ending with same 10 digits
        result = await self.db.execute(
            self._base_query()
            .where(Patient.phone.is_not(None))
            .order_by(Patient.guardian_patient_id.is_(None).desc(), Patient.id.asc())
        )
        for patient in result.scalars().all():
            if indian_mobile_last10(patient.phone) == last10:
                return patient
        return None

    async def list_dependents(self, guardian_patient_id: int) -> list[Patient]:
        result = await self.db.execute(
            self._base_query()
            .where(Patient.guardian_patient_id == guardian_patient_id)
            .order_by(Patient.id.asc())
        )
        return list(result.scalars().all())

    async def get_by_email(self, email: str) -> Patient | None:
        result = await self.db.execute(
            self._base_query().where(Patient.email == email)
        )
        return result.scalar_one_or_none()

    def _search_filter(self, q: str):
        q_clean = q.strip().lower()
        pattern = f"%{q_clean}%"
        concat_name = func.lower(Patient.first_name) + " " + func.lower(Patient.last_name)
        base_filter = or_(
            func.lower(Patient.first_name).like(pattern),
            func.lower(Patient.last_name).like(pattern),
            func.lower(Patient.patient_code).like(pattern),
            func.lower(cast(Patient.phone, String)).like(pattern),
            func.lower(cast(Patient.email, String)).like(pattern),
            concat_name.like(pattern),
        )
        
        words = q_clean.split()
        if len(words) > 1:
            from sqlalchemy import and_
            word_filters = []
            for word in words:
                word_pattern = f"%{word}%"
                word_filters.append(
                    or_(
                        func.lower(Patient.first_name).like(word_pattern),
                        func.lower(Patient.last_name).like(word_pattern),
                        func.lower(Patient.patient_code).like(word_pattern),
                        func.lower(cast(Patient.phone, String)).like(word_pattern),
                        func.lower(cast(Patient.email, String)).like(word_pattern),
                    )
                )
            return or_(base_filter, and_(*word_filters))
            
        return base_filter

    async def search(self, q: str, skip: int = 0, limit: int = 20, nurse_id: int | None = None) -> list[Patient]:
        query = self._base_query(nurse_id).where(self._search_filter(q))
        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_search(self, q: str, nurse_id: int | None = None) -> int:
        query = select(func.count()).select_from(Patient).where(Patient.is_deleted.is_(False), self._search_filter(q))
        if nurse_id is not None:
            from app.models.nurse_model import NursePatientAssignment
            query = query.join(
                NursePatientAssignment,
                NursePatientAssignment.patient_id == Patient.id
            ).where(
                NursePatientAssignment.nurse_id == nurse_id,
                NursePatientAssignment.status == "Active"
            )
        result = await self.db.scalar(query)
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
        nurse_id: int | None = None,
    ) -> list[Patient]:
        query = self._base_query(nurse_id)
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
        nurse_id: int | None = None,
    ) -> int:
        query = select(func.count()).select_from(Patient).where(Patient.is_deleted.is_(False))
        if nurse_id is not None:
            from app.models.nurse_model import NursePatientAssignment
            query = query.join(
                NursePatientAssignment,
                NursePatientAssignment.patient_id == Patient.id
            ).where(
                NursePatientAssignment.nurse_id == nurse_id,
                NursePatientAssignment.status == "Active"
            )
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

    async def get_patient_stats(self, nurse_id: int | None = None) -> dict[str, int]:
        query = select(
            func.count(case((Patient.status == "active", 1))).label("active_count"),
            func.count(case((Patient.status == "inactive", 1))).label("inactive_count"),
            func.count(func.distinct(case((Patient.city != "", Patient.city), else_=None))).label("cities_count")
        ).select_from(Patient).where(Patient.is_deleted.is_(False))
        if nurse_id is not None:
            from app.models.nurse_model import NursePatientAssignment
            query = query.join(
                NursePatientAssignment,
                NursePatientAssignment.patient_id == Patient.id
            ).where(
                NursePatientAssignment.nurse_id == nurse_id,
                NursePatientAssignment.status == "Active"
            )
        
        result = await self.db.execute(query)
        row = result.one()
        return {
            "active_count": row.active_count or 0,
            "inactive_count": row.inactive_count or 0,
            "cities_count": row.cities_count or 0,
        }

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
        from sqlalchemy.orm import selectinload
        result = await self.db.execute(
            select(Appointment)
            .where(Appointment.patient_id == patient_id)
            .options(selectinload(Appointment.patient))
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

    async def get_document(self, document_id: int) -> PatientDocument | None:
        result = await self.db.execute(
            select(PatientDocument).where(PatientDocument.id == document_id)
        )
        return result.scalar_one_or_none()

    async def delete_document(self, document: PatientDocument) -> None:
        await self.db.delete(document)
        await self.db.flush()
