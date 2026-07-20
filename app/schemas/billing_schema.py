from datetime import date, datetime
from typing import List, Optional

from pydantic import Field

from app.schemas.common_schema import BaseSchema


class BillItemCreate(BaseSchema):
    description: str
    quantity: int = Field(1, ge=1)
    unit_price: float = Field(..., ge=0)
    gst_rate: float = Field(18.0, ge=0, le=18.0)
    item_type: str = "service"


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
    insurance_id: int | None = None
    appointment_id: Optional[int] = None
    items: List[BillItemCreate] = Field(..., min_length=1)


class BillingUpdate(BaseSchema):
    discount_percent: float | None = Field(None, ge=0, le=100)
    discount_amount: float | None = Field(None, ge=0)
    gst_rate: float | None = Field(None, ge=0, le=18.0)
    tax_amount: float | None = Field(None, ge=0)
    due_date: datetime | None = None
    notes: str | None = None
    insurance_id: int | None = None
    status: str | None = None
    items: List[BillItemCreate] | None = None


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
    insurance_id: int | None
    invoice_path: str | None
    appointment_id: Optional[int] = None
    items: List[BillItemResponse] = []
    created_at: datetime
    updated_at: datetime
    source: Optional[str] = "billing"


class PaymentCreate(BaseSchema):
    amount: float = Field(..., gt=0)
    payment_method: str
    transaction_ref: str | None = None


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


class DailyCollectionSummary(BaseSchema):
    date: str
    total_collected: float
    payment_count: int
    by_method: dict[str, float]


class BillingSummary(BaseSchema):
    total_revenue: float
    total_pending: float
    total_paid: float
    overdue_count: int
    pending_count: int
