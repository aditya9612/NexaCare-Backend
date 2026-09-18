from datetime import date
from sqlalchemy import func, or_, select, cast, String, case
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.appointment_model import Appointment
from app.models.patient_model import FamilyMember, Patient, PatientDocument


class PatientRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _base_query(self, nurse_id: int | None = None, allowed_patient_ids: list[int] | None = None):
        query = select(Patient).where(Patient.is_deleted.is_(False))
        if allowed_patient_ids is not None:
            query = query.where(Patient.id.in_(allowed_patient_ids))
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
        allowed_patient_ids: list[int] | None = None,
    ) -> list[Patient]:
        from datetime import datetime, time
        query = self._base_query(nurse_id=nurse_id, allowed_patient_ids=allowed_patient_ids)
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
        allowed_patient_ids: list[int] | None = None,
    ) -> int:
        from datetime import datetime, time
        query = select(func.count()).select_from(Patient).where(Patient.is_deleted.is_(False))
        if allowed_patient_ids is not None:
            query = query.where(Patient.id.in_(allowed_patient_ids))
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

    async def search(
        self,
        q: str,
        skip: int = 0,
        limit: int = 20,
        nurse_id: int | None = None,
        allowed_patient_ids: list[int] | None = None,
    ) -> list[Patient]:
        query = self._base_query(nurse_id=nurse_id, allowed_patient_ids=allowed_patient_ids).where(self._search_filter(q))
        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_search(
        self,
        q: str,
        nurse_id: int | None = None,
        allowed_patient_ids: list[int] | None = None,
    ) -> int:
        query = select(func.count()).select_from(Patient).where(Patient.is_deleted.is_(False), self._search_filter(q))
        if allowed_patient_ids is not None:
            query = query.where(Patient.id.in_(allowed_patient_ids))
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
        allowed_patient_ids: list[int] | None = None,
    ) -> list[Patient]:
        query = self._base_query(nurse_id=nurse_id, allowed_patient_ids=allowed_patient_ids)
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
        allowed_patient_ids: list[int] | None = None,
    ) -> int:
        query = select(func.count()).select_from(Patient).where(Patient.is_deleted.is_(False))
        if allowed_patient_ids is not None:
            query = query.where(Patient.id.in_(allowed_patient_ids))
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

    async def get_patient_stats(
        self,
        nurse_id: int | None = None,
        allowed_patient_ids: list[int] | None = None,
    ) -> dict[str, int]:
        from datetime import datetime, time
        import calendar
        from sqlalchemy import and_
        from app.utils.helpers import get_today_ist
        from app.repositories.discharge_repository import DischargeRepository
        from app.models.bed_allocation_model import Bed

        today = get_today_ist()
        start_of_month = datetime.combine(date(today.year, today.month, 1), time.min)
        _, last_day = calendar.monthrange(today.year, today.month)
        end_of_month = datetime.combine(date(today.year, today.month, last_day), time.max)

        # 1. Baseline patient stats + this_month
        query = select(
            func.count(case((Patient.status == "active", 1))).label("active_count"),
            func.count(case((Patient.status == "inactive", 1))).label("inactive_count"),
            func.count(func.distinct(case((Patient.city != "", Patient.city), else_=None))).label("cities_count"),
            func.count(
                case(
                    (
                        and_(
                            Patient.created_at >= start_of_month,
                            Patient.created_at <= end_of_month,
                        ),
                        1,
                    )
                )
            ).label("this_month"),
        ).select_from(Patient).where(Patient.is_deleted.is_(False))
        if allowed_patient_ids is not None:
            query = query.where(Patient.id.in_(allowed_patient_ids))
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

        # 2. IPD: Unique patients currently admitted/inpatient (not discharged/cancelled)
        admitted_subq = (
            select(Appointment.patient_id)
            .where(
                func.lower(Appointment.admission_status) == "admitted",
                Appointment.appointment_status.notin_(["Cancelled", "cancelled", "CANCELLED"]),
            )
        )
        occupied_bed_subq = (
            select(Bed.patient_id)
            .where(
                Bed.status.in_(["Occupied", "Reserved"]),
                Bed.patient_id.isnot(None),
            )
        )
        ipd_query = (
            select(func.count(Patient.id))
            .select_from(Patient)
            .where(
                Patient.is_deleted.is_(False),
                or_(
                    Patient.id.in_(admitted_subq),
                    Patient.id.in_(occupied_bed_subq),
                ),
            )
        )
        if nurse_id is not None:
            from app.models.nurse_model import NursePatientAssignment
            ipd_query = ipd_query.join(
                NursePatientAssignment,
                NursePatientAssignment.patient_id == Patient.id,
            ).where(
                NursePatientAssignment.nurse_id == nurse_id,
                NursePatientAssignment.status == "Active",
            )
        ipd_count = await self.db.scalar(ipd_query) or 0

        # 3. OPD: Unique patients having valid OPD appointments (excluding Cancelled and No Show)
        opd_query = (
            select(func.count(func.distinct(Appointment.patient_id)))
            .select_from(Appointment)
            .join(Patient, Appointment.patient_id == Patient.id)
            .where(
                Patient.is_deleted.is_(False),
                func.upper(Appointment.appointment_type) == "OPD",
                or_(
                    Appointment.appointment_status.is_(None),
                    Appointment.appointment_status.notin_([
                        "Cancelled", "cancelled", "CANCELLED", "Canceled", "canceled",
                        "No Show", "no show", "NO SHOW", "No-Show", "no-show",
                    ]),
                ),
            )
        )
        if nurse_id is not None:
            from app.models.nurse_model import NursePatientAssignment
            opd_query = opd_query.join(
                NursePatientAssignment,
                NursePatientAssignment.patient_id == Patient.id,
            ).where(
                NursePatientAssignment.nurse_id == nurse_id,
                NursePatientAssignment.status == "Active",
            )
        opd_count = await self.db.scalar(opd_query) or 0

        # 4. today_discharge: Unique patients actually discharged today
        today_discharge_count = await DischargeRepository(self.db).count_today_discharged(
            on_date=today, nurse_id=nurse_id
        )

        return {
            "active_count": row.active_count or 0,
            "inactive_count": row.inactive_count or 0,
            "cities_count": row.cities_count or 0,
            "this_month": row.this_month or 0,
            "ipd": ipd_count,
            "opd": opd_count,
            "today_discharge": today_discharge_count,
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

    async def get_family_member(self, member_id: int) -> FamilyMember | None:
        result = await self.db.execute(
            select(FamilyMember).where(FamilyMember.id == member_id)
        )
        return result.scalar_one_or_none()

    async def delete_family_member(self, member: FamilyMember) -> None:
        await self.db.delete(member)
        await self.db.flush()

    async def get_patient_lab_history(self, patient_id: int):
        from app.models.lab_model import TestOrder
        from app.schemas.patient_schema import LabHistoryResponse
        from datetime import datetime

        stmt = (
            select(TestOrder)
            .options(
                selectinload(TestOrder.lab_test),
                selectinload(TestOrder.samples),
                selectinload(TestOrder.reports),
            )
            .where(
                TestOrder.is_deleted.is_(False),
                or_(
                    TestOrder.patient_id == patient_id,
                    TestOrder.appointment_id.in_(
                        select(Appointment.id).where(Appointment.patient_id == patient_id)
                    ),
                ),
            )
            .order_by(TestOrder.ordered_at.desc(), TestOrder.id.desc())
        )
        result = await self.db.execute(stmt)
        orders = list(result.scalars().unique().all())

        history: list[LabHistoryResponse] = []
        for o in orders:
            # resolve sample collection date
            sample_date = None
            if hasattr(o, "samples") and o.samples:
                for s in o.samples:
                    dt = s.collected_at or s.collection_date
                    if dt:
                        sample_date = dt.strftime("%Y-%m-%d") if isinstance(dt, datetime) else str(dt)
                        break

            # resolve report availability
            has_report = False
            if hasattr(o, "reports") and o.reports:
                has_report = any(
                    (bool(r.report_path) or str(r.status or "").lower() in ["ready", "approved", "completed", "published"])
                    for r in o.reports
                )

            ord_date = (
                o.ordered_at.strftime("%Y-%m-%d")
                if isinstance(o.ordered_at, datetime)
                else str(o.ordered_at)
                if o.ordered_at
                else None
            )
            comp_date = (
                o.completed_at.strftime("%Y-%m-%d")
                if isinstance(o.completed_at, datetime)
                else str(o.completed_at)
                if o.completed_at
                else None
            )

            test_name = "Lab Test"
            category = None
            if hasattr(o, "lab_test") and o.lab_test:
                test_name = getattr(o.lab_test, "test_name", "Lab Test") or "Lab Test"
                category = getattr(o.lab_test, "category", None)

            history.append(
                LabHistoryResponse(
                    test_order_id=o.id,
                    test_name=test_name,
                    category=category,
                    status=(o.status or "ordered").upper(),
                    ordered_date=ord_date,
                    sample_collected_date=sample_date,
                    completed_date=comp_date,
                    report_available=has_report,
                )
            )

        return history
