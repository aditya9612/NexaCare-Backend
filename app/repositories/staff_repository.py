from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.staff_model import Staff
from app.utils.helpers import utc_now


class StaffRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _base_query(self):
        return (
            select(Staff)
            .options(selectinload(Staff.department), selectinload(Staff.role))
            .where(Staff.is_deleted.is_(False))
        )

    async def create(self, staff: Staff) -> Staff:
        self.db.add(staff)
        await self.db.flush()
        await self.db.refresh(staff)
        return staff

    async def get_by_id(self, staff_id: int) -> Staff | None:
        result = await self.db.execute(self._base_query().where(Staff.id == staff_id))
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Staff | None:
        result = await self.db.execute(
            self._base_query().where(func.lower(Staff.email) == email.lower())
        )
        return result.scalar_one_or_none()

    async def get_by_staff_code(self, staff_code: str) -> Staff | None:
        result = await self.db.execute(
            self._base_query().where(func.lower(Staff.staff_code) == staff_code.lower())
        )
        return result.scalar_one_or_none()

    async def list_all(
        self,
        skip: int = 0,
        limit: int = 20,
        q: str | None = None,
        department_id: int | None = None,
        status: int | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> list[Staff]:
        query = self._base_query()
        if q:
            pattern = f"%{q.lower()}%"
            query = query.where(
                or_(
                    func.lower(Staff.full_name).like(pattern),
                    func.lower(Staff.email).like(pattern),
                )
            )
        if department_id is not None:
            query = query.where(Staff.department_id == department_id)
        if status is not None:
            query = query.where(Staff.status == status)

        column = getattr(Staff, sort_by, Staff.created_at)
        query = query.order_by(column.desc() if sort_order == "desc" else column.asc())
        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_all(
        self,
        q: str | None = None,
        department_id: int | None = None,
        status: int | None = None,
    ) -> int:
        query = select(func.count()).select_from(Staff).where(Staff.is_deleted.is_(False))
        if q:
            pattern = f"%{q.lower()}%"
            query = query.where(
                or_(
                    func.lower(Staff.full_name).like(pattern),
                    func.lower(Staff.email).like(pattern),
                )
            )
        if department_id is not None:
            query = query.where(Staff.department_id == department_id)
        if status is not None:
            query = query.where(Staff.status == status)
        return await self.db.scalar(query) or 0

    async def list_by_department(self, department_id: int) -> list[Staff]:
        result = await self.db.execute(
            self._base_query().where(Staff.department_id == department_id)
        )
        return list(result.scalars().all())

    async def get_dashboard_stats(self) -> dict:
        total = await self.db.scalar(
            select(func.count()).select_from(Staff).where(Staff.is_deleted.is_(False))
        ) or 0
        active = await self.db.scalar(
            select(func.count()).select_from(Staff).where(Staff.is_deleted.is_(False), Staff.status == 1)
        ) or 0
        inactive = await self.db.scalar(
            select(func.count()).select_from(Staff).where(Staff.is_deleted.is_(False), Staff.status == 0)
        ) or 0
        return {
            "total_staff": total,
            "active_staff": active,
            "inactive_staff": inactive,
        }

    async def update(self, staff: Staff) -> Staff:
        await self.db.flush()
        await self.db.refresh(staff)
        return staff

    async def soft_delete(self, staff: Staff) -> Staff:
        staff.is_deleted = True
        staff.deleted_at = utc_now()
        staff.status = 0
        await self.db.flush()
        return staff
