from datetime import date, datetime
import re
from typing import List, Optional

from pydantic import Field, field_validator


def validate_gst_number(v: str | None) -> str | None:
    if v is None:
        return v
    cleaned = v.strip().upper()
    if not cleaned or cleaned.lower() == "null":
        raise ValueError("GST number cannot be blank or 'null'")
    if len(cleaned) != 15:
        raise ValueError("GST number must be exactly 15 characters long")
    
    # State code: 01-38
    # Next 5: letters
    # Next 4: digits
    # Next 1: letter
    # Next 1: alphanumeric
    # Next 1: letter
    # Next 1: alphanumeric
    pattern = r"^(0[1-9]|[1-2][0-9]|3[0-8])[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9][A-Z][A-Z0-9]$"
    if not re.match(pattern, cleaned):
        raise ValueError("Invalid GST number format")
    return cleaned


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

    @field_validator("barcode")
    @classmethod
    def validate_barcode(cls, v: str | None) -> str | None:
        if v is not None:
            if " " in v:
                raise ValueError("Barcode cannot contain spaces")
            if not v.isdigit():
                raise ValueError("Barcode must contain only numeric characters")
            if len(v) != 13:
                raise ValueError("Barcode must be exactly 13 digits")
            if all(c == "0" for c in v):
                raise ValueError("Barcode cannot be all zeros")
        return v

    @field_validator("expiry_date")
    @classmethod
    def validate_expiry_date(cls, v: date | None) -> date | None:
        if v is not None and v < date.today():
            raise ValueError("Expiry date cannot be in the past")
        return v

    @field_validator("name", "generic_name", "category")
    @classmethod
    def validate_non_blank_strings(cls, v: str | None) -> str | None:
        if v is not None:
            if v.strip() == "":
                raise ValueError("cannot be empty or only spaces")
            return v.strip()
        return v


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

    @field_validator("barcode")
    @classmethod
    def validate_barcode(cls, v: str | None) -> str | None:
        if v is not None:
            if " " in v:
                raise ValueError("Barcode cannot contain spaces")
            if not v.isdigit():
                raise ValueError("Barcode must contain only numeric characters")
            if len(v) != 13:
                raise ValueError("Barcode must be exactly 13 digits")
            if all(c == "0" for c in v):
                raise ValueError("Barcode cannot be all zeros")
        return v

    @field_validator("expiry_date")
    @classmethod
    def validate_expiry_date(cls, v: date | None) -> date | None:
        if v is not None and v < date.today():
            raise ValueError("Expiry date cannot be in the past")
        return v

    @field_validator("name", "generic_name", "category")
    @classmethod
    def validate_non_blank_strings(cls, v: str | None) -> str | None:
        if v is not None:
            if v.strip() == "":
                raise ValueError("cannot be empty or only spaces")
            return v.strip()
        return v


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
    description: str | None = None
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


class PrescriptionUpdate(BaseSchema):
    instructions: str | None = None
    status: str | None = None

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


class PharmacyInvoiceCreate(BaseSchema):
    patient_id: int
    prescription_id: int
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

    @field_validator("gst_number")
    @classmethod
    def validate_supplier_gst(cls, v: str | None) -> str | None:
        return validate_gst_number(v)



class SupplierUpdate(BaseSchema):
    name: str | None = None
    contact_person: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    gst_number: str | None = None
    is_active: bool | None = None

    @field_validator("gst_number")
    @classmethod
    def validate_supplier_gst(cls, v: str | None) -> str | None:
        return validate_gst_number(v)



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
