from datetime import date, datetime
from enum import Enum
from typing import Any, List, Optional

from pydantic import AliasChoices, Field, field_validator, model_validator

from app.schemas.common_schema import BaseSchema


class BillType(str, Enum):
    PHARMACY = "pharmacy"
    CONSULTATION = "consultation"


class BillingDateFilter(str, Enum):
    TODAY = "today"
    YESTERDAY = "yesterday"
    LAST_30_DAYS = "last_30_days"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"
    CUSTOM = "custom"


class BillItemCreate(BaseSchema):
    description: str
    quantity: int = Field(1, ge=1)
    unit_price: float = Field(..., ge=0)
    gst_rate: float = Field(18.0, ge=0, le=18.0)
    item_type: str = "service"
    reference_id: Optional[int] = None


class BillItemResponse(BaseSchema):
    id: int
    billing_id: int
    description: str
    quantity: int
    unit_price: float
    gst_rate: float
    gst_amount: float
    line_total: float
    item_type: str
    created_at: datetime


class BillingCreate(BaseSchema):
    patient_id: int
    discount_percent: float = Field(0.0, ge=0, le=100)
    discount_amount: float = Field(0.0, ge=0)
    due_date: datetime | None = None
    notes: str | None = None
    appointment_id: Optional[int] = None
    items: List[BillItemCreate] = Field(..., min_length=1)


class BillingUpdate(BaseSchema):
    discount_percent: float | None = Field(None, ge=0, le=100)
    discount_amount: float | None = Field(None, ge=0)
    gst_rate: float | None = Field(None, ge=0, le=18.0)
    tax_amount: float | None = Field(None, ge=0)
    due_date: datetime | None = None
    notes: str | None = None
    items: List[BillItemCreate] | None = Field(None, min_length=1)


class BillingResponse(BaseSchema):
    id: int
    patient_id: int
    bill_number: str
    subtotal: float
    discount_percent: float
    discount_amount: float
    gst_rate: float
    gst_amount: float
    tax_amount: float
    total_amount: float
    paid_amount: float
    balance_amount: float
    status: str
    due_date: datetime | None
    notes: str | None
    invoice_path: str | None
    appointment_id: Optional[int] = None
    items: List[BillItemResponse] = []
    created_at: datetime
    updated_at: datetime
    source: Optional[str] = "billing"
    bill_type: Optional[str] = "consultation"


class PaymentCreate(BaseSchema):
    amount: float = Field(..., gt=0)
    payment_method: str = Field(..., validation_alias=AliasChoices("payment_method", "paymentMethod"))
    transaction_ref: str | None = Field(
        None,
        validation_alias=AliasChoices("transaction_ref", "transactionReference", "transaction_reference"),
    )

    @model_validator(mode="after")
    def validate_payment_details(self) -> 'PaymentCreate':
        # Normalize payment method
        method = self.payment_method.strip().lower()
        if method == "cheques":
            method = "cheque"
        self.payment_method = method

        # Trim transaction reference if provided
        if self.transaction_ref is not None:
            self.transaction_ref = self.transaction_ref.strip()
            if not self.transaction_ref:
                self.transaction_ref = None

        # Validate allowed payment methods
        allowed_methods = {"cash", "upi", "cheque", "card", "bank_transfer", "insurance"}
        if method not in allowed_methods:
            raise ValueError(
                f"Invalid payment method '{self.payment_method}'. Supported methods are: cash, upi, cheque, card, bank_transfer, insurance"
            )

        # Enforce validation rules only for cash, upi, and cheque
        if method == "cash":
            if self.transaction_ref:
                raise ValueError("Transaction reference should not be provided for cash payments")
        elif method in ("upi", "cheque"):
            if not self.transaction_ref:
                raise ValueError(f"Transaction reference is required for {method} payments")

        return self


class PaymentResponse(BaseSchema):
    id: int
    billing_id: int
    amount: float
    payment_method: str
    transaction_ref: str | None
    payment_date: datetime
    status: str
    is_refund: bool
    refund_reason: str | None
    created_at: datetime


class RefundCreate(BaseSchema):
    amount: float = Field(..., gt=0)
    refund_reason: str


class InsuranceCreate(BaseSchema):
    patient_id: int
    provider_name: str
    policy_number: str
    coverage_percent: float = Field(0.0, ge=0, le=100)
    max_coverage: float | None = None
    valid_from: date | None = None
    valid_to: date | None = None


class InsuranceResponse(BaseSchema):
    id: int
    patient_id: int
    provider_name: str
    policy_number: str
    coverage_percent: float
    max_coverage: float | None
    valid_from: date | None
    valid_to: date | None
    is_active: bool
    created_at: datetime


class InsuranceClaimCreate(BaseSchema):
    billing_id: int
    insurance_id: int
    claimed_amount: float = Field(..., gt=0)
    notes: str | None = None


class InsuranceClaimResponse(BaseSchema):
    id: int
    billing_id: int
    insurance_id: int
    claim_number: str
    claimed_amount: float
    approved_amount: float | None
    status: str
    submitted_at: datetime | None
    approved_at: datetime | None
    notes: str | None
    created_at: datetime


