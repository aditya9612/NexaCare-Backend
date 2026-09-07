from typing import List, Optional
from pydantic import field_validator
from app.schemas.common_schema import BaseSchema


class RevenueForecast(BaseSchema):
    projected_revenue: float
    growth_percentage: float
    trend: str
    message: str

    @field_validator("projected_revenue", "growth_percentage", mode="after")
    @classmethod
    def round_forecast_fields(cls, v: float) -> float:
        return round(float(v), 2)


class ClaimPending(BaseSchema):
    count: int
    status: str
    message: str


class ForecastMonthlyData(BaseSchema):
    month: str
    actual: float
    predicted: float

    @field_validator("actual", "predicted", mode="after")
    @classmethod
    def round_chart_fields(cls, v: float) -> float:
        return round(float(v), 2)


class AIRevenueForecast(BaseSchema):
    chart_data: List[ForecastMonthlyData]


class ExpensePrediction(BaseSchema):
    chart_data: List[ForecastMonthlyData]


class AccountantDashboardResponse(BaseSchema):
    total_bills: int
    paid_bills: int
    pending_bills: int
    overdue_bills: int

    total_revenue: float
    total_billed: float
    pending_amount: float
    today_collection: float
    monthly_revenue: float
    yearly_revenue: float

    total_payments: int
    total_refunds: float

    insurance_claims: int
    pending_claims: int
    approved_claims: int

    revenue_forecast: Optional[RevenueForecast] = None
    claim_pending: Optional[ClaimPending] = None
    ai_revenue_forecast: Optional[AIRevenueForecast] = None
    expense_prediction: Optional[ExpensePrediction] = None

    @field_validator(
        "total_revenue",
        "total_billed",
        "pending_amount",
        "today_collection",
        "monthly_revenue",
        "yearly_revenue",
        "total_refunds",
        mode="after",
    )
    @classmethod
    def round_money_fields(cls, v: float) -> float:
        return round(float(v), 2)