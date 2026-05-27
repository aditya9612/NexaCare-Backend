from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import ReorderAlertStatus, StockTransactionType
from app.core.exceptions import BadRequestException, NotFoundException
from app.models.inventory_model import InventoryItem, ReorderAlert, StockTransaction, Vendor, Warehouse
from app.repositories.audit_repository import AuditRepository
from app.repositories.department_repository import DepartmentRepository
from app.repositories.inventory_repository import (
    InventoryRepository,
    ReorderAlertRepository,
    StockTransactionRepository,
    VendorRepository,
    WarehouseRepository,
)
from app.schemas.inventory_schema import (
    ConsumptionReport,
    InventoryItemCreate,
    InventoryItemResponse,
    InventoryItemUpdate,
    ReorderAlertResponse,
    StockSummary,
    StockTransactionCreate,
    StockTransactionResponse,
    VendorCreate,
    VendorResponse,
    VendorUpdate,
    WarehouseCreate,
    WarehouseResponse,
    WarehouseUpdate,
)
from app.utils.helpers import generate_code, generate_stock_transaction_number, utc_now
from app.utils.pagination import build_paginated_result


class InventoryService:
    def __init__(self, db: AsyncSession):
        self.item_repo = InventoryRepository(db)
        self.transaction_repo = StockTransactionRepository(db)
        self.vendor_repo = VendorRepository(db)
        self.warehouse_repo = WarehouseRepository(db)
        self.alert_repo = ReorderAlertRepository(db)
        self.audit_repo = AuditRepository(db)
        self.dept_repo = DepartmentRepository(db)

    async def _validate_department(self, department_id: int | None) -> None:
        if department_id is not None:
            dept = await self.dept_repo.get_by_id(department_id)
            if not dept:
                raise NotFoundException(f"Department with ID {department_id} not found")

    async def create_item(self, data: InventoryItemCreate, user_id: int) -> InventoryItemResponse:
        await self._validate_department(data.department_id)
        sku = data.sku or generate_code("SKU")
        item = InventoryItem(sku=sku, **data.model_dump(exclude={"sku"}))
        item = await self.item_repo.create(item)
        await self._check_reorder_alert(item)
        await self.audit_repo.create("create", "inventory", user_id=user_id, resource_id=str(item.id))
        return InventoryItemResponse.model_validate(item)

    async def list_items(
        self, page: int = 1, size: int = 20, sort_by: str = "created_at",
        sort_order: str = "desc", category: str | None = None, warehouse_id: int | None = None,
    ):
        skip = (page - 1) * size
        items = await self.item_repo.list_all(
            skip=skip, limit=size, sort_by=sort_by, sort_order=sort_order,
            category=category, warehouse_id=warehouse_id,
        )
        total = await self.item_repo.count_all(category=category, warehouse_id=warehouse_id)
        return build_paginated_result([InventoryItemResponse.model_validate(i) for i in items], total, page, size)

    async def search_items(self, q: str, page: int = 1, size: int = 20):
        skip = (page - 1) * size
        items = await self.item_repo.search(q, skip=skip, limit=size)
        total = await self.item_repo.count_search(q)
        return build_paginated_result([InventoryItemResponse.model_validate(i) for i in items], total, page, size)

    async def get_item(self, item_id: int) -> InventoryItemResponse:
        item = await self.item_repo.get_by_id(item_id)
        if not item:
            raise NotFoundException("Inventory item not found")
        return InventoryItemResponse.model_validate(item)

    async def update_item(self, item_id: int, data: InventoryItemUpdate, user_id: int) -> InventoryItemResponse:
        item = await self.item_repo.get_by_id(item_id)
        if not item:
            raise NotFoundException("Inventory item not found")
        await self._validate_department(data.department_id)
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(item, key, value)
        item = await self.item_repo.update(item)
        await self._check_reorder_alert(item)
        await self.audit_repo.create("update", "inventory", user_id=user_id, resource_id=str(item.id))
        return InventoryItemResponse.model_validate(item)

    async def delete_item(self, item_id: int, user_id: int) -> None:
        item = await self.item_repo.get_by_id(item_id)
        if not item:
            raise NotFoundException("Inventory item not found")
        await self.item_repo.soft_delete(item)
        await self.audit_repo.create("delete", "inventory", user_id=user_id, resource_id=str(item.id))

    async def _check_reorder_alert(self, item: InventoryItem) -> None:
        if item.quantity <= item.reorder_level:
            alert = ReorderAlert(
                item_id=item.id,
                current_quantity=item.quantity,
                reorder_level=item.reorder_level,
                status=ReorderAlertStatus.ACTIVE,
            )
            await self.alert_repo.create(alert)
        else:
            await self.alert_repo.resolve_for_item(item.id)

    async def create_transaction(self, data: StockTransactionCreate, user_id: int) -> StockTransactionResponse:
        item = await self.item_repo.get_by_id(data.item_id)
        if not item:
            raise NotFoundException("Inventory item not found")

        delta = data.quantity
        if data.transaction_type in (StockTransactionType.OUTWARD, StockTransactionType.CONSUMPTION):
            if item.quantity < data.quantity:
                raise BadRequestException("Insufficient stock for transaction")
            delta = -data.quantity
        elif data.transaction_type == StockTransactionType.TRANSFER:
            if not data.target_warehouse_id:
                raise BadRequestException("Target warehouse required for transfer")
            if item.quantity < data.quantity:
                raise BadRequestException("Insufficient stock for transfer")
            delta = -data.quantity
        elif data.transaction_type == StockTransactionType.INWARD:
            delta = data.quantity
        elif data.transaction_type == StockTransactionType.ADJUSTMENT:
            delta = data.quantity - item.quantity

        transaction = StockTransaction(
            transaction_number=generate_stock_transaction_number(),
            transaction_date=utc_now(),
            performed_by=user_id,
            **data.model_dump(exclude={"target_warehouse_id"}),
        )
        transaction = await self.transaction_repo.create(transaction)
        await self.item_repo.update_quantity(data.item_id, delta)
        item = await self.item_repo.get_by_id(data.item_id)
        if item:
            await self._check_reorder_alert(item)
        await self.audit_repo.create("create", "inventory_transaction", user_id=user_id, resource_id=str(transaction.id))
        return StockTransactionResponse.model_validate(transaction)

    async def list_transactions(
        self, page: int = 1, size: int = 20, item_id: int | None = None, transaction_type: str | None = None
    ):
        skip = (page - 1) * size
        items = await self.transaction_repo.list_all(
            skip=skip, limit=size, item_id=item_id, transaction_type=transaction_type
        )
        total = await self.transaction_repo.count_all(item_id=item_id, transaction_type=transaction_type)
        return build_paginated_result(
            [StockTransactionResponse.model_validate(t) for t in items], total, page, size
        )

    async def create_vendor(self, data: VendorCreate, user_id: int) -> VendorResponse:
        vendor = Vendor(**data.model_dump())
        vendor = await self.vendor_repo.create(vendor)
        await self.audit_repo.create("create", "inventory_vendor", user_id=user_id, resource_id=str(vendor.id))
        return VendorResponse.model_validate(vendor)

    async def list_vendors(self, page: int = 1, size: int = 20):
        skip = (page - 1) * size
        items = await self.vendor_repo.list_all(skip=skip, limit=size)
        total = await self.vendor_repo.count_all()
        return build_paginated_result([VendorResponse.model_validate(v) for v in items], total, page, size)

    async def create_warehouse(self, data: WarehouseCreate, user_id: int) -> WarehouseResponse:
        code = data.code or generate_code("WH")
        warehouse = Warehouse(code=code, name=data.name, location=data.location, capacity=data.capacity)
        warehouse = await self.warehouse_repo.create(warehouse)
        await self.audit_repo.create("create", "inventory_warehouse", user_id=user_id, resource_id=str(warehouse.id))
        return WarehouseResponse.model_validate(warehouse)

    async def list_warehouses(self, page: int = 1, size: int = 20):
        skip = (page - 1) * size
        items = await self.warehouse_repo.list_all(skip=skip, limit=size)
        total = await self.warehouse_repo.count_all()
        return build_paginated_result([WarehouseResponse.model_validate(w) for w in items], total, page, size)

    async def get_reorder_alerts(self, page: int = 1, size: int = 50) -> list[ReorderAlertResponse]:
        skip = (page - 1) * size
        alerts = await self.alert_repo.list_active(skip=skip, limit=size)
        result = []
        for alert in alerts:
            item = await self.item_repo.get_by_id(alert.item_id)
            result.append(ReorderAlertResponse(
                id=alert.id,
                item_id=alert.item_id,
                item_name=item.name if item else "",
                sku=item.sku if item else "",
                current_quantity=alert.current_quantity,
                reorder_level=alert.reorder_level,
                status=alert.status,
                created_at=alert.created_at,
            ))
        return result

    async def get_stock_summary(self) -> StockSummary:
        data = await self.item_repo.get_stock_summary()
        return StockSummary(**data)

    async def get_consumption_report(self, period: str = "monthly") -> list[ConsumptionReport]:
        now = utc_now()
        if period == "daily":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "yearly":
            start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        rows = await self.transaction_repo.get_consumption_report(start, now)
        return [ConsumptionReport(period=period, **row) for row in rows]
