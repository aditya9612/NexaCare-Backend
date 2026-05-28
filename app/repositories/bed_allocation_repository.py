from typing import List, Optional
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.bed_allocation_model import Floor, Room, Bed, BedActivityLog
from app.models.patient_model import Patient


class BedAllocationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # Floor Operations
    async def get_floor_by_id(self, floor_id: str, load_nested: bool = True) -> Optional[Floor]:
        if load_nested:
            query = (
                select(Floor)
                .where(Floor.id == floor_id)
                .options(selectinload(Floor.rooms).selectinload(Room.beds).selectinload(Bed.patient))
            )
        else:
            query = select(Floor).where(Floor.id == floor_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_floor_by_number(self, number: int) -> Optional[Floor]:
        query = select(Floor).where(Floor.number == number)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_floors(self) -> List[Floor]:
        query = (
            select(Floor)
            .options(selectinload(Floor.rooms).selectinload(Room.beds).selectinload(Bed.patient))
            .order_by(Floor.number.asc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def create_floor(self, floor: Floor) -> Floor:
        self.db.add(floor)
        await self.db.flush()
        await self.db.refresh(floor)
        return floor

    async def delete_floor(self, floor: Floor) -> None:
        await self.db.delete(floor)
        await self.db.flush()

    # Room Operations
    async def get_room_by_id(self, room_id: str, load_nested: bool = True) -> Optional[Room]:
        if load_nested:
            query = (
                select(Room)
                .where(Room.id == room_id)
                .options(selectinload(Room.beds).selectinload(Bed.patient))
            )
        else:
            query = select(Room).where(Room.id == room_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_room_by_number(self, floor_id: str, number: int) -> Optional[Room]:
        query = select(Room).where(Room.floor_id == floor_id, Room.number == number)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def create_room(self, room: Room) -> Room:
        self.db.add(room)
        await self.db.flush()
        await self.db.refresh(room)
        return room

    async def delete_room(self, room: Room) -> None:
        await self.db.delete(room)
        await self.db.flush()

    # Bed Operations
    async def get_bed_by_id(self, bed_id: str, load_patient: bool = True) -> Optional[Bed]:
        if load_patient:
            query = (
                select(Bed)
                .where(Bed.id == bed_id)
                .options(selectinload(Bed.patient), selectinload(Bed.room))
            )
        else:
            query = select(Bed).where(Bed.id == bed_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_bed_by_name(self, room_id: str, name: str) -> Optional[Bed]:
        query = select(Bed).where(Bed.room_id == room_id, Bed.name == name)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def create_bed(self, bed: Bed) -> Bed:
        self.db.add(bed)
        await self.db.flush()
        await self.db.refresh(bed)
        return bed

    async def delete_bed(self, bed: Bed) -> None:
        await self.db.delete(bed)
        await self.db.flush()

    # Patient Operations (Retrieves patient from main patients table)
    async def get_patient_by_id(self, patient_id: int) -> Optional[Patient]:
        query = select(Patient).where(Patient.id == patient_id, Patient.is_deleted.is_(False))
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    # BedActivityLog Operations
    async def create_activity_log(self, log: BedActivityLog) -> BedActivityLog:
        self.db.add(log)
        await self.db.flush()
        return log

    async def list_activity_logs(self, limit: int = 50) -> List[BedActivityLog]:
        query = select(BedActivityLog).order_by(BedActivityLog.timestamp.desc()).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    # Analytics Helpers
    async def count_floors(self) -> int:
        return await self.db.scalar(select(func.count(Floor.id))) or 0

    async def count_rooms(self) -> int:
        return await self.db.scalar(select(func.count(Room.id))) or 0

    async def count_beds(self) -> int:
        return await self.db.scalar(select(func.count(Bed.id))) or 0

    async def count_occupied_beds(self) -> int:
        return await self.db.scalar(select(func.count(Bed.id)).where(Bed.status == "Occupied")) or 0

    async def count_available_beds(self) -> int:
        return await self.db.scalar(select(func.count(Bed.id)).where(Bed.status == "Available")) or 0

    async def get_icu_bed_stats(self):
        total = await self.db.scalar(select(func.count(Bed.id)).where(func.lower(Bed.type) == "icu")) or 0
        occupied = await self.db.scalar(
            select(func.count(Bed.id)).where(func.lower(Bed.type) == "icu", Bed.status == "Occupied")
        ) or 0
        available = await self.db.scalar(
            select(func.count(Bed.id)).where(func.lower(Bed.type) == "icu", Bed.status == "Available")
        ) or 0
        return total, occupied, available
