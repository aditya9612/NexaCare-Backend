from datetime import date, datetime
from typing import List, Dict, Any

from sqlalchemy import func, select, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing_model import Billing, Payment, InsuranceClaim
from app.models.expense_model import Expense


class AccountantRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_dashboard_stats(self) -> Dict[str, Any]:
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
            .where(InsuranceClaim.status.in_(["submitted", "pending"]))
        ) or 0

        approved_claims = await self.db.scalar(
            select(func.count())
            .select_from(InsuranceClaim)
            .where(InsuranceClaim.status == "approved")
        ) or 0

        now = datetime.now()
        current_month = now.month
        current_year = now.year

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
                func.date(Payment.payment_date) == now.date(),
                Payment.is_refund.is_(False)
            )
        ) or 0

        return {
            "total_bills": total_bills,
            "paid_bills": paid_bills,
            "pending_bills": pending_bills,
            "overdue_bills": overdue_bills,
            "total_revenue": round(float(total_revenue), 2),
            "total_billed": round(float(total_billed), 2),
            "pending_amount": round(float(pending_amount), 2),
            "today_collection": round(float(today_collection), 2),
            "monthly_revenue": round(float(monthly_revenue), 2),
            "yearly_revenue": round(float(yearly_revenue), 2),
            "total_payments": total_payments,
            "total_refunds": round(float(total_refunds), 2),
            "insurance_claims": insurance_claims,
            "pending_claims": pending_claims,
            "approved_claims": approved_claims,
        }

    async def get_monthly_revenue_history(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        query = (
            select(
                func.year(Payment.payment_date).label("year"),
                func.month(Payment.payment_date).label("month"),
                func.coalesce(func.sum(Payment.amount), 0.0).label("revenue"),
            )
            .where(
                Payment.payment_date >= start_date,
                Payment.payment_date <= end_date,
                Payment.is_refund.is_(False),
            )
            .group_by(func.year(Payment.payment_date), func.month(Payment.payment_date))
            .order_by(func.year(Payment.payment_date), func.month(Payment.payment_date))
        )
        result = await self.db.execute(query)
        return [
            {"year": row.year, "month": row.month, "revenue": round(float(row.revenue), 2)}
            for row in result.all()
        ]

    async def get_monthly_expense_history(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        query = (
            select(
                func.year(Expense.expense_date).label("year"),
                func.month(Expense.expense_date).label("month"),
                func.coalesce(func.sum(Expense.amount), 0.0).label("expense"),
            )
            .where(
                Expense.is_deleted.is_(False),
                Expense.expense_date >= start_date,
                Expense.expense_date <= end_date,
            )
            .group_by(func.year(Expense.expense_date), func.month(Expense.expense_date))
            .order_by(func.year(Expense.expense_date), func.month(Expense.expense_date))
        )
        result = await self.db.execute(query)
        return [
            {"year": row.year, "month": row.month, "expense": round(float(row.expense), 2)}
            for row in result.all()
        ]

    async def get_month_revenue(self, year: int, month: int) -> float:
        val = await self.db.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0.0)).where(
                func.year(Payment.payment_date) == year,
                func.month(Payment.payment_date) == month,
                Payment.is_refund.is_(False),
            )
        )
        return round(float(val or 0.0), 2)