from datetime import date, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.pharmacy_model import (
    Medicine,
    PharmacyInvoice,
    PharmacyInvoiceItem,
    Prescription,
    PrescriptionItem,
    Purchase,
    PurchaseItem,
    Supplier,
)
from app.utils.helpers import utc_now


class MedicineRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _base_query(self):
        return select(Medicine).where(Medicine.is_deleted.is_(False))

    async def list_all(
        self, skip: int = 0, limit: int = 20, sort_by: str = "created_at",
        sort_order: str = "desc", category: str | None = None,
    ) -> list[Medicine]:
        query = self._base_query()
        if category:
            query = query.where(Medicine.category == category)
        column = getattr(Medicine, sort_by, Medicine.created_at)
        query = query.order_by(column.desc() if sort_order == "desc" else column.asc())
        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_all(self, category: str | None = None) -> int:
        query = select(func.count()).select_from(Medicine).where(Medicine.is_deleted.is_(False))
        if category:
            query = query.where(Medicine.category == category)
        return (await self.db.scalar(query)) or 0

    async def search(self, q: str, skip: int = 0, limit: int = 20) -> list[Medicine]:
        pattern = f"%{q.lower()}%"
        query = self._base_query().where(
            or_(
                func.lower(Medicine.name).like(pattern),
                func.lower(Medicine.sku).like(pattern),
                func.lower(Medicine.generic_name).like(pattern),
                func.lower(Medicine.barcode).like(pattern),
            )
        )
        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_search(self, q: str) -> int:
        pattern = f"%{q.lower()}%"
        result = await self.db.scalar(
            select(func.count()).select_from(Medicine).where(
                Medicine.is_deleted.is_(False),
                or_(
                    func.lower(Medicine.name).like(pattern),
                    func.lower(Medicine.sku).like(pattern),
                    func.lower(Medicine.generic_name).like(pattern),
                ),
            )
        )
        return result or 0

    async def get_by_id(self, medicine_id: int) -> Medicine | None:
        result = await self.db.execute(
            self._base_query().where(Medicine.id == medicine_id)
        )
        return result.scalar_one_or_none()

    async def get_by_barcode(self, barcode: str) -> Medicine | None:
        result = await self.db.execute(
            self._base_query().where(Medicine.barcode == barcode)
        )
        return result.scalar_one_or_none()

    async def create(self, medicine: Medicine) -> Medicine:
        self.db.add(medicine)
        await self.db.flush()
        await self.db.refresh(medicine)
        return medicine

    async def update(self, medicine: Medicine) -> Medicine:
        await self.db.flush()
        await self.db.refresh(medicine)
        return medicine

    async def soft_delete(self, medicine: Medicine) -> None:
        medicine.is_deleted = True
        medicine.deleted_at = utc_now()
        await self.db.flush()

    async def update_stock(self, medicine_id: int, delta: int) -> Medicine | None:
        medicine = await self.get_by_id(medicine_id)
        if medicine:
            medicine.stock_quantity = max(0, medicine.stock_quantity + delta)
            await self.db.flush()
            await self.db.refresh(medicine)
        return medicine

    async def get_low_stock(self, skip: int = 0, limit: int = 50) -> list[Medicine]:
        query = self._base_query().where(
            Medicine.stock_quantity <= Medicine.reorder_level, Medicine.is_active.is_(True)
        )
        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all())

    async def get_expiry_alerts(self, days: int = 30, skip: int = 0, limit: int = 50) -> list[Medicine]:
        threshold = date.today() + timedelta(days=days)
        query = self._base_query().where(
            Medicine.expiry_date.isnot(None),
            Medicine.expiry_date <= threshold,
            Medicine.stock_quantity > 0,
        )
        result = await self.db.execute(query.order_by(Medicine.expiry_date.asc()).offset(skip).limit(limit))
        return list(result.scalars().all())


class PrescriptionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _base_query(self):
        return (
            select(Prescription)
            .where(Prescription.is_deleted.is_(False))
            .options(selectinload(Prescription.items))
        )

    async def list_all(
        self, skip: int = 0, limit: int = 20, status: str | None = None, doctor_id: int | None = None
    ) -> list[Prescription]:
        query = self._base_query()
        if status:
            query = query.where(Prescription.status == status)
        if doctor_id is not None:
            query = query.where(Prescription.doctor_id == doctor_id)
        result = await self.db.execute(query.order_by(Prescription.created_at.desc()).offset(skip).limit(limit))
        return list(result.scalars().unique().all())

    async def count_all(self, status: str | None = None, doctor_id: int | None = None) -> int:
        query = select(func.count()).select_from(Prescription).where(Prescription.is_deleted.is_(False))
        if status:
            query = query.where(Prescription.status == status)
        if doctor_id is not None:
            query = query.where(Prescription.doctor_id == doctor_id)
        return (await self.db.scalar(query)) or 0

    async def get_by_id(self, prescription_id: int) -> Prescription | None:
        result = await self.db.execute(self._base_query().where(Prescription.id == prescription_id))
        return result.scalar_one_or_none()

    async def create(self, prescription: Prescription, items: list[PrescriptionItem]) -> Prescription:
        self.db.add(prescription)
        await self.db.flush()
        for item in items:
            item.prescription_id = prescription.id
            self.db.add(item)
        await self.db.flush()
        await self.db.refresh(prescription)
        return prescription

    async def update(self, prescription: Prescription, items: list[PrescriptionItem] | None = None) -> Prescription:
        await self.db.flush()
        if items is not None:
            prescription.items.clear()
            for item in items:
                item.prescription_id = prescription.id
                self.db.add(item)
            await self.db.flush()
        await self.db.refresh(prescription)
        return prescription

    async def soft_delete(self, prescription: Prescription) -> None:
        prescription.is_deleted = True
        prescription.deleted_at = utc_now()
        await self.db.flush()


class PharmacyInvoiceRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _base_query(self):
        return (
            select(PharmacyInvoice)
            .where(PharmacyInvoice.is_deleted.is_(False))
            .options(selectinload(PharmacyInvoice.items))
        )

    async def list_all(self, skip: int = 0, limit: int = 20) -> list[PharmacyInvoice]:
        result = await self.db.execute(
            self._base_query().order_by(PharmacyInvoice.created_at.desc()).offset(skip).limit(limit)
        )
        return list(result.scalars().unique().all())

    async def count_all(self) -> int:
        return (await self.db.scalar(
            select(func.count()).select_from(PharmacyInvoice).where(PharmacyInvoice.is_deleted.is_(False))
        )) or 0

    async def get_by_id(self, invoice_id: int) -> PharmacyInvoice | None:
        result = await self.db.execute(self._base_query().where(PharmacyInvoice.id == invoice_id))
        return result.scalar_one_or_none()

    async def create(self, invoice: PharmacyInvoice, items: list[PharmacyInvoiceItem]) -> PharmacyInvoice:
        self.db.add(invoice)
        await self.db.flush()
        for item in items:
            item.invoice_id = invoice.id
            self.db.add(item)
        await self.db.flush()
        result = await self.db.execute(self._base_query().where(PharmacyInvoice.id == invoice.id))
        return result.scalar_one()

    async def get_sales_report(self, start, end) -> dict:
        total = await self.db.scalar(
            select(func.coalesce(func.sum(PharmacyInvoice.total_amount), 0)).where(
                PharmacyInvoice.is_deleted.is_(False),
                PharmacyInvoice.created_at >= start,
                PharmacyInvoice.created_at <= end,
            )
        )
        count = await self.db.scalar(
            select(func.count()).select_from(PharmacyInvoice).where(
                PharmacyInvoice.is_deleted.is_(False),
                PharmacyInvoice.created_at >= start,
                PharmacyInvoice.created_at <= end,
            )
        )
        return {"total_sales": float(total or 0), "invoice_count": count or 0}


class SupplierRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all(self, skip: int = 0, limit: int = 20) -> list[Supplier]:
        result = await self.db.execute(
            select(Supplier).where(Supplier.is_deleted.is_(False)).offset(skip).limit(limit)
        )
        return list(result.scalars().all())

    async def count_all(self) -> int:
        return (await self.db.scalar(
            select(func.count()).select_from(Supplier).where(Supplier.is_deleted.is_(False))
        )) or 0

    async def create(self, supplier: Supplier) -> Supplier:
        self.db.add(supplier)
        await self.db.flush()
        await self.db.refresh(supplier)
        return supplier


class PurchaseRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _base_query(self):
        return select(Purchase).options(selectinload(Purchase.items))

    async def list_all(self, skip: int = 0, limit: int = 20) -> list[Purchase]:
        result = await self.db.execute(
            self._base_query().order_by(Purchase.created_at.desc()).offset(skip).limit(limit)
        )
        return list(result.scalars().unique().all())

    async def count_all(self) -> int:
        return (await self.db.scalar(select(func.count()).select_from(Purchase))) or 0

    async def get_by_id(self, purchase_id: int) -> Purchase | None:
        result = await self.db.execute(self._base_query().where(Purchase.id == purchase_id))
        return result.scalar_one_or_none()

    async def create(self, purchase: Purchase, items: list[PurchaseItem]) -> Purchase:
        self.db.add(purchase)
        await self.db.flush()
        for item in items:
            item.purchase_id = purchase.id
            self.db.add(item)
        await self.db.flush()
        await self.db.refresh(purchase)
        return purchase
