from datetime import date, datetime
from sqlalchemy import func, select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.billing_model import Payment, Billing


class TransactionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _base_query(self):
        return select(Payment)

    async def list_all(
        self,
        skip: int = 0,
        limit: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        billing_id: int | None = None,
        payment_method: str | None = None,
        status: str | None = None,
        start_date: date | datetime | None = None,
        end_date: date | datetime | None = None,
        q: str | None = None,
    ) -> list[Payment]:
        query = self._base_query()

        if billing_id is not None:
            query = query.where(Payment.billing_id == billing_id)
        if payment_method is not None:
            query = query.where(func.lower(Payment.payment_method) == payment_method.lower().strip())
        if status is not None:
            query = query.where(func.lower(Payment.status) == status.lower().strip())

        if start_date is not None:
            if isinstance(start_date, date) and not isinstance(start_date, datetime):
                start_dt = datetime.combine(start_date, datetime.min.time())
            else:
                start_dt = start_date
            query = query.where(Payment.payment_date >= start_dt)

        if end_date is not None:
            if isinstance(end_date, date) and not isinstance(end_date, datetime):
                end_dt = datetime.combine(end_date, datetime.max.time())
            else:
                end_dt = end_date
            query = query.where(Payment.payment_date <= end_dt)

        if q is not None and q.strip() != "":
            pattern = f"%{q.lower().strip()}%"
            query = query.join(Payment.billing).where(
                or_(
                    func.lower(Payment.payment_method).like(pattern),
                    func.lower(Payment.transaction_ref).like(pattern),
                    func.lower(Payment.status).like(pattern),
                    func.lower(Billing.bill_number).like(pattern),
                )
            )

        column = getattr(Payment, sort_by, Payment.created_at)
        if sort_order == "desc":
            query = query.order_by(column.desc(), Payment.id.desc())
        else:
            query = query.order_by(column.asc(), Payment.id.asc())

        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_all(
        self,
        billing_id: int | None = None,
        payment_method: str | None = None,
        status: str | None = None,
        start_date: date | datetime | None = None,
        end_date: date | datetime | None = None,
        q: str | None = None,
    ) -> int:
        query = select(func.count()).select_from(Payment)

        if billing_id is not None:
            query = query.where(Payment.billing_id == billing_id)
        if payment_method is not None:
            query = query.where(func.lower(Payment.payment_method) == payment_method.lower().strip())
        if status is not None:
            query = query.where(func.lower(Payment.status) == status.lower().strip())

        if start_date is not None:
            if isinstance(start_date, date) and not isinstance(start_date, datetime):
                start_dt = datetime.combine(start_date, datetime.min.time())
            else:
                start_dt = start_date
            query = query.where(Payment.payment_date >= start_dt)

        if end_date is not None:
            if isinstance(end_date, date) and not isinstance(end_date, datetime):
                end_dt = datetime.combine(end_date, datetime.max.time())
            else:
                end_dt = end_date
            query = query.where(Payment.payment_date <= end_dt)

        if q is not None and q.strip() != "":
            pattern = f"%{q.lower().strip()}%"
            query = query.join(Payment.billing).where(
                or_(
                    func.lower(Payment.payment_method).like(pattern),
                    func.lower(Payment.transaction_ref).like(pattern),
                    func.lower(Payment.status).like(pattern),
                    func.lower(Billing.bill_number).like(pattern),
                )
            )

        return (await self.db.scalar(query)) or 0

    async def get_by_id(self, payment_id: int) -> Payment | None:
        result = await self.db.execute(self._base_query().where(Payment.id == payment_id))
        return result.scalar_one_or_none()

    async def create(self, payment: Payment) -> Payment:
        self.db.add(payment)
        await self.db.flush()
        await self.db.refresh(payment)
        return payment

    async def update(self, payment: Payment) -> Payment:
        await self.db.flush()
        await self.db.refresh(payment)
        return payment

    async def delete(self, payment: Payment) -> None:
        await self.db.delete(payment)
        await self.db.flush()

    async def get_all_active(
        self,
        billing_id: int | None = None,
        payment_method: str | None = None,
        status: str | None = None,
        start_date: date | datetime | None = None,
        end_date: date | datetime | None = None,
        q: str | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> list[Payment]:
        query = self._base_query()

        if billing_id is not None:
            query = query.where(Payment.billing_id == billing_id)
        if payment_method is not None:
            query = query.where(func.lower(Payment.payment_method) == payment_method.lower().strip())
        if status is not None:
            query = query.where(func.lower(Payment.status) == status.lower().strip())

        if start_date is not None:
            if isinstance(start_date, date) and not isinstance(start_date, datetime):
                start_dt = datetime.combine(start_date, datetime.min.time())
            else:
                start_dt = start_date
            query = query.where(Payment.payment_date >= start_dt)

        if end_date is not None:
            if isinstance(end_date, date) and not isinstance(end_date, datetime):
                end_dt = datetime.combine(end_date, datetime.max.time())
            else:
                end_dt = end_date
            query = query.where(Payment.payment_date <= end_dt)

        if q is not None and q.strip() != "":
            pattern = f"%{q.lower().strip()}%"
            query = query.join(Payment.billing).where(
                or_(
                    func.lower(Payment.payment_method).like(pattern),
                    func.lower(Payment.transaction_ref).like(pattern),
                    func.lower(Payment.status).like(pattern),
                    func.lower(Billing.bill_number).like(pattern),
                )
            )

        column = getattr(Payment, sort_by, Payment.created_at)
        if sort_order == "desc":
            query = query.order_by(column.desc(), Payment.id.desc())
        else:
            query = query.order_by(column.asc(), Payment.id.asc())

        result = await self.db.execute(query)
        return list(result.scalars().all())
