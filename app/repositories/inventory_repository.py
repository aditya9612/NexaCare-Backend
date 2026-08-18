from datetime import date, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.inventory_model import InventoryItem, ReorderAlert, StockTransaction, Warehouse
from app.models.vendor_model import Vendor
from app.utils.helpers import utc_now


class InventoryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _base_query(self):
        return select(InventoryItem).where(InventoryItem.is_deleted.is_(False))

    async def list_all(
        self, skip: int = 0, limit: int = 20, sort_by: str = "created_at",
        sort_order: str = "desc", category: str | None = None, warehouse_id: int | None = None,
    ) -> list[InventoryItem]:
        query = self._base_query()
        if category:
            query = query.where(InventoryItem.category == category)
        if warehouse_id:
            query = query.where(InventoryItem.warehouse_id == warehouse_id)
        if sort_by not in InventoryItem.__table__.columns:
            column = InventoryItem.created_at
        else:
            column = getattr(InventoryItem, sort_by)
        query = query.order_by(column.desc() if sort_order == "desc" else column.asc())
        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_all(self, category: str | None = None, warehouse_id: int | None = None) -> int:
        query = select(func.count()).select_from(InventoryItem).where(InventoryItem.is_deleted.is_(False))
        if category:
            query = query.where(InventoryItem.category == category)
        if warehouse_id:
            query = query.where(InventoryItem.warehouse_id == warehouse_id)
        return (await self.db.scalar(query)) or 0

    async def search(self, q: str, skip: int = 0, limit: int = 20) -> list[InventoryItem]:
        pattern = f"%{q.lower()}%"
        query = self._base_query().where(
            or_(
                func.lower(InventoryItem.name).like(pattern),
                func.lower(InventoryItem.sku).like(pattern),
                func.lower(InventoryItem.barcode).like(pattern),
            )
        )
        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_search(self, q: str) -> int:
        pattern = f"%{q.lower()}%"
        return (await self.db.scalar(
            select(func.count()).select_from(InventoryItem).where(
                InventoryItem.is_deleted.is_(False),
                or_(
                    func.lower(InventoryItem.name).like(pattern),
                    func.lower(InventoryItem.sku).like(pattern),
                ),
            )
        )) or 0

    async def get_by_id(self, item_id: int) -> InventoryItem | None:
        result = await self.db.execute(self._base_query().where(InventoryItem.id == item_id))
        return result.scalar_one_or_none()

    async def get_by_id_for_update(self, item_id: int) -> InventoryItem | None:
        result = await self.db.execute(
            self._base_query().where(InventoryItem.id == item_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_by_sku(self, sku: str) -> InventoryItem | None:
        result = await self.db.execute(
            self._base_query().where(func.lower(InventoryItem.sku) == sku.lower())
        )
        return result.scalar_one_or_none()

    async def get_by_barcode(self, barcode: str) -> InventoryItem | None:
        result = await self.db.execute(
            self._base_query().where(func.lower(InventoryItem.barcode) == barcode.lower())
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> InventoryItem | None:
        result = await self.db.execute(
            self._base_query().where(func.lower(InventoryItem.name) == name.strip().lower())
        )
        return result.scalar_one_or_none()

    async def create(self, item: InventoryItem) -> InventoryItem:
        self.db.add(item)
        await self.db.flush()
        await self.db.refresh(item)
        return item

    async def update(self, item: InventoryItem) -> InventoryItem:
        await self.db.flush()
        await self.db.refresh(item)
        return item

    async def soft_delete(self, item: InventoryItem) -> None:
        item.is_deleted = True
        item.deleted_at = utc_now()
        await self.db.flush()

    async def get_all_active(self) -> list[InventoryItem]:
        query = self._base_query().order_by(InventoryItem.name.asc())
        result = await self.db.execute(query)
        return list(result.scalars().all())


    async def update_quantity(self, item_id: int, delta: int) -> InventoryItem | None:
        item = await self.get_by_id(item_id)
        if item:
            item.quantity = max(0, item.quantity + delta)
            await self.db.flush()
            await self.db.refresh(item)
        return item

    async def get_stock_summary(self) -> dict:
        total_items = await self.db.scalar(
            select(func.count()).select_from(InventoryItem).where(InventoryItem.is_deleted.is_(False))
        )
        total_qty = await self.db.scalar(
            select(func.coalesce(func.sum(InventoryItem.quantity), 0)).where(InventoryItem.is_deleted.is_(False))
        )
        low_stock = await self.db.scalar(
            select(func.count()).select_from(InventoryItem).where(
                InventoryItem.is_deleted.is_(False),
                InventoryItem.quantity <= InventoryItem.reorder_level,
            )
        )
        expired = await self.db.scalar(
            select(func.count()).select_from(InventoryItem).where(
                InventoryItem.is_deleted.is_(False),
                InventoryItem.expiry_date.isnot(None),
                InventoryItem.expiry_date < date.today(),
            )
        )
        total_value = await self.db.scalar(
            select(func.coalesce(func.sum(InventoryItem.quantity * InventoryItem.unit_cost), 0)).where(
                InventoryItem.is_deleted.is_(False)
            )
        )
        return {
            "total_items": total_items or 0,
            "total_quantity": int(total_qty or 0),
            "low_stock_count": low_stock or 0,
            "expired_count": expired or 0,
            "total_value": float(total_value or 0),
        }


class StockTransactionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all(
        self, skip: int = 0, limit: int = 20, item_id: int | None = None,
        transaction_type: str | None = None,
    ) -> list[StockTransaction]:
        query = select(StockTransaction)
        if item_id:
            query = query.where(StockTransaction.item_id == item_id)
        if transaction_type:
            query = query.where(StockTransaction.transaction_type == transaction_type)
        result = await self.db.execute(
            query.order_by(StockTransaction.transaction_date.desc()).offset(skip).limit(limit)
        )
        return list(result.scalars().all())

    async def count_all(self, item_id: int | None = None, transaction_type: str | None = None) -> int:
        query = select(func.count()).select_from(StockTransaction)
        if item_id:
            query = query.where(StockTransaction.item_id == item_id)
        if transaction_type:
            query = query.where(StockTransaction.transaction_type == transaction_type)
        return (await self.db.scalar(query)) or 0

    async def get_by_id(self, transaction_id: int) -> StockTransaction | None:
        result = await self.db.execute(
            select(StockTransaction).where(StockTransaction.id == transaction_id)
        )
        return result.scalar_one_or_none()

    async def get_by_reference(self, reference_type: str, reference_id: int) -> StockTransaction | None:
        result = await self.db.execute(
            select(StockTransaction).where(
                StockTransaction.reference_type == reference_type,
                StockTransaction.reference_id == reference_id
            )
        )
        return result.scalar_one_or_none()


    async def create(self, transaction: StockTransaction) -> StockTransaction:
        self.db.add(transaction)
        await self.db.flush()
        await self.db.refresh(transaction)
        return transaction

    async def update(self, transaction: StockTransaction) -> StockTransaction:
        await self.db.flush()
        await self.db.refresh(transaction)
        return transaction

    async def delete(self, transaction: StockTransaction) -> None:
        await self.db.delete(transaction)
        await self.db.flush()

    async def get_consumption_report(self, start, end) -> list[dict]:
        result = await self.db.execute(
            select(
                StockTransaction.item_id,
                InventoryItem.name,
                InventoryItem.sku,
                func.sum(StockTransaction.quantity),
                func.sum(StockTransaction.quantity * StockTransaction.unit_cost),
            )
            .join(InventoryItem, InventoryItem.id == StockTransaction.item_id)
            .where(
                StockTransaction.transaction_type == "consumption",
                StockTransaction.transaction_date >= start,
                StockTransaction.transaction_date <= end,
            )
            .group_by(StockTransaction.item_id, InventoryItem.name, InventoryItem.sku)
        )
        return [
            {
                "item_id": row[0],
                "item_name": row[1],
                "sku": row[2],
                "total_consumed": int(row[3]),
                "total_value": float(row[4] or 0),
            }
            for row in result.all()
        ]


# --- VendorRepository removed (use central VendorRepository instead) ---


class WarehouseRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all(self, skip: int = 0, limit: int = 20) -> list[Warehouse]:
        result = await self.db.execute(
            select(Warehouse)
            .where(Warehouse.is_deleted.is_(False))
            .order_by(Warehouse.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_all(self) -> int:
        return (await self.db.scalar(
            select(func.count()).select_from(Warehouse).where(Warehouse.is_deleted.is_(False))
        )) or 0

    async def count_active(self) -> int:
        return (await self.db.scalar(
            select(func.count()).select_from(Warehouse).where(
                Warehouse.is_deleted.is_(False),
                Warehouse.is_active.is_(True)
            )
        )) or 0

    async def count_inactive(self) -> int:
        return (await self.db.scalar(
            select(func.count()).select_from(Warehouse).where(
                Warehouse.is_deleted.is_(False),
                Warehouse.is_active.is_(False)
            )
        )) or 0

    async def get_by_id(self, warehouse_id: int) -> Warehouse | None:
        result = await self.db.execute(
            select(Warehouse).where(Warehouse.id == warehouse_id, Warehouse.is_deleted.is_(False))
        )
        return result.scalar_one_or_none()

    async def get_by_code(self, code: str) -> Warehouse | None:
        result = await self.db.execute(
            select(Warehouse).where(func.lower(Warehouse.code) == code.lower(), Warehouse.is_deleted.is_(False))
        )
        return result.scalar_one_or_none()

    async def create(self, warehouse: Warehouse) -> Warehouse:
        self.db.add(warehouse)
        await self.db.flush()
        await self.db.refresh(warehouse)
        return warehouse

    async def update(self, warehouse: Warehouse) -> Warehouse:
        await self.db.flush()
        await self.db.refresh(warehouse)
        return warehouse

    async def soft_delete(self, warehouse: Warehouse) -> None:
        warehouse.is_deleted = True
        warehouse.deleted_at = utc_now()
        warehouse.is_active = False
        await self.db.flush()


class ReorderAlertRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_active(self, skip: int = 0, limit: int = 50) -> list[ReorderAlert]:
        result = await self.db.execute(
            select(ReorderAlert)
            .where(ReorderAlert.status == "active")
            .order_by(ReorderAlert.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_active(self) -> int:
        return (await self.db.scalar(
            select(func.count()).select_from(ReorderAlert).where(ReorderAlert.status == "active")
        )) or 0

    async def create(self, alert: ReorderAlert) -> ReorderAlert:
        self.db.add(alert)
        await self.db.flush()
        await self.db.refresh(alert)
        return alert

    async def resolve_for_item(self, item_id: int) -> None:
        result = await self.db.execute(
            select(ReorderAlert).where(ReorderAlert.item_id == item_id, ReorderAlert.status == "active")
        )
        for alert in result.scalars().all():
            alert.status = "resolved"
            alert.resolved_at = utc_now()
        await self.db.flush()
