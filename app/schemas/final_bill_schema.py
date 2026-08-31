from datetime import datetime
from pydantic import Field

from app.schemas.common_schema import BaseSchema


class IPDFinalBillItemResponse(BaseSchema):
    id: int
    final_bill_id: int
    item_type: str
    item_name: str
    quantity: int
    unit_price: float
    tax_rate: float
    total_price: float
    reference_id: int | None = None
    created_at: datetime
    updated_at: datetime


class IPDFinalBillResponse(BaseSchema):
    id: int
    bill_number: str
    discharge_id: int
    patient_id: int
    appointment_id: int
    doctor_id: int
    bed_id: int | None = None

    # Component subtotals
    bed_charges: float | None = 0.0
    doctor_charges: float | None = 0.0
    lab_charges: float | None = 0.0
    radiology_charges: float | None = 0.0
    pharmacy_charges: float | None = 0.0
    procedure_charges: float | None = 0.0
    prior_opd_charges: float | None = 0.0

    # Financial calculations
    gross_total: float | None = 0.0
    discount_amount: float | None = 0.0
    discount_reason: str | None = None
    tax_rate: float | None = 0.0
    tax_amount: float | None = 0.0
    net_total: float | None = 0.0
    advance_adjusted: float | None = 0.0
    balance_amount: float | None = 0.0
    refund_amount: float | None = 0.0

    # Status & Settlement
    status: str
    payment_mode: str | None = None
    settled_at: datetime | None = None
    settled_by: int | None = None
    notes: str | None = None

    created_at: datetime
    updated_at: datetime

    items: list[IPDFinalBillItemResponse] = []


class IPDFinalBillSummaryResponse(BaseSchema):
    id: int
    bill_number: str
    discharge_id: int
    patient_id: int
    patient_name: str | None = None
    gross_total: float
    discount_amount: float
    net_total: float
    advance_adjusted: float
    balance_amount: float
    refund_amount: float
    status: str
    created_at: datetime
