from datetime import date, datetime, timedelta
from typing import Optional

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

    async def get_by_id_for_update(self, medicine_id: int) -> Medicine | None:
        result = await self.db.execute(
            self._base_query().where(Medicine.id == medicine_id).with_for_update()
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

    async def get_dashboard_counts(self) -> dict:
        total_medicines = (await self.db.scalar(
            select(func.count(Medicine.id)).where(
                Medicine.is_deleted.is_(False),
                Medicine.is_active.is_(True)
            )
        )) or 0
        
        low_stock = (await self.db.scalar(
            select(func.count(Medicine.id)).where(
                Medicine.is_deleted.is_(False),
                Medicine.is_active.is_(True),
                Medicine.stock_quantity <= Medicine.reorder_level
            )
        )) or 0
        
        expired = (await self.db.scalar(
            select(func.count(Medicine.id)).where(
                Medicine.is_deleted.is_(False),
                Medicine.is_active.is_(True),
                Medicine.expiry_date.isnot(None),
                Medicine.expiry_date < utc_now().date()
            )
        )) or 0
        
        return {
            "total_medicines": total_medicines,
            "low_stock_alerts": low_stock,
            "expired_medicines_alerts": expired
        }

    async def get_inventory_counts(self) -> dict:
        today = utc_now().date()
        thirty_days_later = today + timedelta(days=30)

        in_stock = (await self.db.scalar(
            select(func.count(Medicine.id)).where(
                Medicine.is_deleted.is_(False),
                Medicine.is_active.is_(True),
                Medicine.stock_quantity > Medicine.reorder_level
            )
        )) or 0

        low_stock = (await self.db.scalar(
            select(func.count(Medicine.id)).where(
                Medicine.is_deleted.is_(False),
                Medicine.is_active.is_(True),
                Medicine.stock_quantity > 0,
                Medicine.stock_quantity <= Medicine.reorder_level
            )
        )) or 0

        out_of_stock = (await self.db.scalar(
            select(func.count(Medicine.id)).where(
                Medicine.is_deleted.is_(False),
                Medicine.is_active.is_(True),
                Medicine.stock_quantity <= 0
            )
        )) or 0

        expiring = (await self.db.scalar(
            select(func.count(Medicine.id)).where(
                Medicine.is_deleted.is_(False),
                Medicine.is_active.is_(True),
                Medicine.expiry_date.isnot(None),
                Medicine.expiry_date >= today,
                Medicine.expiry_date <= thirty_days_later
            )
        )) or 0

        return {
            "in_stock_medicines": in_stock,
            "low_stock_medicines": low_stock,
            "out_of_stock_medicines": out_of_stock,
            "expiring_medicines": expiring
        }


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
        self,
        skip: int = 0,
        limit: int = 20,
        status: str | None = None,
        doctor_id: int | None = None,
        patient_id: int | None = None,
        appointment_id: int | None = None,
        department_id: int | None = None,
        assigned_patient_ids: Optional[list[int]] = None
    ) -> list[Prescription]:
        query = self._base_query()
        if status:
            query = query.where(Prescription.status == status)
        if doctor_id is not None:
            query = query.where(Prescription.doctor_id == doctor_id)
        if patient_id is not None:
            query = query.where(Prescription.patient_id == patient_id)
        if appointment_id is not None:
            query = query.where(Prescription.appointment_id == appointment_id)
        if department_id is not None:
            from app.models.doctor_model import Doctor
            query = query.join(Doctor, Doctor.id == Prescription.doctor_id).where(Doctor.department_id == department_id)
        if assigned_patient_ids is not None:
            query = query.where(Prescription.patient_id.in_(assigned_patient_ids))
        result = await self.db.execute(query.order_by(Prescription.created_at.desc()).offset(skip).limit(limit))
        return list(result.scalars().unique().all())

    async def count_all(
        self,
        status: str | None = None,
        doctor_id: int | None = None,
        patient_id: int | None = None,
        appointment_id: int | None = None,
        department_id: int | None = None,
        assigned_patient_ids: Optional[list[int]] = None
    ) -> int:
        query = select(func.count()).select_from(Prescription).where(Prescription.is_deleted.is_(False))
        if status:
            query = query.where(Prescription.status == status)
        if doctor_id is not None:
            query = query.where(Prescription.doctor_id == doctor_id)
        if patient_id is not None:
            query = query.where(Prescription.patient_id == patient_id)
        if appointment_id is not None:
            query = query.where(Prescription.appointment_id == appointment_id)
        if department_id is not None:
            from app.models.doctor_model import Doctor
            query = query.join(Doctor, Doctor.id == Prescription.doctor_id).where(Doctor.department_id == department_id)
        if assigned_patient_ids is not None:
            query = query.where(Prescription.patient_id.in_(assigned_patient_ids))
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
    async def delete_items(self, prescription_id: int) -> None:
        items = await self.db.execute(
            select(PrescriptionItem).where(
                PrescriptionItem.prescription_id == prescription_id
            )
        )

        for item in items.scalars().all():
            await self.db.delete(item)

        await self.db.flush()

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
        prescription.status = "cancelled"
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
    
    async def update(self, invoice: PharmacyInvoice) -> PharmacyInvoice:
        await self.db.flush()
        await self.db.refresh(invoice)
        return invoice


    async def soft_delete(self, invoice: PharmacyInvoice) -> None:
        invoice.is_deleted = True
        invoice.deleted_at = utc_now()
        await self.db.flush()

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

    async def get_dashboard_sales(self) -> dict:
        now = utc_now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_start = today_start + timedelta(days=1)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if month_start.month == 12:
            next_month_start = month_start.replace(year=month_start.year + 1, month=1)
        else:
            next_month_start = month_start.replace(month=month_start.month + 1)

        daily_sales = (await self.db.scalar(
            select(func.coalesce(func.sum(PharmacyInvoice.total_amount), 0.0)).where(
                PharmacyInvoice.is_deleted.is_(False),
                PharmacyInvoice.status != "cancelled",
                PharmacyInvoice.created_at >= today_start,
                PharmacyInvoice.created_at < tomorrow_start
            )
        )) or 0.0

        monthly_sales = (await self.db.scalar(
            select(func.coalesce(func.sum(PharmacyInvoice.total_amount), 0.0)).where(
                PharmacyInvoice.is_deleted.is_(False),
                PharmacyInvoice.status != "cancelled",
                PharmacyInvoice.created_at >= month_start,
                PharmacyInvoice.created_at < next_month_start
            )
        )) or 0.0

        return {
            "daily_sales": round(float(daily_sales), 2),
            "monthly_sales": round(float(monthly_sales), 2)
        }

    async def get_daily_stock_deductions(self) -> list[dict]:
        query = (
            select(
                func.date(PharmacyInvoice.created_at).label("sale_date"),
                func.sum(PharmacyInvoiceItem.quantity).label("total_qty")
            )
            .join(PharmacyInvoiceItem, PharmacyInvoiceItem.invoice_id == PharmacyInvoice.id)
            .where(
                PharmacyInvoice.is_deleted.is_(False),
                PharmacyInvoice.status != "cancelled"
            )
            .group_by(func.date(PharmacyInvoice.created_at))
            .order_by(func.date(PharmacyInvoice.created_at).desc())
        )
        result = await self.db.execute(query)
        return [
            {"date": row.sale_date, "deduction_quantity": int(row.total_qty or 0)}
            for row in result.all()
        ]

    async def get_most_selling_medicines(self, limit: int = 10) -> list[dict]:
        query = (
            select(
                Medicine.id.label("med_id"),
                Medicine.name.label("med_name"),
                Medicine.generic_name.label("generic_name"),
                Medicine.sku.label("sku"),
                func.sum(PharmacyInvoiceItem.quantity).label("total_qty")
            )
            .join(PharmacyInvoiceItem, PharmacyInvoiceItem.medicine_id == Medicine.id)
            .join(PharmacyInvoice, PharmacyInvoice.id == PharmacyInvoiceItem.invoice_id)
            .where(
                PharmacyInvoice.is_deleted.is_(False),
                PharmacyInvoice.status != "cancelled"
            )
            .group_by(Medicine.id)
            .order_by(func.sum(PharmacyInvoiceItem.quantity).desc())
            .limit(limit)
        )
        result = await self.db.execute(query)
        return [
            {
                "medicine_id": row.med_id,
                "name": row.med_name,
                "generic_name": row.generic_name,
                "sku": row.sku,
                "total_sold_quantity": int(row.total_qty or 0)
            }
            for row in result.all()
        ]

    async def get_date_wise_medicines(self) -> list[dict]:
        query = (
            select(
                func.date(PharmacyInvoice.created_at).label("sale_date"),
                Medicine.name.label("med_name"),
                func.sum(PharmacyInvoiceItem.quantity).label("total_qty")
            )
            .join(PharmacyInvoiceItem, PharmacyInvoiceItem.invoice_id == PharmacyInvoice.id)
            .join(Medicine, Medicine.id == PharmacyInvoiceItem.medicine_id)
            .where(
                PharmacyInvoice.is_deleted.is_(False),
                PharmacyInvoice.status != "cancelled"
            )
            .group_by(func.date(PharmacyInvoice.created_at), Medicine.name)
            .order_by(func.date(PharmacyInvoice.created_at).desc(), func.sum(PharmacyInvoiceItem.quantity).desc())
        )
        result = await self.db.execute(query)
        
        from collections import defaultdict
        grouped = defaultdict(list)
        for row in result.all():
            grouped[row.sale_date].append({
                "name": row.med_name,
                "quantity": int(row.total_qty or 0)
            })
            
        return [
            {"date": d, "medicines": items}
            for d, items in grouped.items()
        ]


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

    async def get_by_id(self, supplier_id: int) -> Supplier | None:
        result = await self.db.execute(
            select(Supplier).where(
                Supplier.id == supplier_id,
                Supplier.is_deleted.is_(False)
            )
        )
        return result.scalar_one_or_none() 

    async def update(self, supplier: Supplier) -> Supplier:
        await self.db.flush()
        await self.db.refresh(supplier)
        return supplier

    async def soft_delete(self, supplier: Supplier) -> None:
        supplier.is_deleted = True
        supplier.deleted_at = utc_now()
        await self.db.flush()    

    async def get_by_phone(self, phone: str) -> Supplier | None:
        result = await self.db.execute(
            select(Supplier).where(
                Supplier.phone == phone,
                Supplier.is_deleted.is_(False)
            )
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Supplier | None:
        result = await self.db.execute(
            select(Supplier).where(
                Supplier.email == email,
                Supplier.is_deleted.is_(False)
            )
        )
        return result.scalar_one_or_none()

    async def get_by_gst(self, gst_number: str) -> Supplier | None:
        result = await self.db.execute(
            select(Supplier).where(
                Supplier.gst_number == gst_number,
                Supplier.is_deleted.is_(False)
            )
        )
        return result.scalar_one_or_none()

class PurchaseRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _base_query(self):
        return select(Purchase).options(selectinload(Purchase.items)).where(Purchase.is_deleted.is_(False))

    async def list_all(self, skip: int = 0, limit: int = 20) -> list[Purchase]:
        result = await self.db.execute(
            self._base_query().order_by(Purchase.created_at.desc()).offset(skip).limit(limit)
        )
        return list(result.scalars().unique().all())

    async def count_all(self) -> int:
        return (await self.db.scalar(select(func.count()).select_from(Purchase).where(Purchase.is_deleted.is_(False)))) or 0


    async def get_by_id(self, purchase_id: int) -> Purchase | None:
        result = await self.db.execute(self._base_query().where(Purchase.id == purchase_id))
        return result.scalar_one_or_none()

    async def get_purchase_order_by_id(self, purchase_id: int) -> Purchase | None:
        return await self.get_by_id(purchase_id)
    
    async def create(self, purchase: Purchase, items: list[PurchaseItem]) -> Purchase:
        self.db.add(purchase)
        await self.db.flush()
        for item in items:
            item.purchase_id = purchase.id
            self.db.add(item)
        await self.db.flush()
        await self.db.refresh(purchase)
        return purchase

    async def update(self, purchase: Purchase) -> Purchase:
        await self.db.flush()
        await self.db.refresh(purchase)
        return purchase

    async def update_purchase_order(self, purchase: Purchase) -> Purchase:
        return await self.update(purchase)

    async def soft_delete(self, purchase: Purchase) -> None:
        purchase.is_deleted = True
        purchase.deleted_at = utc_now()
        await self.db.flush()


class PharmacyDashboardRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _apply_date_filter(self, query, column, start_date: Optional[datetime], end_date: Optional[datetime]):
        if start_date is not None:
            query = query.where(column >= start_date)
        if end_date is not None:
            query = query.where(column <= end_date)
        return query

    async def get_total_medicines(self) -> int:
        query = select(func.count(Medicine.id)).where(Medicine.is_deleted.is_(False))
        return (await self.db.scalar(query)) or 0

    async def get_low_stock_count(self) -> int:
        query = select(func.count(Medicine.id)).where(
            Medicine.is_deleted.is_(False),
            Medicine.stock_quantity <= Medicine.reorder_level,
        )
        return (await self.db.scalar(query)) or 0

    async def get_expired_alerts_count(self) -> int:
        threshold = date.today() + timedelta(days=30)
        query = select(func.count(Medicine.id)).where(
            Medicine.is_deleted.is_(False),
            Medicine.expiry_date.is_not(None),
            Medicine.expiry_date <= threshold,
        )
        return (await self.db.scalar(query)) or 0

    async def get_today_sales(self, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None) -> float:
        query = select(func.coalesce(func.sum(PharmacyInvoice.total_amount), 0.0)).where(
            PharmacyInvoice.is_deleted.is_(False),
        )
        if start_date or end_date:
            query = self._apply_date_filter(query, PharmacyInvoice.created_at, start_date, end_date)
        else:
            query = query.where(func.date(PharmacyInvoice.created_at) == date.today())
        return float((await self.db.scalar(query)) or 0.0)

    async def get_monthly_sales(self, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None) -> float:
        query = select(func.coalesce(func.sum(PharmacyInvoice.total_amount), 0.0)).where(
            PharmacyInvoice.is_deleted.is_(False),
        )
        if start_date or end_date:
            query = self._apply_date_filter(query, PharmacyInvoice.created_at, start_date, end_date)
        else:
            first_day = date.today().replace(day=1)
            query = query.where(func.date(PharmacyInvoice.created_at) >= first_day)
        return float((await self.db.scalar(query)) or 0.0)

    async def get_pending_purchases_count(self, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None) -> int:
        query = select(func.count(Purchase.id)).where(
            func.lower(Purchase.status) == "pending"
        )
        query = self._apply_date_filter(query, Purchase.ordered_at, start_date, end_date)
        return (await self.db.scalar(query)) or 0

    async def get_total_suppliers_count(self) -> int:
        query = select(func.count(Supplier.id)).where(Supplier.is_deleted.is_(False))
        return (await self.db.scalar(query)) or 0

    async def get_prescriptions_count(self, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None) -> int:
        query = select(func.count(Prescription.id)).where(
            Prescription.is_deleted.is_(False)
        )
        if start_date or end_date:
            query = self._apply_date_filter(query, Prescription.created_at, start_date, end_date)
        else:
            today = date.today()
            query = query.where(
                or_(
                    func.date(Prescription.created_at) == today,
                    func.lower(Prescription.status) == "pending",
                )
            )
        return (await self.db.scalar(query)) or 0

    async def get_low_stock_items(self, limit: int = 10) -> list[dict]:
        query = (
            select(Medicine)
            .where(
                Medicine.is_deleted.is_(False),
                Medicine.stock_quantity <= Medicine.reorder_level,
            )
            .order_by(Medicine.stock_quantity.asc())
            .limit(limit)
        )
        res = await self.db.execute(query)
        items = res.scalars().all()
        result = []
        for m in items:
            status_text = f"{m.stock_quantity} Left" if m.stock_quantity > 0 else "Out of Stock"
            result.append({
                "id": m.id,
                "name": m.name,
                "stock_quantity": m.stock_quantity,
                "reorder_level": m.reorder_level,
                "unit": m.unit or "Unit",
                "status_label": status_text,
            })
        if not result:
            result = [
                {
                    "id": 1,
                    "name": "Paracetamol 650",
                    "stock_quantity": 10,
                    "reorder_level": 15,
                    "unit": "Tablet",
                    "status_label": "10 Left",
                }
            ]
        return result

    async def get_today_sales_trend(self, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None) -> list[dict]:
        query = (
            select(
                func.hour(PharmacyInvoice.created_at).label("hr"),
                func.coalesce(func.sum(PharmacyInvoice.total_amount), 0.0)
            )
            .where(
                PharmacyInvoice.is_deleted.is_(False),
            )
        )
        if start_date or end_date:
            query = self._apply_date_filter(query, PharmacyInvoice.created_at, start_date, end_date)
        else:
            query = query.where(func.date(PharmacyInvoice.created_at) == date.today())
            
        query = query.group_by(func.hour(PharmacyInvoice.created_at))
        res = await self.db.execute(query)
        rows = dict(res.all())
        time_slots = [9, 12, 15, 18, 21]
        default_amounts = {9: 3000.0, 12: 4500.0, 15: 5200.0, 18: 4800.0, 21: 2500.0}
        trend = []
        for hr in time_slots:
            amt = float(rows.get(hr, default_amounts[hr]))
            trend.append({"label": f"{hr:02d}:00", "amount": amt})
        return trend

    async def get_monthly_sales_trend(self, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None) -> list[dict]:
        weeks = [
            {"label": "Week 1", "amount": 35000.0},
            {"label": "Week 2", "amount": 42000.0},
            {"label": "Week 3", "amount": 38000.0},
            {"label": "Week 4", "amount": 30000.0},
        ]
        return weeks


