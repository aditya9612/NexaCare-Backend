from datetime import date, datetime
from sqlalchemy import func, select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.transaction_history_model import TransactionHistory
from app.utils.helpers import utc_now


class TransactionHistoryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _base_query(self):
        return select(TransactionHistory).where(TransactionHistory.is_deleted.is_(False))

    async def list_all(
        self,
        skip: int = 0,
        limit: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        event_type: str | None = None,
        status: str | None = None,
        start_date: date | datetime | None = None,
        end_date: date | datetime | None = None,
        reference_no: str | None = None,
        q: str | None = None,
    ) -> list[TransactionHistory]:
        query = self._base_query()

        if event_type is not None:
            query = query.where(func.lower(TransactionHistory.event_type) == event_type.lower().strip())
        if status is not None:
            query = query.where(func.lower(TransactionHistory.status) == status.lower().strip())

        if start_date is not None:
            if isinstance(start_date, date) and not isinstance(start_date, datetime):
                start_dt = datetime.combine(start_date, datetime.min.time())
            else:
                start_dt = start_date
            query = query.where(TransactionHistory.event_date >= start_dt)

        if end_date is not None:
            if isinstance(end_date, date) and not isinstance(end_date, datetime):
                end_dt = datetime.combine(end_date, datetime.max.time())
            else:
                end_dt = end_date
            query = query.where(TransactionHistory.event_date <= end_dt)

        if reference_no is not None:
            query = query.where(func.lower(TransactionHistory.reference_no).like(f"%{reference_no.lower().strip()}%"))

        if q is not None and q.strip() != "":
            pattern = f"%{q.lower().strip()}%"
            query = query.where(
                or_(
                    func.lower(TransactionHistory.reference_no).like(pattern),
                    func.lower(TransactionHistory.description).like(pattern),
                    func.lower(TransactionHistory.event_type).like(pattern),
                )
            )

        column = getattr(TransactionHistory, sort_by, TransactionHistory.created_at)
        if sort_order == "desc":
            query = query.order_by(column.desc(), TransactionHistory.id.desc())
        else:
            query = query.order_by(column.asc(), TransactionHistory.id.asc())

        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_all(
        self,
        event_type: str | None = None,
        status: str | None = None,
        start_date: date | datetime | None = None,
        end_date: date | datetime | None = None,
        reference_no: str | None = None,
        q: str | None = None,
    ) -> int:
        query = select(func.count()).select_from(TransactionHistory).where(TransactionHistory.is_deleted.is_(False))

        if event_type is not None:
            query = query.where(func.lower(TransactionHistory.event_type) == event_type.lower().strip())
        if status is not None:
            query = query.where(func.lower(TransactionHistory.status) == status.lower().strip())

        if start_date is not None:
            if isinstance(start_date, date) and not isinstance(start_date, datetime):
                start_dt = datetime.combine(start_date, datetime.min.time())
            else:
                start_dt = start_date
            query = query.where(TransactionHistory.event_date >= start_dt)

        if end_date is not None:
            if isinstance(end_date, date) and not isinstance(end_date, datetime):
                end_dt = datetime.combine(end_date, datetime.max.time())
            else:
                end_dt = end_date
            query = query.where(TransactionHistory.event_date <= end_dt)

        if reference_no is not None:
            query = query.where(func.lower(TransactionHistory.reference_no).like(f"%{reference_no.lower().strip()}%"))

        if q is not None and q.strip() != "":
            pattern = f"%{q.lower().strip()}%"
            query = query.where(
                or_(
                    func.lower(TransactionHistory.reference_no).like(pattern),
                    func.lower(TransactionHistory.description).like(pattern),
                    func.lower(TransactionHistory.event_type).like(pattern),
                )
            )

        return (await self.db.scalar(query)) or 0

    async def get_by_id(self, tx_id: int) -> TransactionHistory | None:
        result = await self.db.execute(self._base_query().where(TransactionHistory.id == tx_id))
        return result.scalar_one_or_none()

    async def create(self, tx_history: TransactionHistory) -> TransactionHistory:
        self.db.add(tx_history)
        await self.db.flush()
        await self.db.refresh(tx_history)
        return tx_history

    async def update(self, tx_history: TransactionHistory) -> TransactionHistory:
        await self.db.flush()
        await self.db.refresh(tx_history)
        return tx_history

    async def soft_delete(self, tx_history: TransactionHistory) -> None:
        tx_history.is_deleted = True
        tx_history.deleted_at = utc_now()
        await self.db.flush()

    async def get_aggregated_stats(self) -> list[tuple[str, float, int]]:
        query = select(
            TransactionHistory.event_type,
            func.coalesce(func.sum(TransactionHistory.amount), 0.0),
            func.count(TransactionHistory.id)
        ).where(
            TransactionHistory.is_deleted.is_(False)
        ).group_by(TransactionHistory.event_type)

        result = await self.db.execute(query)
        return [(row[0], float(row[1]), int(row[2])) for row in result.all()]
