from app.schemas.common_schema import BaseSchema


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