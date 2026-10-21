from sqlalchemy import func, select, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.vendor_model import Vendor
from app.utils.helpers import utc_now


class VendorRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _base_query(self, hospital_id: int | None = None):
        query = select(Vendor).where(Vendor.is_deleted.is_(False))
        if hospital_id is not None:
            from app.models.inventory_model import InventoryItem, Warehouse
            item_subquery = (
                select(1)
                .select_from(InventoryItem)
                .join(Warehouse, InventoryItem.warehouse_id == Warehouse.id)
                .where(
                    InventoryItem.vendor_id == Vendor.id,
                    InventoryItem.is_deleted.is_(False),
                    Warehouse.hospital_id == hospital_id,
                )
            )
            query = query.where(
                or_(
                    Vendor.hospital_id == hospital_id,
                    and_(Vendor.hospital_id.is_(None), item_subquery.exists())
                )
            )
        return query

    async def list_all(
        self,
        skip: int = 0,
        limit: int = 20,
        vendor_type: str | None = None,
        hospital_id: int | None = None,
        search: str | None = None,
    ) -> list[Vendor]:
        query = self._base_query(hospital_id=hospital_id)
        if vendor_type is not None:
            norm_type = "expenses" if vendor_type.lower() == "expense" else vendor_type.lower()
            query = query.where(Vendor.vendor_type == norm_type)
        if search and search.strip():
            s = f"%{search.strip().lower()}%"
            query = query.where(
                or_(
                    func.lower(Vendor.name).ilike(s),
                    func.lower(Vendor.contact_person).ilike(s),
                    func.lower(Vendor.phone).ilike(s),
                    func.lower(Vendor.email).ilike(s),
                )
            )
        query = query.order_by(
            Vendor.created_at.desc(),
            Vendor.id.desc()
        )
        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_all(
        self,
        vendor_type: str | None = None,
        hospital_id: int | None = None,
        search: str | None = None,
    ) -> int:
        if hospital_id is not None:
            from app.models.inventory_model import InventoryItem, Warehouse
            item_subquery = (
                select(1)
                .select_from(InventoryItem)
                .join(Warehouse, InventoryItem.warehouse_id == Warehouse.id)
                .where(
                    InventoryItem.vendor_id == Vendor.id,
                    InventoryItem.is_deleted.is_(False),
                    Warehouse.hospital_id == hospital_id,
                )
            )
            query = (
                select(func.count(Vendor.id))
                .select_from(Vendor)
                .where(
                    Vendor.is_deleted.is_(False),
                    or_(
                        Vendor.hospital_id == hospital_id,
                        and_(Vendor.hospital_id.is_(None), item_subquery.exists())
                    )
                )
            )
            if vendor_type is not None:
                norm_type = "expenses" if vendor_type.lower() == "expense" else vendor_type.lower()
                query = query.where(Vendor.vendor_type == norm_type)
        else:
            query = select(func.count(Vendor.id)).select_from(Vendor).where(Vendor.is_deleted.is_(False))
            if vendor_type is not None:
                norm_type = "expenses" if vendor_type.lower() == "expense" else vendor_type.lower()
                query = query.where(Vendor.vendor_type == norm_type)
        if search and search.strip():
            s = f"%{search.strip().lower()}%"
            query = query.where(
                or_(
                    func.lower(Vendor.name).ilike(s),
                    func.lower(Vendor.contact_person).ilike(s),
                    func.lower(Vendor.phone).ilike(s),
                    func.lower(Vendor.email).ilike(s),
                )
            )
        return (await self.db.scalar(query)) or 0

    async def get_by_id(self, vendor_id: int, hospital_id: int | None = None) -> Vendor | None:
        result = await self.db.execute(self._base_query(hospital_id=hospital_id).where(Vendor.id == vendor_id))
        return result.scalars().first()

    async def get_by_name(self, name: str, hospital_id: int | None = None) -> Vendor | None:
        result = await self.db.execute(
            self._base_query(hospital_id=hospital_id).where(func.lower(Vendor.name) == name.lower().strip())
        )
        return result.scalars().first()

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

    async def get_all_active(self, vendor_type: str | None = None, hospital_id: int | None = None) -> list[Vendor]:
        query = self._base_query(hospital_id=hospital_id)
        if vendor_type is not None:
            norm_type = "expenses" if vendor_type.lower() == "expense" else vendor_type.lower()
            query = query.where(Vendor.vendor_type == norm_type)
        query = query.order_by(
            Vendor.created_at.desc(),
            Vendor.id.desc()
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())
