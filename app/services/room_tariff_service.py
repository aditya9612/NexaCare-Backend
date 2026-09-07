from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, ConflictException, NotFoundException
from app.models.room_tariff_model import RoomTariff
from app.repositories.room_tariff_repository import RoomTariffRepository
from app.schemas.room_tariff_schema import RoomTariffCreate, RoomTariffResponse, RoomTariffUpdate


class RoomTariffService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = RoomTariffRepository(db)

    async def list_tariffs(self, active_only: bool = False) -> list[RoomTariffResponse]:
        tariffs = await self.repo.get_all(active_only=active_only)
        if not tariffs and not active_only:
            # Auto-seed standard default tariffs if empty
            await self._seed_default_tariffs()
            tariffs = await self.repo.get_all(active_only=active_only)
        return [RoomTariffResponse.model_validate(t) for t in tariffs]

    async def get_by_id(self, tariff_id: int) -> RoomTariffResponse:
        tariff = await self.repo.get_by_id(tariff_id)
        if not tariff:
            raise NotFoundException(f"Room tariff with id {tariff_id} not found")
        return RoomTariffResponse.model_validate(tariff)

    async def get_by_room_type(self, room_type: str) -> RoomTariff:
        tariff = await self.repo.get_by_room_type(room_type)
        if not tariff:
            # Fallback based on generic room matching
            all_tariffs = await self.repo.get_all(active_only=True)
            for t in all_tariffs:
                if t.room_type.lower() in room_type.lower() or room_type.lower() in t.room_type.lower():
                    return t
            # Default general tariff fallback
            return RoomTariff(
                room_type=room_type,
                daily_rate=1000.0,
                nursing_charge_per_day=300.0,
                doctor_visit_charge=500.0,
                is_active=True,
            )
        return tariff

    async def create(self, data: RoomTariffCreate) -> RoomTariffResponse:
        existing = await self.repo.get_by_room_type(data.room_type)
        if existing:
            raise ConflictException(f"Tariff for room type '{data.room_type}' already exists")

        tariff = RoomTariff(
            room_type=data.room_type.strip(),
            daily_rate=data.daily_rate,
            nursing_charge_per_day=data.nursing_charge_per_day,
            doctor_visit_charge=data.doctor_visit_charge,
            description=data.description,
            is_active=data.is_active,
        )
        tariff = await self.repo.create(tariff)
        return RoomTariffResponse.model_validate(tariff)

    async def update(self, tariff_id: int, data: RoomTariffUpdate) -> RoomTariffResponse:
        tariff = await self.repo.get_by_id(tariff_id)
        if not tariff:
            raise NotFoundException(f"Room tariff with id {tariff_id} not found")

        update_dict = data.model_dump(exclude_unset=True)
        if "room_type" in update_dict and update_dict["room_type"] != tariff.room_type:
            existing = await self.repo.get_by_room_type(update_dict["room_type"])
            if existing and existing.id != tariff.id:
                raise ConflictException(f"Tariff for room type '{update_dict['room_type']}' already exists")
            tariff.room_type = update_dict["room_type"].strip()

        for key, value in update_dict.items():
            if key != "room_type" and value is not None:
                setattr(tariff, key, value)

        tariff = await self.repo.update(tariff)
        return RoomTariffResponse.model_validate(tariff)

    async def delete(self, tariff_id: int) -> None:
        tariff = await self.repo.get_by_id(tariff_id)
        if not tariff:
            raise NotFoundException(f"Room tariff with id {tariff_id} not found")
        await self.repo.delete(tariff)

    async def _seed_default_tariffs(self) -> None:
        defaults = [
            ("ICU", 5000.0, 1000.0, 1000.0, "Intensive Care Unit with 24/7 cardiac monitoring"),
            ("Deluxe", 3500.0, 600.0, 600.0, "Private air-conditioned deluxe room with attendant bed"),
            ("Special", 2000.0, 400.0, 500.0, "Semi-private room with attached bathroom"),
            ("General Ward", 800.0, 250.0, 300.0, "General ward multi-bed accommodation"),
        ]
        for name, rate, nurse, doc, desc in defaults:
            t = RoomTariff(
                room_type=name,
                daily_rate=rate,
                nursing_charge_per_day=nurse,
                doctor_visit_charge=doc,
                description=desc,
                is_active=True,
            )
            self.db.add(t)
        await self.db.flush()
