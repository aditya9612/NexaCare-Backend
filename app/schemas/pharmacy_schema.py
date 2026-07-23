from datetime import date, datetime
import re
from typing import List, Optional

from pydantic import EmailStr, Field, field_validator

from app.schemas.common_schema import BaseSchema
from app.utils.validators import validate_gst_number


def validate_supplier_name(v: str | None) -> str | None:
    if v is None:
        return v
    if not v or not v.strip() or v.lower() == "null" or v.lower() == "string":
        raise ValueError("Supplier name cannot be blank, 'null', or 'string'")
    if v.startswith(" ") or v.endswith(" "):
        raise ValueError("Supplier name must not contain leading or trailing spaces")
    if "  " in v:
        raise ValueError("Supplier name must not contain multiple consecutive spaces")
    if not v.isascii():
        raise ValueError("Supplier name must contain only standard ASCII characters")
    if not re.match(r"^[a-zA-Z\s\-\'\.\&\,\(\)]+$", v):
        raise ValueError("Supplier name must contain only alphabetic characters, spaces, hyphens, dots, ampersands, or parentheses")
    return v


def validate_contact_person(v: str | None) -> str | None:
    if v is None:
        return v
    if not v.strip() or v.lower() == "null" or v.lower() == "string":
        raise ValueError("Contact person cannot be blank, 'null', or 'string'")
    if v.startswith(" ") or v.endswith(" "):
        raise ValueError("Contact person must not contain leading or trailing spaces")
    if "  " in v:
        raise ValueError("Contact person must not contain multiple consecutive spaces")
    if not v.isascii():
        raise ValueError("Contact person must contain only standard ASCII characters")
    if not re.match(r"^[a-zA-Z\s\-\'\.]+$", v):
        raise ValueError("Contact person must contain only alphabetic characters, spaces, hyphens, dots, or apostrophes")
    return v


def validate_supplier_phone(v: str | None) -> str | None:
    if v is None:
        return v
    if not v.strip() or v.lower() == "null" or v.lower() == "string":
        raise ValueError("Phone number cannot be blank, 'null', or 'string'")
    if v.startswith(" ") or v.endswith(" "):
        raise ValueError("Phone number should not contain leading or trailing spaces")
    if " " in v:
        raise ValueError("Phone number should not contain spaces")
        
    raw_num = v
    if v.startswith("+91"):
        raw_num = v[3:]
    elif v.startswith("91") and len(v) == 12:
        raw_num = v[2:]
        
    if len(raw_num) != 10:
        raise ValueError("Phone number must contain exactly 10 digits")
        
    if not raw_num.isdigit():
        raise ValueError("Phone number must contain only numeric digits")
        
    if raw_num[0] not in {"6", "7", "8", "9"}:
        raise ValueError("Phone number must start with 6, 7, 8, or 9")
        
    if len(set(raw_num)) == 1:
        raise ValueError("Phone number cannot consist of repeated identical digits")
        
    return "+91" + raw_num


def validate_supplier_address(v: str | None) -> str | None:
    if v is None:
        return v
    if not v.strip() or v.lower() == "null" or v.lower() == "string":
        raise ValueError("Address cannot be blank, 'null', or 'string'")
    if v.startswith(" ") or v.endswith(" "):
        raise ValueError("Address must not contain leading or trailing spaces")
    return v.strip()


class MedicineCreate(BaseSchema):
    name: str
    generic_name: str | None = None
    barcode: str | None = None
    batch_number: str | None = None
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
    batch_number: str | None = None
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
    batch_number: str | None
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
    appointment_id: int
    instructions: str | None = None
    items: List[PrescriptionItemCreate] = Field(..., min_length=1)


class PrescriptionItemUpdate(BaseSchema):
    medicine_id: int
    dosage: str
    frequency: str
    duration_days: int = Field(1, ge=1)
    quantity: int = Field(1, ge=1)
    instructions: str | None = None



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


class PrescriptionUpdate(BaseSchema):
    patient_id: Optional[int] = None
    instructions: Optional[str] = None
    status: Optional[str] = None
    items: Optional[List[PrescriptionItemCreate]] = None


class PharmacyInvoiceItemCreate(BaseSchema):
    medicine_id: int = Field(..., gt=0)
    quantity: int = Field(1, ge=1)
    unit_price: float | None = Field(None, ge=0)


class PharmacyInvoiceCreate(BaseSchema):
    patient_id: int | None = Field(None, gt=0)
    prescription_id: int | None = Field(None, gt=0)
    payment_mode: str | None = Field("Cash", description="Payment mode (Cash, Card, UPI, Net Banking, Online, etc.)")
    discount_amount: float = Field(0.0, ge=0)
    discount_percentage: float = Field(0.0, ge=0, le=100)
    tax_percentage: float = Field(0.0, ge=0, le=100)
    tax_amount: float = Field(0.0, ge=0)
    items: List[PharmacyInvoiceItemCreate] = Field(..., min_length=1)


