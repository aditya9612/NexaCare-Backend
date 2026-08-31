from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.final_bill_model import IPDFinalBill, IPDFinalBillItem


class FinalBillRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, final_bill_id: int) -> IPDFinalBill | None:
        stmt = (
            select(IPDFinalBill)
            .options(selectinload(IPDFinalBill.items), selectinload(IPDFinalBill.patient))
            .where(IPDFinalBill.id == final_bill_id, IPDFinalBill.is_deleted == False)
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_by_id_with_items(self, final_bill_id: int) -> IPDFinalBill | None:
        return await self.get_by_id(final_bill_id)

    async def get_by_discharge_id_with_items(self, discharge_id: int) -> IPDFinalBill | None:
        stmt = (
            select(IPDFinalBill)
            .options(selectinload(IPDFinalBill.items), selectinload(IPDFinalBill.patient))
            .where(IPDFinalBill.discharge_id == discharge_id, IPDFinalBill.is_deleted == False)
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_by_appointment_id(self, appointment_id: int) -> IPDFinalBill | None:
        stmt = (
            select(IPDFinalBill)
            .options(selectinload(IPDFinalBill.items), selectinload(IPDFinalBill.patient))
            .where(IPDFinalBill.appointment_id == appointment_id, IPDFinalBill.is_deleted == False)
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def list_all_final_bills(
        self,
        skip: int = 0,
        limit: int = 50,
        patient_id: int | None = None,
        status: str | None = None,
    ) -> list[IPDFinalBill]:
        stmt = (
            select(IPDFinalBill)
            .options(selectinload(IPDFinalBill.items), selectinload(IPDFinalBill.patient))
            .where(IPDFinalBill.is_deleted == False)
        )
        if patient_id:
            stmt = stmt.where(IPDFinalBill.patient_id == patient_id)
        if status:
            stmt = stmt.where(IPDFinalBill.status == status)
        stmt = stmt.order_by(IPDFinalBill.id.desc()).offset(skip).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def create(self, final_bill: IPDFinalBill) -> IPDFinalBill:
        self.db.add(final_bill)
        await self.db.flush()
        await self.db.refresh(final_bill)
        return final_bill

    async def update(self, final_bill: IPDFinalBill) -> IPDFinalBill:
        await self.db.flush()
        await self.db.refresh(final_bill)
        return final_bill
