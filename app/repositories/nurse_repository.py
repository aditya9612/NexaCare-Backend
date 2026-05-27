from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.department_model import Department
from app.models.nurse_model import Nurse


class NurseRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _base_query(self):
        return select(Nurse).outerjoin(Nurse.department)

    async def list_all(
        self,
        skip: int = 0,
        limit: int = 20,
        department_id: int | None = None,
        shift: str | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> list[Nurse]:
        query = self._base_query()
        if department_id:
            query = query.where(Nurse.department_id == department_id)
        if shift:
            query = query.where(Nurse.shift == shift)
        column = getattr(Nurse, sort_by, Nurse.created_at)
        query = query.order_by(column.desc() if sort_order == "desc" else column.asc())
        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_all(
        self,
        department_id: int | None = None,
        shift: str | None = None,
    ) -> int:
        query = select(func.count()).select_from(Nurse)
        if department_id:
            query = query.where(Nurse.department_id == department_id)
        if shift:
            query = query.where(Nurse.shift == shift)
        return await self.db.scalar(query) or 0

    async def get_by_id(self, nurse_id: int) -> Nurse | None:
        result = await self.db.execute(self._base_query().where(Nurse.id == nurse_id))
        return result.scalar_one_or_none()

    async def get_by_license(self, license_number: str) -> Nurse | None:
        result = await self.db.execute(
            select(Nurse).where(Nurse.license_number == license_number)
        )
        return result.scalar_one_or_none()

    def _search_filter(self, q: str):
        pattern = f"%{q.lower()}%"
        return or_(
            func.lower(Nurse.nurse_code).like(pattern),
            func.lower(Nurse.license_number).like(pattern),
            func.lower(Nurse.shift).like(pattern),
            func.lower(Department.department_name).like(pattern),
        )

    async def search(self, q: str, skip: int = 0, limit: int = 20) -> list[Nurse]:
        query = self._base_query().where(self._search_filter(q))
        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_search(self, q: str) -> int:
        return (
            await self.db.scalar(
                select(func.count())
                .select_from(Nurse)
                .outerjoin(Nurse.department)
                .where(self._search_filter(q))
            )
            or 0
        )

    async def create(self, nurse: Nurse) -> Nurse:
        self.db.add(nurse)
        await self.db.flush()
        await self.db.refresh(nurse)
        return nurse

    async def update(self, nurse: Nurse) -> Nurse:
        await self.db.flush()
        await self.db.refresh(nurse)
        return nurse

    async def delete(self, nurse: Nurse) -> None:
        await self.db.delete(nurse)
        await self.db.flush()
