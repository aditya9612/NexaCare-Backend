from datetime import datetime
from pydantic import Field
from app.schemas.common_schema import BaseSchema


class TransactionHistoryCreate(BaseSchema):
    event_type: str
    reference_no: str
    description: str | None = None
    amount: float = Field(..., ge=0)
    status: str | None = "completed"
    source_module: str
    source_id: int
    event_date: datetime | None = None


class TransactionHistoryResponse(BaseSchema):
    id: int
    event_type: str
    reference_no: str
    description: str | None
    amount: float
    status: str
    source_module: str
    source_id: int
    event_date: datetime
    created_at: datetime
    updated_at: datetime


class DashboardSummaryResponse(BaseSchema):
    total_income: float
    total_expense: float
    net_cash_flow: float
    total_refunds: float
    total_receivables: float
    event_counts: dict[str, int]
