from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.clinical_record_model import ClinicalRecord
from app.utils.helpers import utc_now


class ClinicalRecordRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _base_query(self):
        return (
            select(ClinicalRecord)
            .where(ClinicalRecord.is_deleted.is_(False))
            .options(
                selectinload(ClinicalRecord.patient),
                selectinload(ClinicalRecord.doctor)
            )
        )

    async def create(self, record: ClinicalRecord) -> ClinicalRecord:
        self.db.add(record)
        await self.db.flush()
        # Refresh to load relationships
        query = self._base_query().where(ClinicalRecord.id == record.id)
        result = await self.db.execute(query)
        return result.scalar_one()

    async def get_by_id(self, record_id: int) -> ClinicalRecord | None:
        query = self._base_query().where(ClinicalRecord.id == record_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_all(
        self,
        skip: int = 0,
        limit: int = 20,
        patient_id: int | None = None,
        doctor_id: int | None = None,
        appointment_id: int | None = None
    ) -> list[ClinicalRecord]:
        query = self._base_query()
        if patient_id is not None:
            query = query.where(ClinicalRecord.patient_id == patient_id)
        if doctor_id is not None:
            query = query.where(ClinicalRecord.doctor_id == doctor_id)
        if appointment_id is not None:
            query = query.where(ClinicalRecord.appointment_id == appointment_id)
        
        query = query.order_by(ClinicalRecord.created_at.desc())
        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_all(
        self,
        patient_id: int | None = None,
        doctor_id: int | None = None,
        appointment_id: int | None = None
    ) -> int:
        query = select(func.count()).select_from(ClinicalRecord).where(ClinicalRecord.is_deleted.is_(False))
        if patient_id is not None:
            query = query.where(ClinicalRecord.patient_id == patient_id)
        if doctor_id is not None:
            query = query.where(ClinicalRecord.doctor_id == doctor_id)
        if appointment_id is not None:
            query = query.where(ClinicalRecord.appointment_id == appointment_id)
            
        return (await self.db.scalar(query)) or 0

    async def update(self, record: ClinicalRecord) -> ClinicalRecord:
        await self.db.flush()
        # Refresh to load relationships
        query = self._base_query().where(ClinicalRecord.id == record.id)
        result = await self.db.execute(query)
        return result.scalar_one()

    async def soft_delete(self, record: ClinicalRecord) -> None:
        record.is_deleted = True
        record.deleted_at = utc_now()
        await self.db.flush()
