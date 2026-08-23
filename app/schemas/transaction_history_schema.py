from datetime import datetime
from pydantic import Field, model_validator
from typing import Optional
from app.schemas.common_schema import BaseSchema


class TransactionHistoryCreate(BaseSchema):
    event_type: str
    reference_no: str
    description: str | None = None
    amount: float = Field(..., ge=0)
    status: str | None = "completed"
    source_module: str | None = None
    source_id: int | None = None
    transaction_id: int | None = None
    event_date: datetime | None = None

    @model_validator(mode="after")
    def validate_source_or_transaction(self) -> 'TransactionHistoryCreate':
        if self.transaction_id is not None:
            if self.transaction_id <= 0:
                raise ValueError("transaction_id must be greater than 0")
            if self.source_id is not None and self.source_id != self.transaction_id:
                raise ValueError("source_id and transaction_id cannot conflict")
            
            self.source_id = self.transaction_id
            if not self.source_module:
                self.source_module = "payments"
        else:
            if not self.source_module or self.source_id is None:
                raise ValueError("Either transaction_id or source_module and source_id must be provided")
        return self


class TransactionHistoryResponse(BaseSchema):
    id: int
    event_type: str
    reference_no: str
    description: str | None
    amount: float
    status: str
    source_module: str
    source_id: int
    transaction_id: int | None = None
    event_date: datetime
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def populate_transaction_id(self) -> 'TransactionHistoryResponse':
        if self.source_module in ("payments", "refunds"):
            self.transaction_id = self.source_id
        else:
            self.transaction_id = None
        return self


class DashboardSummaryResponse(BaseSchema):
    total_income: float
    total_expense: float
    net_cash_flow: float
    total_refunds: float
    total_receivables: float
    event_counts: dict[str, int]
