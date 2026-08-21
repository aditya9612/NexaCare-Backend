from typing import List, Optional
from app.schemas.common_schema import BaseSchema


class RevenueForecast(BaseSchema):
    projected_revenue: float
    growth_percentage: float
    trend: str
    message: str


class ClaimPending(BaseSchema):
    count: int
    status: str
    message: str


class ForecastMonthlyData(BaseSchema):
    month: str
    actual: float
    predicted: float


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

    total_payments: float
    total_refunds: float

    insurance_claims: int
    pending_claims: int
    approved_claims: int

    revenue_forecast: Optional[RevenueForecast] = None
    claim_pending: Optional[ClaimPending] = None
    ai_revenue_forecast: Optional[AIRevenueForecast] = None
    expense_prediction: Optional[ExpensePrediction] = None