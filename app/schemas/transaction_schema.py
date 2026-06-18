from datetime import datetime
from pydantic import Field
from app.schemas.common_schema import BaseSchema


class TransactionCreate(BaseSchema):
    billing_id: int
    amount: float = Field(..., gt=0)
    payment_method: str
    transaction_ref: str | None = None
    payment_date: datetime | None = None
    status: str | None = "completed"
    is_refund: bool | None = False
    refund_reason: str | None = None


class TransactionUpdate(BaseSchema):
    amount: float | None = Field(None, gt=0)
    payment_method: str | None = None
    transaction_ref: str | None = None
    payment_date: datetime | None = None
    status: str | None = None
    is_refund: bool | None = None
    refund_reason: str | None = None


class TransactionResponse(BaseSchema):
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
    updated_at: datetime
