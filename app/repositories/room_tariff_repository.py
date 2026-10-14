from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.room_tariff_model import RoomTariff


class RoomTariffRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, tariff_id: int, hospital_id: Optional[int] = None) -> RoomTariff | None:
        query = select(RoomTariff).where(RoomTariff.id == tariff_id)
        if hospital_id is not None:
            query = query.where(RoomTariff.hospital_id == hospital_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_by_room_type(self, room_type: str, hospital_id: Optional[int] = None) -> RoomTariff | None:
        clean = room_type.strip()
        query = select(RoomTariff).where(RoomTariff.room_type.ilike(clean))
        if hospital_id is not None:
            query = query.where(RoomTariff.hospital_id == hospital_id)
        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_all(self, active_only: bool = False, hospital_id: Optional[int] = None) -> list[RoomTariff]:
        query = select(RoomTariff)
        if hospital_id is not None:
            query = query.where(RoomTariff.hospital_id == hospital_id)
        if active_only:
            query = query.where(RoomTariff.is_active.is_(True))
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