class PharmacyInvoiceUpdate(BaseSchema):
    patient_id: Optional[int] = Field(None, gt=0)
    prescription_id: Optional[int] = Field(None, gt=0)
    payment_mode: Optional[str] = Field(None, description="Payment mode (Cash, Card, UPI, Net Banking, Online, etc.)")
    discount_amount: Optional[float] = Field(None, ge=0)
    discount_percentage: Optional[float] = Field(None, ge=0, le=100)
    tax_percentage: Optional[float] = Field(None, ge=0, le=100)
    tax_amount: Optional[float] = Field(None, ge=0)
    status: Optional[str] = None
    items: Optional[List[PharmacyInvoiceItemCreate]] = None


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
    payment_mode: str | None = "Cash"
    subtotal: float
    discount_percentage: float | None = 0.0
    discount_amount: float
    tax_percentage: float | None = 0.0
    tax_amount: float | None = 0.0
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
    email: EmailStr | None = None
    address: str | None = None
    gst_number: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        res = validate_supplier_name(v)
        if res is None:
            raise ValueError("Supplier name cannot be blank")
        return res

    @field_validator("contact_person")
    @classmethod
    def validate_contact(cls, v: str | None) -> str | None:
        return validate_contact_person(v)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str | None) -> str | None:
        return validate_supplier_phone(v)

    @field_validator("address")
    @classmethod
    def validate_address(cls, v: str | None) -> str | None:
        return validate_supplier_address(v)

    @field_validator("gst_number")
    @classmethod
    def validate_supplier_gst(cls, v: str | None) -> str | None:
        return validate_gst_number(v)


class SupplierUpdate(BaseSchema):
    name: str | None = None
    contact_person: str | None = None
    phone: str | None = None
    email: EmailStr | None = None
    address: str | None = None
    gst_number: str | None = None
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        return validate_supplier_name(v)

    @field_validator("contact_person")
    @classmethod
    def validate_contact(cls, v: str | None) -> str | None:
        return validate_contact_person(v)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str | None) -> str | None:
        return validate_supplier_phone(v)

    @field_validator("address")
    @classmethod
    def validate_address(cls, v: str | None) -> str | None:
        return validate_supplier_address(v)

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
    status: str | None = None


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


class PharmacyDashboardResponse(BaseSchema):
    total_medicines: int
    low_stock_alerts: int
    expired_medicines_alerts: int
    daily_sales: float
    monthly_sales: float


class DailyStockDeduction(BaseSchema):
    date: date
    deduction_quantity: int


class MostSellingMedicine(BaseSchema):
    medicine_id: int
    name: str
    generic_name: str | None = None
    sku: str
    total_sold_quantity: int


class DateWiseMedicineItem(BaseSchema):
    name: str
    quantity: int


class DateWiseMedicine(BaseSchema):
    date: date
    medicines: List[DateWiseMedicineItem]


class PharmacyInventoryOverviewResponse(BaseSchema):
    in_stock_medicines: int
    low_stock_medicines: int
    out_of_stock_medicines: int
    expiring_medicines: int
    daily_stock_deductions: List[DailyStockDeduction]
    most_selling_medicines: List[MostSellingMedicine]
    date_wise_medicines: List[DateWiseMedicine]


class LowStockItemAlert(BaseSchema):
    medicine_id: int | None = None
    medicine_name: str | None = None
    current_stock: int | None = None
    minimum_stock: int | None = None
    
    # Backward compatibility fields
    id: int | None = None
    name: str | None = None
    stock_quantity: int | None = None
    reorder_level: int | None = None
    unit: str = "Unit"
    status_label: str = "Low Stock"


class PharmacySalesTrendPoint(BaseSchema):
    amount: float
    
    # Support both label and specific trend keys
    label: str | None = None
    hour: str | None = None
    date: str | None = None


class PharmacyDashboardResponse(BaseSchema):
    total_medicines: int
    total_medicines_subtext: str = "Current catalog count"
    low_stock_alerts: int
    low_stock_subtext: str = "Needs reorder attention"
    expired_alerts: int
    expired_subtext: str = "Near expiry and expired"
    today_sales: float
    today_sales_subtext: str = "Paid invoices only"
    monthly_sales: float
    monthly_sales_subtext: str = "Current month revenue"
    pending_purchases: int
    pending_purchases_subtext: str = "Awaiting completion"
    total_suppliers: int
    total_suppliers_subtext: str = "Active + inactive partners"
    prescriptions: int | None = None
    prescriptions_count: int | None = None
    prescriptions_subtext: str = "Today and backlog queue"

    low_stock_items: List[LowStockItemAlert] = []
    today_sales_trend: List[PharmacySalesTrendPoint] = []
    monthly_sales_trend: List[PharmacySalesTrendPoint] = []

