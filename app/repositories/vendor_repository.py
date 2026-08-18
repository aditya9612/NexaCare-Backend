from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.vendor_model import Vendor
from app.utils.helpers import utc_now


class VendorRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _base_query(self):
        return select(Vendor).where(Vendor.is_deleted.is_(False))

    async def list_all(self, skip: int = 0, limit: int = 20, vendor_type: str | None = None) -> list[Vendor]:
        query = self._base_query()
        if vendor_type is not None:
            query = query.where(Vendor.vendor_type == vendor_type)
        query = query.order_by(
            Vendor.created_at.desc(),
            Vendor.id.desc()
        )
        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_all(self, vendor_type: str | None = None) -> int:
        query = select(func.count()).select_from(Vendor).where(Vendor.is_deleted.is_(False))
        if vendor_type is not None:
            query = query.where(Vendor.vendor_type == vendor_type)
        return (await self.db.scalar(query)) or 0

    async def get_by_id(self, vendor_id: int) -> Vendor | None:
        result = await self.db.execute(self._base_query().where(Vendor.id == vendor_id))
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Vendor | None:
        result = await self.db.execute(
            self._base_query().where(func.lower(Vendor.name) == name.lower().strip())
        )
        return result.scalar_one_or_none()

    async def create(self, vendor: Vendor) -> Vendor:
        self.db.add(vendor)
        await self.db.flush()
        await self.db.refresh(vendor)
        return vendor

    async def update(self, vendor: Vendor) -> Vendor:
        await self.db.flush()
        await self.db.refresh(vendor)
        return vendor

    async def soft_delete(self, vendor: Vendor) -> None:
        vendor.is_deleted = True
        vendor.deleted_at = utc_now()
        await self.db.flush()

    async def get_all_active(self, vendor_type: str | None = None) -> list[Vendor]:
        query = self._base_query()
        if vendor_type is not None:
            query = query.where(Vendor.vendor_type == vendor_type)
        query = query.order_by(
            Vendor.created_at.desc(),
            Vendor.id.desc()
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())
