from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing_model import Billing, Payment, InsuranceClaim


class AccountantRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_dashboard_stats(self):
        total_bills = await self.db.scalar(
            select(func.count()).select_from(Billing)
        ) or 0

        paid_bills = await self.db.scalar(
            select(func.count())
            .select_from(Billing)
            .where(Billing.status == "paid")
        ) or 0

        pending_bills = await self.db.scalar(
            select(func.count())
            .select_from(Billing)
            .where(Billing.status == "pending")
        ) or 0

        overdue_bills = await self.db.scalar(
            select(func.count())
            .select_from(Billing)
            .where(Billing.status == "overdue")
        ) or 0

        total_billed = await self.db.scalar(
            select(func.coalesce(func.sum(Billing.total_amount), 0))
        ) or 0

        pending_amount = await self.db.scalar(
            select(func.coalesce(func.sum(Billing.balance_amount), 0))
        ) or 0

        total_revenue = await self.db.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0))
            .where(Payment.is_refund.is_(False))
        ) or 0

        total_refunds = await self.db.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0))
            .where(Payment.is_refund.is_(True))
        ) or 0

        total_payments = await self.db.scalar(
            select(func.count())
            .select_from(Payment)
        ) or 0

        insurance_claims = await self.db.scalar(
            select(func.count())
            .select_from(InsuranceClaim)
        ) or 0

        pending_claims = await self.db.scalar(
            select(func.count())
            .select_from(InsuranceClaim)
            .where(InsuranceClaim.status == "submitted")
        ) or 0

        approved_claims = await self.db.scalar(
            select(func.count())
            .select_from(InsuranceClaim)
            .where(InsuranceClaim.status == "approved")
        ) or 0

        current_month = datetime.now().month
        current_year = datetime.now().year

        monthly_revenue = await self.db.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0))
            .where(
                func.month(Payment.payment_date) == current_month,
                func.year(Payment.payment_date) == current_year,
                Payment.is_refund.is_(False)
            )
        ) or 0

        yearly_revenue = await self.db.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0))
            .where(
                func.year(Payment.payment_date) == current_year,
                Payment.is_refund.is_(False)
            )
        ) or 0

        today_collection = await self.db.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0))
            .where(
                func.date(Payment.payment_date) == datetime.now().date(),
                Payment.is_refund.is_(False)
            )
        ) or 0

        return {
            "total_bills": total_bills,
            "paid_bills": paid_bills,
            "pending_bills": pending_bills,
            "overdue_bills": overdue_bills,
            "total_revenue": float(total_revenue),
            "total_billed": float(total_billed),
            "pending_amount": float(pending_amount),
            "today_collection": float(today_collection),
            "monthly_revenue": float(monthly_revenue),
            "yearly_revenue": float(yearly_revenue),
            "total_payments": total_payments,
            "total_refunds": float(total_refunds),
            "insurance_claims": insurance_claims,
            "pending_claims": pending_claims,
            "approved_claims": approved_claims,
        }