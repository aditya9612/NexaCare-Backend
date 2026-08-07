from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import ReorderAlertStatus, StockTransactionType
from app.core.exceptions import BadRequestException, NotFoundException, ConflictException
from app.models.inventory_model import InventoryItem, ReorderAlert, StockTransaction, Warehouse
from app.models.vendor_model import Vendor
from app.repositories.audit_repository import AuditRepository
from app.repositories.department_repository import DepartmentRepository
from app.repositories.inventory_repository import (
    InventoryRepository,
    ReorderAlertRepository,
    StockTransactionRepository,
    WarehouseRepository,
)
from app.repositories.vendor_repository import VendorRepository
from app.schemas.inventory_schema import (
    ConsumptionReport,
    InventoryItemCreate,
    InventoryItemResponse,
    InventoryItemUpdate,
    ReorderAlertResponse,
    StockSummary,
    StockTransactionCreate,
    StockTransactionResponse,
    StockTransactionUpdate,
    # Vendor schemas removed (centralized)
    WarehouseCreate,
    WarehouseResponse,
    WarehouseUpdate,
    InventoryDashboardResponse,
)
from app.utils.helpers import generate_code, generate_stock_transaction_number, utc_now
from app.utils.pagination import build_paginated_result


class InventoryService:
    def __init__(self, db: AsyncSession):
        self.db = db
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

    async def _validate_warehouse(self, warehouse_id: int | None) -> None:
        if warehouse_id is not None:
            wh = await self.warehouse_repo.get_by_id(warehouse_id)
            if not wh:
                raise NotFoundException(f"Warehouse with ID {warehouse_id} not found")

    async def _validate_vendor(self, vendor_id: int | None) -> None:
        if vendor_id is not None:
            vendor = await self.vendor_repo.get_by_id(vendor_id)
            if not vendor:
                raise NotFoundException(f"Vendor with ID {vendor_id} not found")

    async def create_item(self, data: InventoryItemCreate, user_id: int) -> InventoryItemResponse:
        await self._validate_department(data.department_id)
        await self._validate_warehouse(data.warehouse_id)
        await self._validate_vendor(data.vendor_id)

        # Check duplicate name case-insensitive ignoring leading/trailing spaces
        existing_name = await self.item_repo.get_by_name(data.name)
        if existing_name:
            raise ConflictException("Inventory item with this name already exists.")
        
        sku = data.sku
        if sku:
            existing = await self.item_repo.get_by_sku(sku)
            if existing:
                raise ConflictException("Inventory item with this SKU already exists")
        else:
            while True:
                sku = generate_code("SKU")
                existing = await self.item_repo.get_by_sku(sku)
                if not existing:
                    break
                    
        barcode = data.barcode
        if barcode:
            existing_barcode = await self.item_repo.get_by_barcode(barcode)
            if existing_barcode:
                raise ConflictException("Inventory item with this barcode already exists")

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
        await self._validate_warehouse(data.warehouse_id)
        await self._validate_vendor(data.vendor_id)
        
        if data.barcode:
            existing_barcode = await self.item_repo.get_by_barcode(data.barcode)
            if existing_barcode and existing_barcode.id != item_id:
                raise ConflictException("Inventory item with this barcode already exists")

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
        item = await self.item_repo.get_by_id_for_update(data.item_id)
        if not item:
            raise NotFoundException("Inventory item not found")

        # Validate reference_type if provided
        if data.reference_type is not None:
            CANONICAL_REF_TYPES = {
                "purchase order": "Purchase Order",
                "sales order": "Sales Order",
                "adjustment": "Adjustment",
                "transfer": "Transfer",
                "return": "Return",
                "opening stock": "Opening Stock"
            }
            ref_type_lower = data.reference_type.lower()
            if ref_type_lower not in CANONICAL_REF_TYPES:
                raise BadRequestException(
                    "Invalid reference_type. Allowed values are: Purchase Order, Sales Order, Adjustment, Transfer, Return, Opening Stock."
                )
            data.reference_type = CANONICAL_REF_TYPES[ref_type_lower]

        # Validate duplicate reference
        if data.reference_type is not None and data.reference_id is not None:
            existing_ref = await self.transaction_repo.get_by_reference(data.reference_type, data.reference_id)
            if existing_ref:
                raise ConflictException(
                    f"Stock transaction with reference type '{data.reference_type}' and reference ID {data.reference_id} already exists"
                )
            
        await self._validate_warehouse(data.warehouse_id)
        await self._validate_warehouse(data.target_warehouse_id)

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

    async def update_transaction(
        self, transaction_id: int, data: StockTransactionUpdate, user_id: int
    ) -> StockTransactionResponse:
        transaction = await self.transaction_repo.get_by_id(transaction_id)
        if not transaction:
            raise NotFoundException("Stock transaction not found")

        # If transaction type is adjustment and quantity is being updated, raise error
        if transaction.transaction_type == StockTransactionType.ADJUSTMENT and data.quantity is not None:
            raise BadRequestException("Adjustment transactions cannot have their quantity updated")

        item = await self.item_repo.get_by_id(transaction.item_id)
        if not item:
            raise NotFoundException("Inventory item associated with transaction not found")

        # Reverse the old transaction impact:
        reverse_delta = 0
        if transaction.transaction_type == StockTransactionType.INWARD:
            reverse_delta = -transaction.quantity
        elif transaction.transaction_type in (
            StockTransactionType.OUTWARD,
            StockTransactionType.CONSUMPTION,
            StockTransactionType.TRANSFER,
        ):
            reverse_delta = transaction.quantity

        # Validate that reversing the old impact does not make inventory negative
        if item.quantity + reverse_delta < 0:
            raise BadRequestException("Insufficient stock to reverse previous transaction impact")

        # New impact:
        new_quantity = data.quantity if data.quantity is not None else transaction.quantity
        new_delta = 0
        if transaction.transaction_type == StockTransactionType.INWARD:
            new_delta = new_quantity
        elif transaction.transaction_type in (
            StockTransactionType.OUTWARD,
            StockTransactionType.CONSUMPTION,
            StockTransactionType.TRANSFER,
        ):
            new_delta = -new_quantity

        # Validate that the new quantity and the final resulting inventory doesn't drop below 0
        if item.quantity + reverse_delta + new_delta < 0:
            raise BadRequestException("Insufficient stock for transaction update")

        # Apply net delta to the item
        net_delta = reverse_delta + new_delta
        if net_delta != 0:
            await self.item_repo.update_quantity(item.id, net_delta)

        # Build details for audit logging before modifying the record
        old_values = {
            "quantity": transaction.quantity,
            "unit_cost": transaction.unit_cost,
            "reference_type": transaction.reference_type,
            "reference_id": transaction.reference_id,
            "notes": transaction.notes,
        }

        # Update fields on the transaction record
        if data.quantity is not None:
            transaction.quantity = data.quantity
        if data.unit_cost is not None:
            transaction.unit_cost = data.unit_cost
        if data.reference_type is not None:
            # Validate reference_type if provided
            CANONICAL_REF_TYPES = {
                "purchase order": "Purchase Order",
                "sales order": "Sales Order",
                "adjustment": "Adjustment",
                "transfer": "Transfer",
                "return": "Return",
                "opening stock": "Opening Stock",
            }
            ref_type_lower = data.reference_type.lower()
            if ref_type_lower not in CANONICAL_REF_TYPES:
                raise BadRequestException(
                    "Invalid reference_type. Allowed values are: Purchase Order, Sales Order, Adjustment, Transfer, Return, Opening Stock."
                )
            transaction.reference_type = CANONICAL_REF_TYPES[ref_type_lower]
        if data.reference_id is not None:
            transaction.reference_id = data.reference_id
        if data.notes is not None:
            transaction.notes = data.notes

        transaction = await self.transaction_repo.update(transaction)

        # Re-evaluate reorder alerts
        refreshed_item = await self.item_repo.get_by_id(item.id)
        if refreshed_item:
            await self._check_reorder_alert(refreshed_item)

        # Audit log
        new_values = {
            "quantity": transaction.quantity,
            "unit_cost": transaction.unit_cost,
            "reference_type": transaction.reference_type,
            "reference_id": transaction.reference_id,
            "notes": transaction.notes,
        }
        await self.audit_repo.create(
            "update",
            "inventory_transaction",
            user_id=user_id,
            resource_id=str(transaction.id),
            details=f"Updated stock transaction fields. Old: {old_values}, New: {new_values}",
        )

        return StockTransactionResponse.model_validate(transaction)

    async def delete_stock_transaction(self, transaction_id: int, user_id: int) -> None:
        transaction = await self.transaction_repo.get_by_id(transaction_id)
        if not transaction:
            raise NotFoundException("Stock transaction not found")

        # If transaction type is adjustment, raise error
        if transaction.transaction_type == StockTransactionType.ADJUSTMENT:
            raise BadRequestException("Adjustment transactions cannot be deleted to preserve stock checkpoints")

        item = await self.item_repo.get_by_id(transaction.item_id)
        if not item:
            raise NotFoundException("Inventory item associated with transaction not found")

        # Reverse the old transaction impact:
        reverse_delta = 0
        if transaction.transaction_type == StockTransactionType.INWARD:
            reverse_delta = -transaction.quantity
        elif transaction.transaction_type in (
            StockTransactionType.OUTWARD,
            StockTransactionType.CONSUMPTION,
            StockTransactionType.TRANSFER,
        ):
            reverse_delta = transaction.quantity

        # Validate that reversing the old impact does not make inventory negative
        if item.quantity + reverse_delta < 0:
            raise BadRequestException("Insufficient stock to reverse and delete transaction")

        # Apply net delta to the item
        if reverse_delta != 0:
            await self.item_repo.update_quantity(item.id, reverse_delta)

        # Hard delete
        await self.transaction_repo.delete(transaction)

        # Re-evaluate reorder alerts
        refreshed_item = await self.item_repo.get_by_id(item.id)
        if refreshed_item:
            await self._check_reorder_alert(refreshed_item)

        # Audit log
        await self.audit_repo.create(
            "delete",
            "inventory_transaction",
            user_id=user_id,
            resource_id=str(transaction.id),
            details=f"Deleted stock transaction of type '{transaction.transaction_type}' with quantity {transaction.quantity}",
        )

    # --- Vendor Services Removed (Centralized in VendorService) ---

    async def create_warehouse(self, data: WarehouseCreate, user_id: int) -> WarehouseResponse:
        code = data.code
        if code:
            existing = await self.warehouse_repo.get_by_code(code)
            if existing:
                raise ConflictException("Warehouse with this code already exists")
        else:
            while True:
                code = generate_code("WH")
                existing = await self.warehouse_repo.get_by_code(code)
                if not existing:
                    break
        warehouse = Warehouse(code=code, name=data.name, location=data.location, capacity=data.capacity)
        warehouse = await self.warehouse_repo.create(warehouse)
        await self.audit_repo.create("create", "inventory_warehouse", user_id=user_id, resource_id=str(warehouse.id))
        return WarehouseResponse.model_validate(warehouse)

    async def list_warehouses(self, page: int = 1, size: int = 20):
        skip = (page - 1) * size
        items = await self.warehouse_repo.list_all(skip=skip, limit=size)
        total = await self.warehouse_repo.count_all()
        return build_paginated_result([WarehouseResponse.model_validate(w) for w in items], total, page, size)

    async def update_warehouse(self, warehouse_id: int, data: WarehouseUpdate, user_id: int) -> WarehouseResponse:
        from sqlalchemy import select, func
        warehouse = await self.warehouse_repo.get_by_id(warehouse_id)
        if not warehouse:
            raise NotFoundException(f"Warehouse with ID {warehouse_id} not found")

        if data.code:
            existing = await self.warehouse_repo.get_by_code(data.code)
            if existing and existing.id != warehouse_id:
                raise ConflictException("Warehouse with this code already exists")

        if data.name:
            existing_name = await self.db.scalar(
                select(Warehouse).where(
                    func.lower(Warehouse.name) == data.name.strip().lower(),
                    Warehouse.id != warehouse_id,
                    Warehouse.is_deleted.is_(False)
                )
            )
            if existing_name:
                raise ConflictException("Warehouse with this name already exists")

        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(warehouse, key, value)

        warehouse = await self.warehouse_repo.update(warehouse)
        await self.audit_repo.create("update", "inventory_warehouse", user_id=user_id, resource_id=str(warehouse.id))
        return WarehouseResponse.model_validate(warehouse)

    async def delete_warehouse(self, warehouse_id: int, user_id: int) -> None:
        from sqlalchemy import select, func
        warehouse = await self.warehouse_repo.get_by_id(warehouse_id)
        if not warehouse:
            raise NotFoundException(f"Warehouse with ID {warehouse_id} not found")

        # Check active inventory items dependency
        item_exists = await self.db.scalar(
            select(func.count()).select_from(InventoryItem).where(
                InventoryItem.warehouse_id == warehouse_id,
                InventoryItem.is_deleted.is_(False)
            )
        )
        if item_exists and item_exists > 0:
            raise BadRequestException("Cannot delete warehouse as it is linked to one or more active inventory items")

        await self.warehouse_repo.soft_delete(warehouse)
        await self.audit_repo.create("delete", "inventory_warehouse", user_id=user_id, resource_id=str(warehouse.id))

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
        data["total_registered_items"] = await self.item_repo.count_all()
        data["stock_alerts"] = await self.alert_repo.count_active()
        data["active_warehouse_units"] = await self.warehouse_repo.count_active()
        data["total_vendors"] = await self.vendor_repo.count_all()
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

    async def get_warehouse(self, warehouse_id: int) -> WarehouseResponse:
        warehouse = await self.warehouse_repo.get_by_id(warehouse_id)
        if not warehouse:
            raise NotFoundException("Warehouse not found")
        return WarehouseResponse.model_validate(warehouse)

    async def get_transaction(self, transaction_id: int) -> StockTransactionResponse:
        transaction = await self.transaction_repo.get_by_id(transaction_id)
        if not transaction:
            raise NotFoundException("Stock transaction not found")
        return StockTransactionResponse.model_validate(transaction)

    async def get_dashboard_summary(self) -> InventoryDashboardResponse:
        total_registered_items = await self.item_repo.count_all()
        stock_alerts = await self.alert_repo.count_active()
        active_warehouse_units = await self.warehouse_repo.count_active()
        total_vendors = await self.vendor_repo.count_all()
        return InventoryDashboardResponse(
            total_registered_items=total_registered_items,
            stock_alerts=stock_alerts,
            active_warehouse_units=active_warehouse_units,
            total_vendors=total_vendors,
        )

