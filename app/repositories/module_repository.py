from datetime import datetime
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.module_model import HospitalModule, Module
from app.utils.helpers import utc_now


class ModuleRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all_modules(self) -> list[Module]:
        result = await self.db.execute(select(Module).order_by(Module.id))
        return list(result.scalars().all())

    async def get_module_by_code(self, code: str) -> Module | None:
        result = await self.db.execute(select(Module).where(Module.code == code))
        return result.scalar_one_or_none()

    async def get_hospital_modules(self, hospital_id: int) -> list[HospitalModule]:
        result = await self.db.execute(
            select(HospitalModule).where(HospitalModule.hospital_id == hospital_id)
        )
        return list(result.scalars().all())

    async def get_active_module_codes(self, hospital_id: int) -> set[str]:
        result = await self.db.execute(
            select(HospitalModule.module_code).where(
                HospitalModule.hospital_id == hospital_id,
                HospitalModule.is_active.is_(True),
            )
        )
        return {code for code in result.scalars().all()}

    async def set_hospital_module_status(
        self,
        hospital_id: int,
        module_code: str,
        is_active: bool,
        status: str = "ACTIVE",
    ) -> HospitalModule:
        result = await self.db.execute(
            select(HospitalModule).where(
                HospitalModule.hospital_id == hospital_id,
                HospitalModule.module_code == module_code,
            )
        )
        hm = result.scalar_one_or_none()
        now = utc_now()
        if hm:
            hm.is_active = is_active
            hm.status = status
            hm.updated_at = now
            if is_active and not hm.activated_at:
                hm.activated_at = now
        else:
            hm = HospitalModule(
                hospital_id=hospital_id,
                module_code=module_code,
                is_active=is_active,
                status=status,
                activated_at=now if is_active else None,
            )
            self.db.add(hm)
        await self.db.flush()
        return hm

    async def bulk_set_hospital_modules(
        self,
        hospital_id: int,
        module_states: dict[str, bool],
    ) -> None:
        for code, is_active in module_states.items():
            await self.set_hospital_module_status(hospital_id, code, is_active)
