from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.ai_config_model import AIConfiguration

class AIConfigRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, config: AIConfiguration) -> AIConfiguration:
        self.db.add(config)
        await self.db.flush()
        await self.db.refresh(config)
        return config

    async def get_by_feature_name(self, name: str) -> AIConfiguration | None:
        result = await self.db.execute(select(AIConfiguration).where(AIConfiguration.feature_name == name))
        return result.scalar_one_or_none()

    async def list_configs(self) -> list[AIConfiguration]:
        result = await self.db.execute(select(AIConfiguration))
        return list(result.scalars().all())

    async def update(self, config: AIConfiguration) -> AIConfiguration:
        await self.db.flush()
        await self.db.refresh(config)
        return config
