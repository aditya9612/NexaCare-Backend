from datetime import date
from sqlalchemy import func, select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.expense_model import ExpenseCategory, Expense, VendorPayment
from app.models.vendor_model import Vendor
from app.utils.helpers import utc_now


class ExpenseCategoryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _base_query(self):
        return select(ExpenseCategory).where(ExpenseCategory.is_deleted.is_(False))

    async def list_all(self, skip: int = 0, limit: int = 20) -> list[ExpenseCategory]:
        query = self._base_query().order_by(ExpenseCategory.name.asc())
        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_all(self) -> int:
        query = select(func.count()).select_from(ExpenseCategory).where(ExpenseCategory.is_deleted.is_(False))
        return (await self.db.scalar(query)) or 0

    async def get_by_id(self, category_id: int) -> ExpenseCategory | None:
        result = await self.db.execute(self._base_query().where(ExpenseCategory.id == category_id))
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> ExpenseCategory | None:
        result = await self.db.execute(
            self._base_query().where(func.lower(ExpenseCategory.name) == name.lower().strip())
        )
        return result.scalar_one_or_none()

    async def create(self, category: ExpenseCategory) -> ExpenseCategory:
        self.db.add(category)
        await self.db.flush()
        await self.db.refresh(category)
        return category

    async def update(self, category: ExpenseCategory) -> ExpenseCategory:
        await self.db.flush()
        await self.db.refresh(category)
        return category

    async def soft_delete(self, category: ExpenseCategory) -> None:
        category.is_deleted = True
        category.deleted_at = utc_now()
        await self.db.flush()


# --- ExpenseVendorRepository removed (use central VendorRepository instead) ---


class ExpenseRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _base_query(self):
        return select(Expense).where(Expense.is_deleted.is_(False))

    async def list_all(
        self,
        skip: int = 0,
        limit: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        category_id: int | None = None,
        vendor_id: int | None = None,
        status: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        description: str | None = None,
    ) -> list[Expense]:
        query = self._base_query()
        if category_id is not None:
            query = query.where(Expense.category_id == category_id)
        if vendor_id is not None:
            query = query.where(Expense.vendor_id == vendor_id)
        if status is not None:
            query = query.where(func.lower(Expense.status) == status.lower().strip())
        if start_date is not None:
            query = query.where(Expense.expense_date >= start_date)
        if end_date is not None:
            query = query.where(Expense.expense_date <= end_date)
        if description is not None:
            query = query.where(func.lower(Expense.description).like(f"%{description.lower().strip()}%"))

        column = getattr(Expense, sort_by, Expense.created_at)
        query = query.order_by(column.desc() if sort_order == "desc" else column.asc())
        query = query.options(selectinload(Expense.category), selectinload(Expense.vendor))

        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_all(
        self,
        category_id: int | None = None,
        vendor_id: int | None = None,
        status: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        description: str | None = None,
    ) -> int:
        query = select(func.count()).select_from(Expense).where(Expense.is_deleted.is_(False))
        if category_id is not None:
            query = query.where(Expense.category_id == category_id)
        if vendor_id is not None:
            query = query.where(Expense.vendor_id == vendor_id)
        if status is not None:
            query = query.where(func.lower(Expense.status) == status.lower().strip())
        if start_date is not None:
            query = query.where(Expense.expense_date >= start_date)
        if end_date is not None:
            query = query.where(Expense.expense_date <= end_date)
        if description is not None:
            query = query.where(func.lower(Expense.description).like(f"%{description.lower().strip()}%"))

        return (await self.db.scalar(query)) or 0

    async def get_by_id(self, expense_id: int) -> Expense | None:
        query = self._base_query().where(Expense.id == expense_id)
        query = query.options(selectinload(Expense.category), selectinload(Expense.vendor))
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def create(self, expense: Expense) -> Expense:
        self.db.add(expense)
        await self.db.flush()
        # Refresh with loaded relationships
        query = select(Expense).where(Expense.id == expense.id).options(
            selectinload(Expense.category), selectinload(Expense.vendor)
        )
        res = await self.db.execute(query)
        return res.scalar_one()

    async def update(self, expense: Expense) -> Expense:
        await self.db.flush()
        # Refresh with loaded relationships
        query = select(Expense).where(Expense.id == expense.id).options(
            selectinload(Expense.category), selectinload(Expense.vendor)
        )
        res = await self.db.execute(query)
        return res.scalar_one()

    async def soft_delete(self, expense: Expense) -> None:
        expense.is_deleted = True
        expense.deleted_at = utc_now()
        await self.db.flush()

    async def get_summary(
        self,
        start_date: date | None = None,
        end_date: date | None = None
    ) -> dict:
        base_filter = [Expense.is_deleted.is_(False)]
        if start_date is not None:
            base_filter.append(Expense.expense_date >= start_date)
        if end_date is not None:
            base_filter.append(Expense.expense_date <= end_date)

        # Total Amount and Total Count
        total_query = select(
            func.coalesce(func.sum(Expense.amount), 0.0).label("total_amount"),
            func.count(Expense.id).label("total_count")
        ).where(*base_filter)
        total_res = await self.db.execute(total_query)
        total_row = total_res.fetchone()
        total_amount = float(total_row[0]) if total_row and total_row[0] is not None else 0.0
        total_count = int(total_row[1]) if total_row and total_row[1] is not None else 0

        # Category aggregates
        cat_query = select(
            Expense.category_id.label("category_id"),
            ExpenseCategory.name.label("name"),
            func.coalesce(func.sum(Expense.amount), 0.0).label("total_amount"),
            func.count(Expense.id).label("count")
        ).join(
            ExpenseCategory, Expense.category_id == ExpenseCategory.id
        ).where(
            *base_filter
        ).group_by(
            Expense.category_id, ExpenseCategory.name
        )
        cat_res = await self.db.execute(cat_query)
        by_category = [
            {
                "category_id": r.category_id,
                "name": r.name,
                "total_amount": float(r.total_amount),
                "count": int(r.count)
            }
            for r in cat_res.all()
        ]

        # Vendor aggregates
        vendor_query = select(
            Expense.vendor_id.label("vendor_id"),
            Vendor.name.label("name"),
            func.coalesce(func.sum(Expense.amount), 0.0).label("total_amount"),
            func.count(Expense.id).label("count")
        ).outerjoin(
            Vendor, Expense.vendor_id == Vendor.id
        ).where(
            *base_filter
        ).group_by(
            Expense.vendor_id, Vendor.name
        )
        vendor_res = await self.db.execute(vendor_query)
        by_vendor = [
            {
                "vendor_id": r.vendor_id,
                "name": r.name if r.name is not None else "Unknown/Direct",
                "total_amount": float(r.total_amount),
                "count": int(r.count)
            }
            for r in vendor_res.all()
        ]

        # Status aggregates
        status_query = select(
            Expense.status.label("status"),
            func.coalesce(func.sum(Expense.amount), 0.0).label("total_amount"),
            func.count(Expense.id).label("count")
        ).where(
            *base_filter
        ).group_by(
            Expense.status
        )
        status_res = await self.db.execute(status_query)
        by_status = [
            {
                "status": r.status,
                "total_amount": float(r.total_amount),
                "count": int(r.count)
            }
            for r in status_res.all()
        ]

        # Monthly aggregates
        monthly_query = select(
            func.year(Expense.expense_date).label("year"),
            func.month(Expense.expense_date).label("month"),
            func.coalesce(func.sum(Expense.amount), 0.0).label("total_amount"),
            func.count(Expense.id).label("count")
        ).where(
            *base_filter
        ).group_by(
            func.year(Expense.expense_date),
            func.month(Expense.expense_date)
        ).order_by(
            func.year(Expense.expense_date).desc(),
            func.month(Expense.expense_date).desc()
        )
        monthly_res = await self.db.execute(monthly_query)
        monthly_summary = [
            {
                "year": int(r.year),
                "month": int(r.month),
                "total_amount": float(r.total_amount),
                "count": int(r.count)
            }
            for r in monthly_res.all()
        ]

        return {
            "total_amount": total_amount,
            "total_count": total_count,
            "by_category": by_category,
            "by_vendor": by_vendor,
            "by_status": by_status,
            "monthly_summary": monthly_summary
        }


class VendorPaymentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _base_query(self):
        return select(VendorPayment).where(VendorPayment.is_deleted.is_(False))

    async def list_all(
        self, skip: int = 0, limit: int = 20, vendor_id: int | None = None, expense_id: int | None = None
    ) -> list[VendorPayment]:
        query = self._base_query()
        if vendor_id is not None:
            query = query.where(VendorPayment.vendor_id == vendor_id)
        if expense_id is not None:
            query = query.where(VendorPayment.expense_id == expense_id)
        result = await self.db.execute(
            query.order_by(VendorPayment.payment_date.desc()).offset(skip).limit(limit)
        )
        return list(result.scalars().all())

    async def count_all(self, vendor_id: int | None = None, expense_id: int | None = None) -> int:
        query = select(func.count()).select_from(VendorPayment).where(VendorPayment.is_deleted.is_(False))
        if vendor_id is not None:
            query = query.where(VendorPayment.vendor_id == vendor_id)
        if expense_id is not None:
            query = query.where(VendorPayment.expense_id == expense_id)
        return (await self.db.scalar(query)) or 0

    async def get_by_id(self, payment_id: int) -> VendorPayment | None:
        result = await self.db.execute(self._base_query().where(VendorPayment.id == payment_id))
        return result.scalar_one_or_none()

    async def get_payments_by_expense(self, expense_id: int) -> list[VendorPayment]:
        result = await self.db.execute(
            self._base_query().where(VendorPayment.expense_id == expense_id)
        )
        return list(result.scalars().all())

    async def create(self, payment: VendorPayment) -> VendorPayment:
        self.db.add(payment)
        await self.db.flush()
        await self.db.refresh(payment)
        return payment

    async def update(self, payment: VendorPayment) -> VendorPayment:
        await self.db.flush()
        await self.db.refresh(payment)
        return payment

    async def soft_delete(self, payment: VendorPayment) -> None:
        payment.is_deleted = True
        payment.deleted_at = utc_now()
        await self.db.flush()
