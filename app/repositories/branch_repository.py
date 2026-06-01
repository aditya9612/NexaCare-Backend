from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.branch_model import Branch

class BranchRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, branch: Branch) -> Branch:
        self.db.add(branch)
        await self.db.flush()
        await self.db.refresh(branch)
        return branch

    async def get_by_id(self, id: int) -> Branch | None:
        result = await self.db.execute(
            select(Branch).where(Branch.id == id, Branch.is_deleted == False)
        )
        return result.scalar_one_or_none()

    async def get_by_code(self, code: str) -> Branch | None:
        result = await self.db.execute(
            select(Branch).where(Branch.code == code, Branch.is_deleted == False)
        )
        return result.scalar_one_or_none()

    async def list_branches(self, hospital_id: int | None = None, skip: int = 0, limit: int = 20) -> list[Branch]:
        query = select(Branch).where(Branch.is_deleted == False)
        if hospital_id is not None:
            query = query.where(Branch.hospital_id == hospital_id)
        query = query.offset(skip).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count_branches(self, hospital_id: int | None = None) -> int:
        query = select(func.count()).select_from(Branch).where(Branch.is_deleted == False)
        if hospital_id is not None:
            query = query.where(Branch.hospital_id == hospital_id)
        result = await self.db.scalar(query)
        return result or 0

    async def update(self, branch: Branch) -> Branch:
        await self.db.flush()
        await self.db.refresh(branch)
        return branch

    async def delete(self, branch: Branch) -> None:
        branch.is_deleted = True
        branch.is_active = False
        await self.db.flush()
