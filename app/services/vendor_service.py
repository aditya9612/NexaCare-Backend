from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, NotFoundException, ConflictException
from app.models.vendor_model import Vendor
from app.models.expense_model import Expense
from app.models.inventory_model import InventoryItem
from app.repositories.vendor_repository import VendorRepository
from app.repositories.audit_repository import AuditRepository
from app.schemas.vendor_schema import VendorCreate, VendorUpdate, VendorResponse
from app.utils.pagination import build_paginated_result


class VendorService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.vendor_repo = VendorRepository(db)
        self.audit_repo = AuditRepository(db)

    async def create_vendor(self, data: VendorCreate, user_id: int) -> VendorResponse:
        existing = await self.vendor_repo.get_by_name(data.name)
        if existing:
            raise ConflictException(f"Vendor with name '{data.name}' already exists")

        vendor = Vendor(**data.model_dump())
        vendor = await self.vendor_repo.create(vendor)
        await self.audit_repo.create("create", "vendor", user_id=user_id, resource_id=str(vendor.id))
        return VendorResponse.model_validate(vendor)

    async def list_vendors(self, page: int = 1, size: int = 20, vendor_type: str | None = None):
        skip = (page - 1) * size
        vendors = await self.vendor_repo.list_all(skip=skip, limit=size, vendor_type=vendor_type)
        total = await self.vendor_repo.count_all(vendor_type=vendor_type)
        return build_paginated_result(
            [VendorResponse.model_validate(v) for v in vendors], total, page, size
        )

    async def get_vendor(self, vendor_id: int) -> VendorResponse:
        vendor = await self.vendor_repo.get_by_id(vendor_id)
        if not vendor:
            raise NotFoundException(f"Vendor with ID {vendor_id} not found")
        return VendorResponse.model_validate(vendor)

    async def update_vendor(self, vendor_id: int, data: VendorUpdate, user_id: int) -> VendorResponse:
        vendor = await self.vendor_repo.get_by_id(vendor_id)
        if not vendor:
            raise NotFoundException(f"Vendor with ID {vendor_id} not found")

        if data.name:
            existing = await self.vendor_repo.get_by_name(data.name)
            if existing and existing.id != vendor_id:
                raise ConflictException(f"Vendor with name '{data.name}' already exists")

        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(vendor, key, value)

        vendor = await self.vendor_repo.update(vendor)
        await self.audit_repo.create("update", "vendor", user_id=user_id, resource_id=str(vendor.id))
        return VendorResponse.model_validate(vendor)

    async def delete_vendor(self, vendor_id: int, user_id: int) -> None:
        vendor = await self.vendor_repo.get_by_id(vendor_id)
        if not vendor:
            raise NotFoundException(f"Vendor with ID {vendor_id} not found")

        # Check if linked to any expenses
        expense_exists = await self.db.scalar(
            select(func.count()).select_from(Expense).where(
                Expense.vendor_id == vendor_id,
                Expense.is_deleted.is_(False)
            )
        )
        if expense_exists and expense_exists > 0:
            raise BadRequestException("Cannot delete vendor as it is linked to one or more expenses")

        # Check if linked to any inventory items
        item_exists = await self.db.scalar(
            select(func.count()).select_from(InventoryItem).where(
                InventoryItem.vendor_id == vendor_id,
                InventoryItem.is_deleted.is_(False)
            )
        )
        if item_exists and item_exists > 0:
            raise BadRequestException("Cannot delete vendor as it is linked to one or more inventory items")

        await self.vendor_repo.soft_delete(vendor)
        await self.audit_repo.create("delete", "vendor", user_id=user_id, resource_id=str(vendor.id))
