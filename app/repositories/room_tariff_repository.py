from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.room_tariff_model import RoomTariff


class RoomTariffRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, tariff_id: int) -> RoomTariff | None:
        return await self.db.get(RoomTariff, tariff_id)

    async def get_by_room_type(self, room_type: str) -> RoomTariff | None:
        clean = room_type.strip()
        result = await self.db.execute(
            select(RoomTariff).where(RoomTariff.room_type.ilike(clean))
        )
        return result.scalars().first()

    async def get_all(self, active_only: bool = False) -> list[RoomTariff]:
        query = select(RoomTariff)
        if active_only:
            query = query.where(RoomTariff.is_active == True)
        query = query.order_by(RoomTariff.room_type.asc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def create(self, tariff: RoomTariff) -> RoomTariff:
        self.db.add(tariff)
        await self.db.flush()
        await self.db.refresh(tariff)
        return tariff

    async def update(self, tariff: RoomTariff) -> RoomTariff:
        await self.db.flush()
        await self.db.refresh(tariff)
        return tariff

    async def delete(self, tariff: RoomTariff) -> None:
        await self.db.delete(tariff)
        await self.db.flush()
