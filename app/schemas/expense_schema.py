from datetime import date, datetime
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator

from app.schemas.common_schema import BaseSchema, PaginationQuery
from app.schemas.vendor_schema import VendorResponse


# --- Category Schemas ---

class ExpenseCategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(..., min_length=1, max_length=255)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 1:
            raise ValueError("name cannot be empty or only spaces")
        return stripped

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 1:
            raise ValueError("description cannot be empty or only spaces")
        return stripped


class ExpenseCategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=255)
    is_active: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            stripped = value.strip()
            if len(stripped) < 1:
                raise ValueError("name cannot be empty or only spaces")
            return stripped
        return value

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            return value.strip()
        return value


class ExpenseCategoryResponse(BaseSchema):
    id: int
    name: str
    description: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime


# --- Vendor Schemas (Moved to central vendor_schema) ---


# --- Expense Schemas ---

class ExpenseCreate(BaseModel):
    category_id: int = Field(..., gt=0)
    vendor_id: Optional[int] = Field(None, gt=0)
    amount: float = Field(..., gt=0)
    description: str = Field(..., min_length=1, max_length=500)
    expense_date: date
    status: str = Field("Pending", pattern="^(Paid|Pending)$")

    @field_validator("expense_date")
    @classmethod
    def validate_expense_date(cls, value: date) -> date:
        if value > date.today():
            raise ValueError("expense_date cannot be in the future")
        return value

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 1:
            raise ValueError("description cannot be empty or only spaces")
        return stripped


class ExpenseUpdate(BaseModel):
    category_id: Optional[int] = Field(None, gt=0)
    vendor_id: Optional[int] = Field(None, gt=0)
    amount: Optional[float] = Field(None, gt=0)
    description: Optional[str] = Field(None, max_length=500)
    expense_date: Optional[date] = None
    status: Optional[str] = Field(None, pattern="^(Paid|Pending)$")

    @field_validator("expense_date")
    @classmethod
    def validate_expense_date(cls, value: Optional[date]) -> Optional[date]:
        if value is not None:
            if value > date.today():
                raise ValueError("expense_date cannot be in the future")
            return value
        return value

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            return value.strip()
        return value


class ExpenseResponse(BaseSchema):
    id: int
    category_id: int
    vendor_id: Optional[int]
    amount: float
    description: Optional[str]
    expense_date: date
    status: str
    category: Optional[ExpenseCategoryResponse] = None
    vendor: Optional[VendorResponse] = None
    created_at: datetime
    updated_at: datetime
    source: str = "expense"



class ExpenseQuery(PaginationQuery):
    description: Optional[str] = None
    category_id: Optional[int] = None
    vendor_id: Optional[int] = None
    status: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None


# --- Vendor Payment Schemas ---

class VendorPaymentCreate(BaseModel):
    vendor_id: int = Field(..., gt=0)
    expense_id: int = Field(..., gt=0)
    amount: float = Field(..., gt=0)
    payment_method: str = Field(..., min_length=1, max_length=50)

    @field_validator("payment_method")
    @classmethod
    def validate_payment_method(cls, value: str) -> str:
        stripped = value.strip()
        val_lower = stripped.lower()
        mapping = {
            "debit/credit/prpaid card": "Debit/credit/prpaid card",
            "debit/credit/prepaid card": "Debit/credit/prpaid card",
            "bank trasfter(neft, rtgs, imps, net banking)": "bank trasfter(NEFT, RTGS, IMPS, Net banking)",
            "bank transfer(neft, rtgs, imps, net banking)": "bank trasfter(NEFT, RTGS, IMPS, Net banking)",
            "upi/bhip pay": "UPI/BHIP PAY",
            "upi/bhim pay": "UPI/BHIP PAY",
            "cash": "CASH"
        }
        if val_lower not in mapping:
            raise ValueError(
                "payment_method must be one of: Debit/credit/prpaid card, "
                "bank trasfter(NEFT, RTGS, IMPS, Net banking), UPI/BHIP PAY, CASH"
            )
        return mapping[val_lower]


class VendorPaymentUpdate(BaseModel):
    vendor_id: Optional[int] = Field(None, gt=0)
    expense_id: Optional[int] = Field(None, gt=0)
    amount: Optional[float] = Field(None, gt=0)
    payment_method: Optional[str] = Field(None, min_length=1, max_length=50)

    @field_validator("payment_method")
    @classmethod
    def validate_payment_method(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            stripped = value.strip()
            val_lower = stripped.lower()
            mapping = {
                "debit/credit/prpaid card": "Debit/credit/prpaid card",
                "debit/credit/prepaid card": "Debit/credit/prpaid card",
                "bank trasfter(neft, rtgs, imps, net banking)": "bank trasfter(NEFT, RTGS, IMPS, Net banking)",
                "bank transfer(neft, rtgs, imps, net banking)": "bank trasfter(NEFT, RTGS, IMPS, Net banking)",
                "upi/bhip pay": "UPI/BHIP PAY",
                "upi/bhim pay": "UPI/BHIP PAY",
                "cash": "CASH"
            }
            if val_lower not in mapping:
                raise ValueError(
                    "payment_method must be one of: Debit/credit/prpaid card, "
                    "bank trasfter(NEFT, RTGS, IMPS, Net banking), UPI/BHIP PAY, CASH"
                )
            return mapping[val_lower]
        return value


class VendorPaymentResponse(BaseSchema):
    id: int
    vendor_id: int
    expense_id: int
    amount: float
    payment_method: str
    payment_date: datetime
    created_at: datetime
    updated_at: datetime


# --- Reporting Schemas ---

class CategorySummary(BaseModel):
    category_id: int
    name: str
    total_amount: float
    count: int


class VendorSummary(BaseModel):
    vendor_id: Optional[int]
    name: Optional[str]
    total_amount: float
    count: int


class StatusSummary(BaseModel):
    status: str
    total_amount: float
    count: int


class MonthlySummary(BaseModel):
    month: int
    year: int
    total_amount: float
    count: int


class ExpenseSummaryResponse(BaseModel):
    total_amount: float
    total_count: int
    by_category: List[CategorySummary]
    by_vendor: List[VendorSummary]
    by_status: List[StatusSummary]
    monthly_summary: List[MonthlySummary]
