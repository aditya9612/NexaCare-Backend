from sqlalchemy import select, func
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

    async def list_all(self, skip: int = 0, limit: int = 20) -> list[Department]:
        result = await self.db.execute(
            select(Department).offset(skip).limit(limit)
        )
        return list(result.scalars().all())

    async def count_all(self) -> int:
        result = await self.db.scalar(select(func.count()).select_from(Department))
        return result or 0

    async def update(self, department: Department) -> Department:
        await self.db.flush()
       
        return department

    async def delete(self, department: Department) -> None:
        await self.db.delete(department)
        await self.db.flush()
