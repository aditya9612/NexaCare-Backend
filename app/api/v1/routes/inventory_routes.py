from fastapi import APIRouter, Depends

from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.models.user_model import User
from app.schemas.common_schema import APIResponse, MessageResponse
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
    WarehouseCreate,
    WarehouseResponse,
    WarehouseUpdate,
)
from app.services.inventory_service import InventoryService
from app.utils.pagination import PaginatedResult

router = APIRouter()


# --- Items ---
@router.post("/items", response_model=APIResponse[InventoryItemResponse], status_code=201)
async def create_inventory_item(
    data: InventoryItemCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("inventory", "create")),
):
    item = await InventoryService(db).create_item(data, current_user.id)
    return APIResponse(message="Inventory item created", data=item)


@router.get("/items", response_model=APIResponse[PaginatedResult[InventoryItemResponse]])
async def list_inventory_items(
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    category: str | None = None,
    warehouse_id: int | None = None,
    q: str | None = None,
    _: User = Depends(require_permission("inventory", "read")),
):
    service = InventoryService(db)
    if q:
        result = await service.search_items(q, page=page, size=size)
    else:
        result = await service.list_items(
            page=page, size=size, sort_by=sort_by, sort_order=sort_order,
            category=category, warehouse_id=warehouse_id,
        )
    return APIResponse(message="Inventory items retrieved", data=result)


@router.get("/items/{item_id}", response_model=APIResponse[InventoryItemResponse])
async def get_inventory_item(
    item_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("inventory", "read")),
):
    item = await InventoryService(db).get_item(item_id)
    return APIResponse(message="Inventory item retrieved", data=item)


@router.put("/items/{item_id}", response_model=APIResponse[InventoryItemResponse])
async def update_inventory_item(
    item_id: int,
    data: InventoryItemUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("inventory", "update")),
):
    item = await InventoryService(db).update_item(item_id, data, current_user.id)
    return APIResponse(message="Inventory item updated", data=item)


@router.delete("/items/{item_id}", response_model=APIResponse[MessageResponse])
async def delete_inventory_item(
    item_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("inventory", "delete")),
):
    await InventoryService(db).delete_item(item_id, current_user.id)
    return APIResponse(message="Inventory item deleted", data=MessageResponse(message="Soft deleted"))


# --- Transactions ---
@router.post("/transactions", response_model=APIResponse[StockTransactionResponse], status_code=201)
async def create_stock_transaction(
    data: StockTransactionCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("inventory", "create")),
):
    transaction = await InventoryService(db).create_transaction(data, current_user.id)
    return APIResponse(message="Stock transaction created", data=transaction)


@router.get("/transactions", response_model=APIResponse[PaginatedResult[StockTransactionResponse]])
async def list_stock_transactions(
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    item_id: int | None = None,
    transaction_type: str | None = None,
    _: User = Depends(require_permission("inventory", "read")),
):
    result = await InventoryService(db).list_transactions(
        page=page, size=size, item_id=item_id, transaction_type=transaction_type
    )
    return APIResponse(message="Stock transactions retrieved", data=result)


@router.get("/stock-transactions/{transaction_id}", response_model=APIResponse[StockTransactionResponse])
async def get_stock_transaction(
    transaction_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("inventory", "read")),
):
    transaction = await InventoryService(db).get_transaction(transaction_id)
    return APIResponse(message="Stock transaction retrieved", data=transaction)


@router.put("/stock-transactions/{transaction_id}", response_model=APIResponse[StockTransactionResponse])
async def update_stock_transaction(
    transaction_id: int,
    data: StockTransactionUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("inventory", "update")),
):
    transaction = await InventoryService(db).update_transaction(transaction_id, data, current_user.id)
    return APIResponse(message="Stock transaction updated", data=transaction)


@router.delete("/stock-transactions/{transaction_id}", response_model=APIResponse[MessageResponse])
async def delete_stock_transaction(
    transaction_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("inventory", "delete")),
):
    await InventoryService(db).delete_stock_transaction(transaction_id, current_user.id)
    return APIResponse(message="Stock transaction deleted", data=MessageResponse(message="Deleted successfully"))


# --- Vendors Removed (moved to unified /vendors API) ---


# --- Warehouses ---
@router.post("/warehouses", response_model=APIResponse[WarehouseResponse], status_code=201)
async def create_warehouse(
    data: WarehouseCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("inventory", "create")),
):
    warehouse = await InventoryService(db).create_warehouse(data, current_user.id)
    return APIResponse(message="Warehouse created", data=warehouse)


@router.get("/warehouses", response_model=APIResponse[PaginatedResult[WarehouseResponse]])
async def list_warehouses(
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    _: User = Depends(require_permission("inventory", "read")),
):
    result = await InventoryService(db).list_warehouses(page=page, size=size)
    return APIResponse(message="Warehouses retrieved", data=result)


@router.get("/warehouses/{warehouse_id}", response_model=APIResponse[WarehouseResponse])
async def get_warehouse(
    warehouse_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("inventory", "read")),
):
    warehouse = await InventoryService(db).get_warehouse(warehouse_id)
    return APIResponse(message="Warehouse retrieved", data=warehouse)


@router.put("/warehouses/{warehouse_id}", response_model=APIResponse[WarehouseResponse])
async def update_warehouse(
    warehouse_id: int,
    data: WarehouseUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("inventory", "update")),
):
    warehouse = await InventoryService(db).update_warehouse(warehouse_id, data, current_user.id)
    return APIResponse(message="Warehouse updated", data=warehouse)


@router.delete("/warehouses/{warehouse_id}", response_model=APIResponse[MessageResponse])
async def delete_warehouse(
    warehouse_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("inventory", "delete")),
):
    await InventoryService(db).delete_warehouse(warehouse_id, current_user.id)
    return APIResponse(message="Warehouse deleted", data=MessageResponse(message="Soft deleted"))


# --- Reports & Alerts ---
@router.get("/reorder-alerts", response_model=APIResponse[list[ReorderAlertResponse]])
async def reorder_alerts(
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 50,
    _: User = Depends(require_permission("inventory", "read")),
):
    alerts = await InventoryService(db).get_reorder_alerts(page=page, size=size)
    return APIResponse(message="Reorder alerts", data=alerts)


@router.get("/stock-summary", response_model=APIResponse[StockSummary])
async def stock_summary(
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("inventory", "read")),
):
    summary = await InventoryService(db).get_stock_summary()
    return APIResponse(message="Stock summary", data=summary)


@router.get("/consumption-reports", response_model=APIResponse[list[ConsumptionReport]])
async def consumption_report(
    db: DbSession,
    current_user: CurrentUser,
    period: str = "monthly",
    _: User = Depends(require_permission("inventory", "read")),
):
    report = await InventoryService(db).get_consumption_report(period=period)
    return APIResponse(message="Consumption report", data=report)
