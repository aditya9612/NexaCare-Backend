from datetime import date, datetime

from sqlalchemy import UniqueConstraint, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import SoftDeleteMixin, TimestampMixin


class InventoryItem(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "inventory_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    sku: Mapped[str] = mapped_column(String(100), unique=False, index=True)
    barcode: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True, index=True)
    category: Mapped[str] = mapped_column(String(100), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    unit: Mapped[str] = mapped_column(String(50))
    unit_cost: Mapped[float] = mapped_column(Float, default=0.0)
    reorder_level: Mapped[int] = mapped_column(Integer, default=10)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"), nullable=True, index=True)
    vendor_id: Mapped[int | None] = mapped_column(ForeignKey("vendors.id"), nullable=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.department_id"), nullable=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


    warehouse: Mapped["Warehouse | None"] = relationship("Warehouse", back_populates="items")
    transactions: Mapped[list["StockTransaction"]] = relationship("StockTransaction", back_populates="item")
    department = relationship("Department", back_populates="inventory_items")
    vendor: Mapped["Vendor | None"] = relationship("Vendor", back_populates="items")
    batches: Mapped[list["ItemBatch"]] = relationship("ItemBatch", back_populates="item")
    warehouse_stocks: Mapped[list["WarehouseStock"]] = relationship("WarehouseStock", back_populates="item")


class StockTransaction(Base, TimestampMixin):
    __tablename__ = "stock_transactions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    transaction_number: Mapped[str] = mapped_column(String(50), unique=False, index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id"), index=True)
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"), nullable=True)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("item_batches.id"), nullable=True, index=True)
    transaction_type: Mapped[str] = mapped_column(String(50), index=True)
    direction: Mapped[str | None] = mapped_column(String(10), nullable=True) # IN or OUT
    quantity: Mapped[int] = mapped_column(Integer)
    balance_before: Mapped[int | None] = mapped_column(Integer, nullable=True)
    balance_after: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unit_cost: Mapped[float] = mapped_column(Float, default=0.0)
    reference_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reference_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    performed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    transaction_date: Mapped[datetime] = mapped_column(DateTime, index=True)

    item: Mapped["InventoryItem"] = relationship("InventoryItem", back_populates="transactions")
    warehouse: Mapped["Warehouse | None"] = relationship("Warehouse", back_populates="transactions")
    batch: Mapped["ItemBatch | None"] = relationship("ItemBatch")


class Warehouse(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "warehouses"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    code: Mapped[str] = mapped_column(String(50), unique=False, index=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    hospital_id: Mapped[int | None] = mapped_column(ForeignKey("hospitals.id"), nullable=True)

    items: Mapped[list["InventoryItem"]] = relationship("InventoryItem", back_populates="warehouse")
    transactions: Mapped[list["StockTransaction"]] = relationship("StockTransaction", back_populates="warehouse")
    stocks: Mapped[list["WarehouseStock"]] = relationship("WarehouseStock", back_populates="warehouse")


class ReorderAlert(Base, TimestampMixin):
    __tablename__ = "reorder_alerts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id"), index=True)
    current_quantity: Mapped[int] = mapped_column(Integer)
    reorder_level: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(50), default="active", index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    item: Mapped["InventoryItem"] = relationship()


class ItemBatch(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "item_batches"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    inventory_item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id"), index=True)
    batch_number: Mapped[str | None] = mapped_column(String(100), index=True, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    manufacturing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    purchase_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    mrp: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)

    item: Mapped["InventoryItem"] = relationship("InventoryItem", back_populates="batches")


class WarehouseStock(Base, TimestampMixin):
    __tablename__ = "warehouse_stock"

    __table_args__ = (
        UniqueConstraint("warehouse_id", "inventory_item_id", name="uq_warehouse_item"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), index=True)
    inventory_item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)

    warehouse: Mapped["Warehouse"] = relationship("Warehouse", back_populates="stocks")
    item: Mapped["InventoryItem"] = relationship("InventoryItem", back_populates="warehouse_stocks")
