from datetime import date, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.billing_model import Billing, BillItem, Insurance, InsuranceClaim, Payment
from app.utils.helpers import utc_now


class BillingRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _base_query(self):
        return (
            select(Billing)
            .where(Billing.is_deleted.is_(False))
            .options(selectinload(Billing.items), selectinload(Billing.payments))
        )

    async def list_all(
        self,
        skip: int = 0,
        limit: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        status: str | None = None,
        patient_id: int | None = None,
        bill_type: str | None = None,
    ) -> list[Billing]:
        query = self._base_query()
        if status:
            query = query.where(Billing.status == status)
        if patient_id:
            query = query.where(Billing.patient_id == patient_id)
        if bill_type:
            bt_val = bill_type.value if hasattr(bill_type, "value") else str(bill_type).lower().strip()
            if bt_val == "pharmacy":
                query = query.where(func.lower(Billing.bill_number).like("rec%"))
            elif bt_val == "consultation":
                query = query.where(
                    or_(
                        func.lower(Billing.bill_number).like("bill%"),
                        func.lower(Billing.bill_number).like("bil%"),
                    )
                )
        column = getattr(Billing, sort_by, Billing.created_at)
        query = query.order_by(column.desc() if sort_order == "desc" else column.asc())
        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().unique().all())

    async def count_all(
        self,
        status: str | None = None,
        patient_id: int | None = None,
        bill_type: str | None = None,
    ) -> int:
        query = select(func.count()).select_from(Billing).where(Billing.is_deleted.is_(False))
        if status:
            query = query.where(Billing.status == status)
        if patient_id:
            query = query.where(Billing.patient_id == patient_id)
        if bill_type:
            bt_val = bill_type.value if hasattr(bill_type, "value") else str(bill_type).lower().strip()
            if bt_val == "pharmacy":
                query = query.where(func.lower(Billing.bill_number).like("rec%"))
            elif bt_val == "consultation":
                query = query.where(
                    or_(
                        func.lower(Billing.bill_number).like("bill%"),
                        func.lower(Billing.bill_number).like("bil%"),
                    )
                )
        result = await self.db.scalar(query)
        return result or 0

    async def search(
        self,
        q: str,
        skip: int = 0,
        limit: int = 20,
        status: str | None = None,
        bill_type: str | None = None,
    ) -> list[Billing]:
        pattern = f"%{q.lower()}%"
        query = self._base_query().where(
            or_(
                func.lower(Billing.bill_number).like(pattern),
                func.lower(Billing.notes).like(pattern),
            )
        )
        if status:
            query = query.where(Billing.status == status)
        if bill_type:
            bt_val = bill_type.value if hasattr(bill_type, "value") else str(bill_type).lower().strip()
            if bt_val == "pharmacy":
                query = query.where(func.lower(Billing.bill_number).like("rec%"))
            elif bt_val == "consultation":
                query = query.where(
                    or_(
                        func.lower(Billing.bill_number).like("bill%"),
                        func.lower(Billing.bill_number).like("bil%"),
                    )
                )
        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().unique().all())

    async def count_search(
        self,
        q: str,
        status: str | None = None,
        bill_type: str | None = None,
    ) -> int:
        pattern = f"%{q.lower()}%"
        query = (
            select(func.count())
            .select_from(Billing)
            .where(
                Billing.is_deleted.is_(False),
                or_(
                    func.lower(Billing.bill_number).like(pattern),
                    func.lower(Billing.notes).like(pattern),
                ),
            )
        )
        if status:
            query = query.where(Billing.status == status)
        if bill_type:
            bt_val = bill_type.value if hasattr(bill_type, "value") else str(bill_type).lower().strip()
            if bt_val == "pharmacy":
                query = query.where(func.lower(Billing.bill_number).like("rec%"))
            elif bt_val == "consultation":
                query = query.where(
                    or_(
                        func.lower(Billing.bill_number).like("bill%"),
                        func.lower(Billing.bill_number).like("bil%"),
                    )
                )
        result = await self.db.scalar(query)
        return result or 0

    async def get_by_id(self, billing_id: int) -> Billing | None:
        result = await self.db.execute(self._base_query().where(Billing.id == billing_id))
        return result.scalar_one_or_none()

    async def get_by_id_for_update(self, billing_id: int) -> Billing | None:
        result = await self.db.execute(
            self._base_query().where(Billing.id == billing_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_by_patient_and_appointment(
        self,
        patient_id: int,
        appointment_id: int,
    ) -> Billing | None:
        result = await self.db.execute(
            self._base_query().where(
                Billing.patient_id == patient_id,
                Billing.appointment_id == appointment_id,
            )
        )
        return result.scalars().first()

    async def create(self, billing: Billing) -> Billing:
        self.db.add(billing)
        await self.db.flush()
        await self.db.refresh(billing)
        return billing

    async def update(self, billing: Billing) -> Billing:
        await self.db.flush()
        await self.db.refresh(billing)
        return billing

    async def soft_delete(self, billing: Billing) -> None:
        billing.is_deleted = True
        billing.deleted_at = utc_now()
        await self.db.flush()

    async def add_item(self, item: BillItem) -> BillItem:
        self.db.add(item)
        await self.db.flush()
        await self.db.refresh(item)
        return item

    async def add_payment(self, payment: Payment) -> Payment:
        self.db.add(payment)
        await self.db.flush()
        await self.db.refresh(payment)
        return payment

    async def get_pending_payments(self, skip: int = 0, limit: int = 20) -> list[Billing]:
        query = self._base_query().where(Billing.balance_amount > 0, Billing.status != "cancelled")
        result = await self.db.execute(
            query.order_by(Billing.due_date.asc()).offset(skip).limit(limit)
        )
        return list(result.scalars().unique().all())

    async def count_pending_payments(self) -> int:
        result = await self.db.scalar(
            select(func.count())
            .select_from(Billing)
            .where(
                Billing.is_deleted.is_(False),
                Billing.balance_amount > 0,
                Billing.status != "cancelled",
            )
        )
        return result or 0

    async def get_revenue_summary(self) -> dict:
        billed = await self.db.scalar(
            select(func.coalesce(func.sum(Billing.total_amount), 0)).where(Billing.is_deleted.is_(False))
        )
        collected = await self.db.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.is_refund.is_(False), Payment.status == "completed"
            )
        )
        pending = await self.db.scalar(
            select(func.coalesce(func.sum(Billing.balance_amount), 0)).where(
                Billing.is_deleted.is_(False), Billing.balance_amount > 0
            )
        )
        overdue = await self.db.scalar(
            select(func.count())
            .select_from(Billing)
            .where(Billing.is_deleted.is_(False), Billing.status == "overdue")
        )
        pending_count = await self.db.scalar(
            select(func.count())
            .select_from(Billing)
            .where(Billing.is_deleted.is_(False), Billing.balance_amount > 0)
        )
        return {
            "total_revenue": float(collected or 0),
            "total_pending": float(pending or 0),
            "total_paid": float(collected or 0),
            "total_billed": float(billed or 0),
            "overdue_count": overdue or 0,
            "pending_count": pending_count or 0,
        }

    async def get_daily_collection(self, target_date: date) -> dict:
        start = datetime.combine(target_date, datetime.min.time())
        end = datetime.combine(target_date, datetime.max.time())
        result = await self.db.execute(
            select(Payment.payment_method, func.sum(Payment.amount))
            .where(
                Payment.is_refund.is_(False),
                Payment.status == "completed",
                Payment.payment_date >= start,
                Payment.payment_date <= end,
            )
            .group_by(Payment.payment_method)
        )
        by_method = {
            str(row[0]): round(float(row[1]), 2)
            for row in result.all()
            if row[0] and str(row[0]).lower() != "pharmacy"
        }
        
        refunds_result = await self.db.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0.0))
            .where(
                Payment.is_refund.is_(True),
                Payment.status == "completed",
                Payment.payment_date >= start,
                Payment.payment_date <= end,
            )
        )
        refund_total = float(refunds_result or 0.0)
        if refund_total > 0:
            by_method["refund"] = round(refund_total, 2)

        gross_collected = sum(v for k, v in by_method.items() if k != "refund")
        net_collected = max(0.0, gross_collected - refund_total)
        total = round(net_collected, 2)

        count = await self.db.scalar(
            select(func.count())
            .select_from(Payment)
            .where(
                Payment.is_refund.is_(False),
                Payment.status == "completed",
                Payment.payment_date >= start,
                Payment.payment_date <= end,
            )
        )
        return {"total_collected": total, "payment_count": count or 0, "by_method": by_method}


    async def get_period_report(self, start: datetime, end: datetime) -> dict:
        billed = await self.db.scalar(
            select(func.coalesce(func.sum(Billing.total_amount), 0)).where(
                Billing.is_deleted.is_(False),
                Billing.created_at >= start,
                Billing.created_at <= end,
            )
        )
        collected = await self.db.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.is_refund.is_(False),
                Payment.payment_date >= start,
                Payment.payment_date <= end,
            )
        )
        refunded = await self.db.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.is_refund.is_(True),
                Payment.payment_date >= start,
                Payment.payment_date <= end,
            )
        )
        bill_count = await self.db.scalar(
            select(func.count())
            .select_from(Billing)
            .where(Billing.is_deleted.is_(False), Billing.created_at >= start, Billing.created_at <= end)
        )
        payment_count = await self.db.scalar(
            select(func.count())
            .select_from(Payment)
            .where(Payment.payment_date >= start, Payment.payment_date <= end)
        )
        return {
            "total_billed": round(float(billed or 0), 2),
            "total_collected": round(float(collected or 0), 2),
            "total_pending": round(float((billed or 0) - (collected or 0)), 2),
            "total_refunded": round(float(refunded or 0), 2),
            "bill_count": bill_count or 0,
            "payment_count": payment_count or 0,
        }


class InsuranceRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, insurance: Insurance) -> Insurance:
        self.db.add(insurance)
        await self.db.flush()
        await self.db.refresh(insurance)
        return insurance

    async def get_by_id(self, insurance_id: int) -> Insurance | None:
        result = await self.db.execute(
            select(Insurance).where(Insurance.id == insurance_id, Insurance.is_deleted.is_(False))
        )
        return result.scalar_one_or_none()


class InsuranceClaimRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, claim: InsuranceClaim) -> InsuranceClaim:
        self.db.add(claim)
        await self.db.flush()
        await self.db.refresh(claim)
        return claim
