from datetime import datetime
from typing import Optional

from pydantic import Field

from app.schemas.common_schema import BaseSchema


class BillingSettingResponse(BaseSchema):
    id: int
    hospital_id: int
    currency: str
    currency_symbol: str
    gst_percentage: float
    invoice_prefix: str
    receipt_prefix: str
    default_payment_mode: str
    round_off_rule: str
    created_at: datetime
    updated_at: datetime


class BillingSettingUpdate(BaseSchema):
    currency: Optional[str] = Field(None, description="Default currency code (e.g. INR, USD)")
    currency_symbol: Optional[str] = Field(None, description="Default currency symbol (e.g. ₹, $)")
    gst_percentage: Optional[float] = Field(None, ge=0.0, le=100.0, description="Default GST percentage")
    invoice_prefix: Optional[str] = Field(None, max_length=10, description="Prefix for generated invoices/bills")
    receipt_prefix: Optional[str] = Field(None, max_length=10, description="Prefix for generated receipts")
    default_payment_mode: Optional[str] = Field(None, description="Default payment mode (e.g. cash, card)")
    round_off_rule: Optional[str] = Field(None, description="Round off rule (e.g. nearest, up, down)")
