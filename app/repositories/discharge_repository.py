from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.bed_allocation_model import Bed
from app.models.discharge_model import Discharge


class DischargeRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, discharge_id: int) -> Discharge | None:
        query = (
            select(Discharge)
            .where(Discharge.id == discharge_id)
            .options(
                selectinload(Discharge.appointment),
                selectinload(Discharge.patient),
                selectinload(Discharge.doctor),
                selectinload(Discharge.bed).selectinload(Bed.room),
                selectinload(Discharge.billing),
            )
        )
        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_by_appointment_id(self, appointment_id: int) -> Discharge | None:
        query = (
            select(Discharge)
            .where(Discharge.appointment_id == appointment_id)
            .order_by(desc(Discharge.id))
            .options(
                selectinload(Discharge.appointment),
                selectinload(Discharge.patient),
                selectinload(Discharge.doctor),
                selectinload(Discharge.bed).selectinload(Bed.room),
                selectinload(Discharge.billing),
            )
        )
        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_all_active(self) -> list[Discharge]:
        query = (
            select(Discharge)
            .where(Discharge.discharge_status.in_(["PENDING_CLEARANCES", "CLEARED"]))
            .order_by(desc(Discharge.updated_at))
            .options(
                selectinload(Discharge.appointment),
                selectinload(Discharge.patient),
                selectinload(Discharge.doctor),
                selectinload(Discharge.bed).selectinload(Bed.room),
            )
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def create(self, discharge: Discharge) -> Discharge:
        self.db.add(discharge)
        await self.db.flush()
        await self.db.refresh(discharge)
        return discharge

    async def update(self, discharge: Discharge) -> Discharge:
        await self.db.flush()
        await self.db.refresh(discharge)
        return discharge