class RevenueReport(BaseSchema):
    period: str
    total_billed: float
    total_collected: float
    total_pending: float
    total_refunded: float
    bill_count: int
    payment_count: int

    @field_validator("total_billed", "total_collected", "total_pending", "total_refunded", mode="after")
    @classmethod
    def round_money_fields(cls, v: float) -> float:
        return round(float(v), 2)



class ReceptionCollectionSummary(BaseSchema):
    total_bill: float = 0.0
    paid_bill: float = 0.0
    pending_bill: float = 0.0
    collected_revenue: float = 0.0
    bills_count: int = 0
    payment_count: int = 0
    refunds_issued: float = 0.0
    refund_count: int = 0
    by_method: dict[str, float] = Field(default_factory=dict)

    @field_validator('total_bill', 'paid_bill', 'pending_bill', 'collected_revenue', 'refunds_issued', mode='after')
    @classmethod
    def round_money_fields(cls, v: float) -> float:
        return max(0.0, round(float(v), 2))


class PharmacyCollectionSummary(BaseSchema):
    total_bill: float = 0.0
    paid_bill: float = 0.0
    pending_bill: float = 0.0
    collected_revenue: float = 0.0
    bills_count: int = 0
    payment_count: int = 0
    refunds_issued: float = 0.0
    refund_count: int = 0

    @field_validator('total_bill', 'paid_bill', 'pending_bill', 'collected_revenue', 'refunds_issued', mode='after')
    @classmethod
    def round_money_fields(cls, v: float) -> float:
        return max(0.0, round(float(v), 2))


class DailyCollectionSummary(BaseSchema):
    date: str
    filter_type: str | None = None
    start_date: str | None = None
    end_date: str | None = None

    # Overall Summary
    today_total_bill: float = 0.0
    today_paid_bill: float = 0.0
    today_pending_bill: float = 0.0
    today_collected_revenue: float = 0.0
    bills_count: int = 0
    total_collected: float = 0.0
    payment_count: int = 0
    refunds_issued: float = 0.0
    refund_count: int = 0
    by_method: dict[str, float] = Field(default_factory=dict)

    # Separate Reception / Appointment Billing & Collection
    reception_today_total_bill: float = 0.0
    reception_today_paid_bill: float = 0.0
    reception_today_pending_bill: float = 0.0
    reception_collected_revenue: float = 0.0

    reception_bills_count: int = 0
    reception_payment_count: int = 0
    reception_refunds_issued: float = 0.0
    reception_refund_count: int = 0

    reception_today_bills_count: int = 0
    reception_today_payment_count: int = 0

    reception_by_method: dict[str, float] = Field(default_factory=dict)

    # Separate Pharmacy Billing & Collection
    pharmacy_total_bill: float = 0.0
    pharmacy_paid_bill: float = 0.0
    pharmacy_pending_bill: float = 0.0
    pharmacy_collected_revenue: float = 0.0
    pharmacy_bills_count: int = 0
    pharmacy_payment_count: int = 0
    pharmacy_refunds_issued: float = 0.0
    pharmacy_refund_count: int = 0

    # Nested section objects for convenience
    reception_collection: ReceptionCollectionSummary | None = None
    pharmacy_collection: PharmacyCollectionSummary | None = None

    @model_validator(mode="before")
    @classmethod
    def map_legacy_reception_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "reception_total_bill" in data and "reception_today_total_bill" not in data:
                data["reception_today_total_bill"] = data["reception_total_bill"]
            if "reception_paid_bill" in data and "reception_today_paid_bill" not in data:
                data["reception_today_paid_bill"] = data["reception_paid_bill"]
            if "reception_pending_bill" in data and "reception_today_pending_bill" not in data:
                data["reception_today_pending_bill"] = data["reception_pending_bill"]
            if "reception_today_collected_revenue" in data and "reception_collected_revenue" not in data:
                data["reception_collected_revenue"] = data["reception_today_collected_revenue"]
            if "reception_bills_count" in data and "reception_today_bills_count" not in data:
                data["reception_today_bills_count"] = data["reception_bills_count"]
            if "reception_today_bills_count" in data and "reception_bills_count" not in data:
                data["reception_bills_count"] = data["reception_today_bills_count"]
            if "reception_payment_count" in data and "reception_today_payment_count" not in data:
                data["reception_today_payment_count"] = data["reception_payment_count"]
            if "reception_today_payment_count" in data and "reception_payment_count" not in data:
                data["reception_payment_count"] = data["reception_today_payment_count"]
        return data

    @field_validator(
        "today_total_bill",
        "today_paid_bill",
        "today_pending_bill",
        "today_collected_revenue",
        "total_collected",

        "refunds_issued",




        "reception_today_total_bill",
        "reception_today_paid_bill",
        "reception_today_pending_bill",

        "reception_collected_revenue",
        "reception_refunds_issued",
        "pharmacy_total_bill",
        "pharmacy_paid_bill",
        "pharmacy_pending_bill",
        "pharmacy_collected_revenue",
        "pharmacy_refunds_issued",
        mode="after",
    )
    @classmethod
    def round_total_collected(cls, v: float) -> float:
        return max(0.0, round(float(v), 2))



class BillingSummary(BaseSchema):
    total_revenue: float
    total_pending: float
    total_paid: float
    overdue_count: int
    pending_count: int
