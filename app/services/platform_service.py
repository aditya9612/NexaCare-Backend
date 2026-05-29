from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.platform_repository import PlatformRepository

class PlatformService:
    def __init__(self, db: AsyncSession):
        self.repo = PlatformRepository(db)

    async def get_metrics(self) -> dict:
        return await self.repo.get_metrics()
