from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.department_model import Department

class DepartmentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, department: Department) -> Department:
        self.db.add(department)
        await self.db.flush()
        
        return department

    async def get_by_id(self, department_id: int) -> Department | None:
        result = await self.db.execute(
            select(Department).where(Department.department_id == department_id)
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Department | None:
        result = await self.db.execute(
            select(Department).where(Department.department_name == name)
        )
        return result.scalar_one_or_none()

    async def get_by_code(self, code: str) -> Department | None:
        result = await self.db.execute(
            select(Department).where(Department.department_code == code)
        )
        return result.scalar_one_or_none()

    async def list_all(
        self,
        skip: int = 0,
        limit: int | None = 20,
        search: str | None = None,
    ) -> list[Department]:
        stmt = select(Department)
        if search:
            clean_q = f"%{search.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Department.department_name).like(clean_q),
                    func.lower(Department.department_code).like(clean_q),
                )
            )
        stmt = stmt.order_by(Department.department_id.asc())
        if skip:
            stmt = stmt.offset(skip)
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def count_all(self, search: str | None = None) -> int:
        stmt = select(func.count()).select_from(Department)
        if search:
            clean_q = f"%{search.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Department.department_name).like(clean_q),
                    func.lower(Department.department_code).like(clean_q),
                )
            )
        result = await self.db.scalar(stmt)
        return result or 0

    async def update(self, department: Department) -> Department:
        await self.db.flush()
       
        return department

    async def delete(self, department: Department) -> None:
        await self.db.delete(department)
        await self.db.flush()
