from datetime import date, datetime, timezone, timedelta
from typing import List, Optional

from pydantic import Field, field_validator

from app.schemas.common_schema import BaseSchema
from app.schemas.vendor_schema import VendorCreate, VendorUpdate, VendorResponse


class InventoryItemCreate(BaseSchema):
    name: str = Field(..., min_length=1, max_length=255)
    sku: Optional[str] = Field(None, min_length=1, max_length=100)
    barcode: Optional[str] = Field(None, min_length=1, max_length=100)
    category: str = Field(..., min_length=1, max_length=100)
    quantity: int = Field(0, ge=0)
    unit: str = Field(..., min_length=1, max_length=50)
    unit_cost: float = Field(0.0, ge=0)
    reorder_level: int = Field(10, ge=0)
    expiry_date: Optional[date] = None
    warehouse_id: Optional[int] = Field(None, gt=0)
    vendor_id: Optional[int] = Field(None, gt=0)
    department_id: Optional[int] = Field(None, gt=0)
    description: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        import re
        stripped = v.strip()
        if len(stripped) < 1:
            raise ValueError("Item name cannot be empty or only spaces")
        if stripped.isdigit():
            raise ValueError("Item name must not be numeric-only")
        if not re.match(r"^[a-zA-Z0-9\s\-\(\)]+$", stripped):
            raise ValueError("Item name contains invalid characters")
        return stripped

    @field_validator("category", "unit")
    @classmethod
    def validate_required_strings(cls, v: str) -> str:
        stripped = v.strip()
        if len(stripped) < 1:
            raise ValueError("cannot be empty or only spaces")
        return stripped

    @field_validator("sku")
    @classmethod
    def validate_sku(cls, v: Optional[str]) -> Optional[str]:
        import re
        if v is not None:
            stripped = v.strip()
            if len(stripped) < 1:
                raise ValueError("SKU cannot be empty or only spaces")
            if len(v) != len(stripped):
                raise ValueError("SKU cannot contain leading or trailing spaces")
            if not re.match(r"^[a-zA-Z0-9\-_]+$", stripped):
                raise ValueError("SKU must contain only alphanumeric characters, hyphens, or underscores")
            if len(stripped) > 100:
                raise ValueError("SKU length cannot exceed 100 characters")
            return stripped
        return v

    @field_validator("description")
    @classmethod
    def validate_optional_strings(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return v.strip()
        return v

    @field_validator("barcode")
    @classmethod
    def validate_barcode(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            stripped = v.strip()
            if stripped != "":
                if not stripped.isdigit():
                    raise ValueError("Barcode must contain only numeric characters")
                if len(stripped) != 13:
                    raise ValueError("Barcode must be exactly 13 digits")
                return stripped
        return v


class InventoryItemUpdate(BaseSchema):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    barcode: Optional[str] = Field(None, min_length=1, max_length=100)
    category: Optional[str] = Field(None, min_length=1, max_length=100)
    quantity: Optional[int] = Field(None, ge=0)
    unit: Optional[str] = Field(None, min_length=1, max_length=50)
    unit_cost: Optional[float] = Field(None, ge=0)
    reorder_level: Optional[int] = Field(None, ge=0)
    expiry_date: Optional[date] = None
    warehouse_id: Optional[int] = Field(None, gt=0)
    vendor_id: Optional[int] = Field(None, gt=0)
    department_id: Optional[int] = Field(None, gt=0)
    description: Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator("name", "category", "unit")
    @classmethod
    def validate_required_strings(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            stripped = v.strip()
            if len(stripped) < 1:
                raise ValueError("cannot be empty or only spaces")
            return stripped
        return v

    @field_validator("barcode")
    @classmethod
    def validate_barcode(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            stripped = v.strip()
            if stripped != "":
                if not stripped.isdigit():
                    raise ValueError("Barcode must contain only numeric characters")
                if len(stripped) != 13:
                    raise ValueError("Barcode must be exactly 13 digits")
                return stripped
        return v

    @field_validator("description")
    @classmethod
    def validate_optional_strings(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return v.strip()
        return v


class InventoryItemResponse(BaseSchema):
    id: int
    name: str
    sku: str
    barcode: Optional[str]
    category: str
    quantity: int
    unit: str
    unit_cost: float
    reorder_level: int
    expiry_date: Optional[date]
    warehouse_id: Optional[int]
    vendor_id: Optional[int]
    department_id: Optional[int]
    description: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class StockTransactionCreate(BaseSchema):
    item_id: int = Field(..., gt=0)
    warehouse_id: Optional[int] = Field(None, gt=0)
    transaction_type: str
    quantity: int = Field(..., ge=1)
    unit_cost: float = Field(0.0, ge=0)
    reference_type: Optional[str] = None
    reference_id: Optional[int] = Field(None, gt=0)
    notes: Optional[str] = None
    target_warehouse_id: Optional[int] = Field(None, gt=0)

    @field_validator("transaction_type")
    @classmethod
    def validate_transaction_type(cls, v: str) -> str:
        v_lower = v.lower()
        allowed = {"inward", "outward", "transfer", "adjustment", "return"}
        if v_lower not in allowed:
            raise ValueError(f"transaction_type must be one of {allowed}")
        return v_lower

    @field_validator("reference_type")
    @classmethod
    def validate_reference_type(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            import re
            stripped = v.strip()
            if len(stripped) < 1:
                raise ValueError("Reference type cannot be empty or only spaces")
            if re.match(r"^[0-9\s]+$", stripped):
                raise ValueError("Reference type must not be numeric-only")
            if not re.match(r"^[a-zA-Z0-9\s\-\_]+$", stripped):
                raise ValueError("Reference type contains invalid characters")
            return stripped
        return v

    @field_validator("notes")
    @classmethod
    def strip_optional_strings(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return v.strip()
        return v


class StockTransactionResponse(BaseSchema):
    id: int
    transaction_number: str
    item_id: int
    warehouse_id: Optional[int]
    transaction_type: str
    quantity: int
    unit_cost: float
    reference_type: Optional[str]
    reference_id: Optional[int]
    notes: Optional[str]
    transaction_date: datetime
    created_at: datetime


class StockTransactionUpdate(BaseSchema):
    item_id: Optional[int] = Field(None, gt=0)
    warehouse_id: Optional[int] = Field(None, gt=0)
    transaction_type: Optional[str] = None
    quantity: Optional[int] = Field(None, ge=1)
    unit_cost: Optional[float] = Field(None, ge=0)
    reference_type: Optional[str] = None
    reference_id: Optional[int] = Field(None, gt=0)
    notes: Optional[str] = None

    @field_validator("transaction_type")
    @classmethod
    def validate_transaction_type(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v_lower = v.lower()
            allowed = {"inward", "outward", "transfer", "adjustment", "return"}
            if v_lower not in allowed:
                raise ValueError(f"transaction_type must be one of {allowed}")
            return v_lower
        return v

    @field_validator("reference_type")
    @classmethod
    def validate_reference_type(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            import re
            stripped = v.strip()
            if len(stripped) < 1:
                raise ValueError("Reference type cannot be empty or only spaces")
            if re.match(r"^[0-9\s]+$", stripped):
                raise ValueError("Reference type must not be numeric-only")
            if not re.match(r"^[a-zA-Z0-9\s\-\_]+$", stripped):
                raise ValueError("Reference type contains invalid characters")
            return stripped
        return v

    @field_validator("notes")
    @classmethod
    def strip_optional_strings(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return v.strip()
        return v


# --- Vendor Schemas (Moved to central vendor_schema) ---


class WarehouseCreate(BaseSchema):
    name: str = Field(..., min_length=1, max_length=255)
    code: str = Field(..., min_length=1, max_length=50)
    location: Optional[str] = Field(None, min_length=1, max_length=255)
    capacity: Optional[int] = Field(None, ge=0)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        import re
        stripped = v.strip()
        if len(stripped) < 1:
            raise ValueError("Warehouse name cannot be empty or only spaces")
        if re.match(r"^[0-9\s]+$", stripped):
            raise ValueError("Warehouse name must not be numeric-only")
        if not re.match(r"^[a-zA-Z0-9\s\-\&\(\)]+$", stripped):
            raise ValueError("Warehouse name contains invalid characters")
        return stripped

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped or stripped.lower() == "null" or stripped.lower() == "string":
            raise ValueError("Warehouse code cannot be blank, 'null', or 'string'")
        import re
        if not re.match(r"^[a-zA-Z0-9\-_]+$", stripped):
            raise ValueError("Warehouse code must contain only letters, numbers, hyphens, and underscores")
        return stripped

    @field_validator("location")
    @classmethod
    def validate_location(cls, v: Optional[str]) -> str:
        import re
        if v is None:
            raise ValueError("Location cannot be empty")
        stripped = v.strip()
        if len(stripped) < 1:
            raise ValueError("Location cannot be empty or only spaces")
        if re.match(r"^[0-9\s]+$", stripped):
            raise ValueError("Location must not be numeric-only")
        if not re.match(r"^[a-zA-Z0-9\s\,\-\/\(\)]+$", stripped):
            raise ValueError("Location contains invalid characters")
        return stripped


class WarehouseUpdate(BaseSchema):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    code: Optional[str] = Field(None, min_length=1, max_length=50)
    location: Optional[str] = Field(None, min_length=1, max_length=255)
    capacity: Optional[int] = Field(None, ge=0)
    is_active: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            import re
            stripped = v.strip()
            if len(stripped) < 1:
                raise ValueError("Warehouse name cannot be empty or only spaces")
            if re.match(r"^[0-9\s]+$", stripped):
                raise ValueError("Warehouse name must not be numeric-only")
            if not re.match(r"^[a-zA-Z0-9\s\-\&\(\)]+$", stripped):
                raise ValueError("Warehouse name contains invalid characters")
            return stripped
        return v

    @field_validator("location")
    @classmethod
    def validate_location(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            import re
            stripped = v.strip()
            if len(stripped) < 1:
                raise ValueError("Location cannot be empty or only spaces")
            if re.match(r"^[0-9\s]+$", stripped):
                raise ValueError("Location must not be numeric-only")
            if not re.match(r"^[a-zA-Z0-9\s\,\-\/\(\)]+$", stripped):
                raise ValueError("Location contains invalid characters")
            return stripped
        return v

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            stripped = v.strip()
            if not stripped or stripped.lower() == "null" or stripped.lower() == "string":
                raise ValueError("Warehouse code cannot be blank, 'null', or 'string'")
            import re
            if not re.match(r"^[a-zA-Z0-9\-_]+$", stripped):
                raise ValueError("Warehouse code must contain only letters, numbers, hyphens, and underscores")
            return stripped
        return v


class WarehouseResponse(BaseSchema):
    id: int
    name: str
    code: str
    location: Optional[str]
    capacity: Optional[int]
    is_active: bool
    created_at: datetime

    @field_validator("created_at", mode="after")
    @classmethod
    def convert_created_at_to_ist(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        ist_tz = timezone(timedelta(hours=5, minutes=30))
        return v.astimezone(ist_tz)


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
    total_registered_items: int
    stock_alerts: int
    active_warehouse_units: int
    inactive_warehouse_units: int
    total_vendors: int


class ConsumptionReport(BaseSchema):
    period: str
    item_id: int
    item_name: str
    sku: str
    total_consumed: int
    total_value: float


class InventoryDashboardResponse(BaseSchema):
    total_registered_items: int
    stock_alerts: int
    active_warehouse_units: int
    total_vendors: int


