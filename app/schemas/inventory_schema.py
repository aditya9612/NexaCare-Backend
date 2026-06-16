from datetime import date, datetime
from typing import List, Optional

from pydantic import Field

from app.schemas.common_schema import BaseSchema


class InventoryItemCreate(BaseSchema):
    name: str
    sku: str | None = None
    barcode: str | None = None
    category: str
    quantity: int = Field(0, ge=0)
    unit: str
    unit_cost: float = Field(0.0, ge=0)
    reorder_level: int = Field(10, ge=0)
    expiry_date: date | None = None
    warehouse_id: int | None = None
    vendor_id: int | None = None
    department_id: int | None = None
    description: str | None = None


class InventoryItemUpdate(BaseSchema):
    name: str | None = None
    barcode: str | None = None
    category: str | None = None
    quantity: int | None = Field(None, ge=0)
    unit: str | None = None
    unit_cost: float | None = Field(None, ge=0)
    reorder_level: int | None = Field(None, ge=0)
    expiry_date: date | None = None
    warehouse_id: int | None = None
    vendor_id: int | None = None
    department_id: int | None = None
    description: str | None = None
    is_active: bool | None = None


class InventoryItemResponse(BaseSchema):
    id: int
    name: str
    sku: str
    barcode: str | None
    category: str
    quantity: int
    unit: str
    unit_cost: float
    reorder_level: int
    expiry_date: date | None
    warehouse_id: int | None
    vendor_id: int | None
    department_id: int | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class StockTransactionCreate(BaseSchema):
    item_id: int
    warehouse_id: int | None = None
    transaction_type: str
    quantity: int = Field(..., ge=1)
    unit_cost: float = Field(0.0, ge=0)
    reference_type: str | None = None
    reference_id: int | None = None
    notes: str | None = None
    target_warehouse_id: int | None = None


class StockTransactionResponse(BaseSchema):
    id: int
    transaction_number: str
    item_id: int
    warehouse_id: int | None
    transaction_type: str
    quantity: int
    unit_cost: float
    reference_type: str | None
    reference_id: int | None
    notes: str | None
    transaction_date: datetime
    created_at: datetime


class VendorCreate(BaseSchema):
    name: str
    contact_person: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    gst_number: str | None = None


class VendorUpdate(BaseSchema):
    name: str | None = None
    contact_person: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    gst_number: str | None = None
    is_active: bool | None = None


class VendorResponse(BaseSchema):
    id: int
    name: str
    contact_person: str | None
    phone: str | None
    email: str | None
    address: str | None
    gst_number: str | None
    is_active: bool
    created_at: datetime


class WarehouseCreate(BaseSchema):
    name: str
    code: str | None = None
    location: str | None = None
    capacity: int | None = Field(None, ge=0)


class WarehouseUpdate(BaseSchema):
    name: str | None = None
    location: str | None = None
    capacity: int | None = Field(None, ge=0)
    is_active: bool | None = None


class WarehouseResponse(BaseSchema):
    id: int
    name: str
    code: str
    location: str | None
    capacity: int | None
    is_active: bool
    created_at: datetime


class ReorderAlertResponse(BaseSchema):
    id: int
    item_id: int
    item_name: str
    sku: str
    current_quantity: int
    reorder_level: int
    status: str
    created_at: datetime


class StockSummary(BaseSchema):
    total_items: int
    total_quantity: int
    low_stock_count: int
    expired_count: int
    total_value: float


class ConsumptionReport(BaseSchema):
    period: str
    item_id: int
    item_name: str
    sku: str
    total_consumed: int
    total_value: float
