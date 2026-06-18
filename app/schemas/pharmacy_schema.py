from datetime import date, datetime
from typing import List, Optional

from pydantic import Field

from app.schemas.common_schema import BaseSchema


class MedicineCreate(BaseSchema):
    name: str
    generic_name: str | None = None
    barcode: str | None = None
    category: str
    unit: str
    unit_price: float = Field(0.0, ge=0)
    stock_quantity: int = Field(0, ge=0)
    reorder_level: int = Field(10, ge=0)
    expiry_date: date | None = None
    manufacturer: str | None = None
    description: str | None = None


class MedicineUpdate(BaseSchema):
    name: str | None = None
    generic_name: str | None = None
    barcode: str | None = None
    category: str | None = None
    unit: str | None = None
    unit_price: float | None = Field(None, ge=0)
    stock_quantity: int | None = Field(None, ge=0)
    reorder_level: int | None = Field(None, ge=0)
    expiry_date: date | None = None
    manufacturer: str | None = None
    description: str | None = None
    is_active: bool | None = None


class MedicineResponse(BaseSchema):
    id: int
    name: str
    generic_name: str | None
    barcode: str | None
    sku: str
    category: str
    unit: str
    unit_price: float
    stock_quantity: int
    reorder_level: int
    expiry_date: date | None
    manufacturer: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class PrescriptionItemCreate(BaseSchema):
    medicine_id: int
    dosage: str
    frequency: str
    duration_days: int = Field(1, ge=1)
    quantity: int = Field(1, ge=1)
    instructions: str | None = None


class PrescriptionCreate(BaseSchema):
    patient_id: int
    doctor_id: int
    appointment_id: int | None = None
    instructions: str | None = None
    items: List[PrescriptionItemCreate] = Field(default_factory=list)
    

class PrescriptionItemUpdate(BaseSchema):
    medicine_id: int
    dosage: str
    frequency: str
    duration_days: int = Field(1, ge=1)
    quantity: int = Field(1, ge=1)
    instructions: str | None = None


class PrescriptionUpdate(BaseSchema):
    instructions: str | None = None
    items: List[PrescriptionItemUpdate] | None = None    


class PrescriptionItemResponse(BaseSchema):
    id: int
    prescription_id: int
    medicine_id: int
    dosage: str
    frequency: str
    duration_days: int
    quantity: int
    instructions: str | None


class PrescriptionResponse(BaseSchema):
    id: int
    patient_id: int
    doctor_id: int
    appointment_id: int | None
    prescription_number: str
    status: str
    instructions: str | None
    items: List[PrescriptionItemResponse] = []
    dispensed_at: datetime | None
    created_at: datetime


class PharmacyInvoiceItemCreate(BaseSchema):
    medicine_id: int
    quantity: int = Field(1, ge=1)
    unit_price: float | None = Field(None, ge=0)


class PharmacyInvoiceCreate(BaseSchema):
    patient_id: int | None = None
    prescription_id: int | None = None
    discount_amount: float = Field(0.0, ge=0)
    items: List[PharmacyInvoiceItemCreate] = Field(..., min_length=1)


class PharmacyInvoiceItemResponse(BaseSchema):
    id: int
    invoice_id: int
    medicine_id: int
    quantity: int
    unit_price: float
    line_total: float


class PharmacyInvoiceResponse(BaseSchema):
    id: int
    invoice_number: str
    patient_id: int | None
    prescription_id: int | None
    subtotal: float
    discount_amount: float
    gst_amount: float
    total_amount: float
    paid_amount: float
    status: str
    items: List[PharmacyInvoiceItemResponse] = []
    created_at: datetime


class SupplierCreate(BaseSchema):
    name: str
    contact_person: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    gst_number: str | None = None


class SupplierUpdate(BaseSchema):
    name: str | None = None
    contact_person: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    gst_number: str | None = None
    is_active: bool | None = None


class SupplierResponse(BaseSchema):
    id: int
    name: str
    contact_person: str | None
    phone: str | None
    email: str | None
    address: str | None
    gst_number: str | None
    is_active: bool
    created_at: datetime


class PurchaseItemCreate(BaseSchema):
    medicine_id: int
    quantity: int = Field(..., ge=1)
    unit_price: float = Field(..., ge=0)
    expiry_date: date | None = None


class PurchaseCreate(BaseSchema):
    supplier_id: int
    notes: str | None = None
    items: List[PurchaseItemCreate] = Field(..., min_length=1)


class PurchaseItemResponse(BaseSchema):
    id: int
    purchase_id: int
    medicine_id: int
    quantity: int
    unit_price: float
    expiry_date: date | None
    line_total: float


class PurchaseResponse(BaseSchema):
    id: int
    purchase_number: str
    supplier_id: int
    total_amount: float
    status: str
    ordered_at: datetime
    received_at: datetime | None
    notes: str | None
    items: List[PurchaseItemResponse] = []
    created_at: datetime


class LowStockAlert(BaseSchema):
    medicine_id: int
    name: str
    sku: str
    stock_quantity: int
    reorder_level: int


class ExpiryAlert(BaseSchema):
    medicine_id: int
    name: str
    sku: str
    expiry_date: date
    stock_quantity: int
    days_until_expiry: int


class SalesReport(BaseSchema):
    period: str
    total_sales: float
    invoice_count: int
    top_medicines: List[dict]
