from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import SoftDeleteMixin, TimestampMixin


class InventoryItem(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "inventory_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    sku: Mapped[str] = mapped_column(String(100), unique=True, index=True)
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

    warehouse: Mapped["Warehouse | None"] = relationship(back_populates="items")
    transactions: Mapped[list["StockTransaction"]] = relationship(back_populates="item")
    department = relationship("Department", back_populates="inventory_items")


class StockTransaction(Base, TimestampMixin):
    __tablename__ = "stock_transactions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    transaction_number: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id"), index=True)
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"), nullable=True)
    transaction_type: Mapped[str] = mapped_column(String(50), index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    unit_cost: Mapped[float] = mapped_column(Float, default=0.0)
    reference_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reference_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    performed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    transaction_date: Mapped[datetime] = mapped_column(DateTime, index=True)

    item: Mapped["InventoryItem"] = relationship(back_populates="transactions")
    warehouse: Mapped["Warehouse | None"] = relationship(back_populates="transactions")


class Vendor(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "vendors"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    contact_person: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    gst_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Warehouse(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "warehouses"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    items: Mapped[list["InventoryItem"]] = relationship(back_populates="warehouse")
    transactions: Mapped[list["StockTransaction"]] = relationship(back_populates="warehouse")


class ReorderAlert(Base, TimestampMixin):
    __tablename__ = "reorder_alerts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id"), index=True)
    current_quantity: Mapped[int] = mapped_column(Integer)
    reorder_level: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(50), default="active", index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    item: Mapped["InventoryItem"] = relationship()
