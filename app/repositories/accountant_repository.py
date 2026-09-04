from datetime import date, datetime
from typing import List, Dict, Any

from sqlalchemy import func, select, case, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing_model import Billing, Payment, InsuranceClaim
from app.models.expense_model import Expense
from app.models.final_bill_model import IPDFinalBill


class AccountantRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_dashboard_stats(self) -> Dict[str, Any]:
        # 1. OPD Billings Counts & Amounts
        b_total = await self.db.scalar(
            select(func.count()).select_from(Billing).where(Billing.is_deleted.is_(False))
        ) or 0

        b_paid = await self.db.scalar(
            select(func.count())
            .select_from(Billing)
            .where(Billing.is_deleted.is_(False), Billing.status == "paid")
        ) or 0

        b_pending = await self.db.scalar(
            select(func.count())
            .select_from(Billing)
            .where(Billing.is_deleted.is_(False), Billing.status.in_(["pending", "partial"]))
        ) or 0

        b_overdue = await self.db.scalar(
            select(func.count())
            .select_from(Billing)
            .where(Billing.is_deleted.is_(False), Billing.status == "overdue")
        ) or 0

        b_billed = await self.db.scalar(
            select(func.coalesce(func.sum(Billing.total_amount), 0))
            .where(Billing.is_deleted.is_(False))
        ) or 0

        b_pending_amount = await self.db.scalar(
            select(func.coalesce(func.sum(Billing.balance_amount), 0))
            .where(Billing.is_deleted.is_(False))
        ) or 0

        # 2. IPD Final Bills Counts & Amounts
        ipd_total = await self.db.scalar(
            select(func.count()).select_from(IPDFinalBill).where(IPDFinalBill.is_deleted.is_(False))
        ) or 0

        ipd_paid = await self.db.scalar(
            select(func.count())
            .select_from(IPDFinalBill)
            .where(IPDFinalBill.is_deleted.is_(False), IPDFinalBill.status == "paid")
        ) or 0

        ipd_pending = await self.db.scalar(
            select(func.count())
            .select_from(IPDFinalBill)
            .where(IPDFinalBill.is_deleted.is_(False), IPDFinalBill.status == "pending")
        ) or 0

        ipd_billed = await self.db.scalar(
            select(func.coalesce(func.sum(IPDFinalBill.net_total), 0))
            .where(IPDFinalBill.is_deleted.is_(False))
        ) or 0

        ipd_pending_amount = await self.db.scalar(
            select(
                func.coalesce(
                    func.sum(case((IPDFinalBill.status == "paid", 0.0), else_=IPDFinalBill.balance_amount)),
                    0.0,
                )
            ).where(IPDFinalBill.is_deleted.is_(False))
        ) or 0

        # 3. Combined Bills & Billed
        total_bills = b_total + ipd_total
        paid_bills = b_paid + ipd_paid
        pending_bills = b_pending + ipd_pending
        overdue_bills = b_overdue
        total_billed = b_billed + ipd_billed
        pending_amount = b_pending_amount + ipd_pending_amount

        # 4. Revenue & Collections
        b_revenue = await self.db.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0))
            .where(Payment.is_refund.is_(False))
        ) or 0

        ipd_revenue = await self.db.scalar(
            select(
                func.coalesce(
                    func.sum(case((IPDFinalBill.status == "paid", IPDFinalBill.net_total), else_=IPDFinalBill.advance_adjusted)),
                    0.0,
                )
            ).where(IPDFinalBill.is_deleted.is_(False))
        ) or 0

        total_revenue = b_revenue + ipd_revenue

        b_refunds = await self.db.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0))
            .where(Payment.is_refund.is_(True))
        ) or 0

        ipd_refunds = await self.db.scalar(
            select(func.coalesce(func.sum(IPDFinalBill.refund_amount), 0.0))
            .where(IPDFinalBill.is_deleted.is_(False))
        ) or 0

        total_refunds = b_refunds + ipd_refunds

        b_payments_count = await self.db.scalar(
            select(func.count()).select_from(Payment)
        ) or 0

        ipd_payments_count = await self.db.scalar(
            select(func.count())
            .select_from(IPDFinalBill)
            .where(
                IPDFinalBill.is_deleted.is_(False),
                or_(IPDFinalBill.status == "paid", IPDFinalBill.advance_adjusted > 0),
            )
        ) or 0

        total_payments = b_payments_count + ipd_payments_count

        insurance_claims = await self.db.scalar(
            select(func.count()).select_from(InsuranceClaim)
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
        ipd_dt = func.coalesce(IPDFinalBill.settled_at, IPDFinalBill.updated_at, IPDFinalBill.created_at)

        # Monthly Revenue
        b_monthly_revenue = await self.db.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0))
            .where(
                func.month(Payment.payment_date) == current_month,
                func.year(Payment.payment_date) == current_year,
                Payment.is_refund.is_(False)
            )
        ) or 0

        ipd_monthly_revenue = await self.db.scalar(
            select(
                func.coalesce(
                    func.sum(case((IPDFinalBill.status == "paid", IPDFinalBill.net_total), else_=IPDFinalBill.advance_adjusted)),
                    0.0,
                )
            ).where(
                IPDFinalBill.is_deleted.is_(False),
                func.month(ipd_dt) == current_month,
                func.year(ipd_dt) == current_year,
                or_(IPDFinalBill.status == "paid", IPDFinalBill.advance_adjusted > 0),
            )
        ) or 0

        monthly_revenue = b_monthly_revenue + ipd_monthly_revenue

        # Yearly Revenue
        b_yearly_revenue = await self.db.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0))
            .where(
                func.year(Payment.payment_date) == current_year,
                Payment.is_refund.is_(False)
            )
        ) or 0

        ipd_yearly_revenue = await self.db.scalar(
            select(
                func.coalesce(
                    func.sum(case((IPDFinalBill.status == "paid", IPDFinalBill.net_total), else_=IPDFinalBill.advance_adjusted)),
                    0.0,
                )
            ).where(
                IPDFinalBill.is_deleted.is_(False),
                func.year(ipd_dt) == current_year,
                or_(IPDFinalBill.status == "paid", IPDFinalBill.advance_adjusted > 0),
            )
        ) or 0

        yearly_revenue = b_yearly_revenue + ipd_yearly_revenue

        # Today Collection
        b_today_collection = await self.db.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0))
            .where(
                func.date(Payment.payment_date) == now.date(),
                Payment.is_refund.is_(False)
            )
        ) or 0

        ipd_today_collection = await self.db.scalar(
            select(
                func.coalesce(
                    func.sum(case((IPDFinalBill.status == "paid", IPDFinalBill.net_total), else_=IPDFinalBill.advance_adjusted)),
                    0.0,
                )
            ).where(
                IPDFinalBill.is_deleted.is_(False),
                func.date(ipd_dt) == now.date(),
                or_(IPDFinalBill.status == "paid", IPDFinalBill.advance_adjusted > 0),
            )
        ) or 0

        today_collection = b_today_collection + ipd_today_collection

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
        # OPD Payments History
        b_query = (
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
        b_result = await self.db.execute(b_query)

        # IPD Final Bills History
        ipd_dt = func.coalesce(IPDFinalBill.settled_at, IPDFinalBill.updated_at, IPDFinalBill.created_at)
        ipd_query = (
            select(
                func.year(ipd_dt).label("year"),
                func.month(ipd_dt).label("month"),
                func.coalesce(
                    func.sum(case((IPDFinalBill.status == "paid", IPDFinalBill.net_total), else_=IPDFinalBill.advance_adjusted)),
                    0.0,
                ).label("revenue"),
            )
            .where(
                IPDFinalBill.is_deleted.is_(False),
                ipd_dt >= start_date,
                ipd_dt <= end_date,
                or_(IPDFinalBill.status == "paid", IPDFinalBill.advance_adjusted > 0),
            )
            .group_by(func.year(ipd_dt), func.month(ipd_dt))
            .order_by(func.year(ipd_dt), func.month(ipd_dt))
        )
        ipd_result = await self.db.execute(ipd_query)

        monthly_map: Dict[tuple, float] = {}
        for row in b_result.all():
            key = (int(row.year), int(row.month))
            monthly_map[key] = monthly_map.get(key, 0.0) + float(row.revenue)

        for row in ipd_result.all():
            key = (int(row.year), int(row.month))
            monthly_map[key] = monthly_map.get(key, 0.0) + float(row.revenue)

        sorted_keys = sorted(monthly_map.keys())
        return [
            {"year": k[0], "month": k[1], "revenue": round(monthly_map[k], 2)}
            for k in sorted_keys
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
        b_val = await self.db.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0.0)).where(
                func.year(Payment.payment_date) == year,
                func.month(Payment.payment_date) == month,
                Payment.is_refund.is_(False),
            )
        ) or 0.0

        ipd_dt = func.coalesce(IPDFinalBill.settled_at, IPDFinalBill.updated_at, IPDFinalBill.created_at)
        ipd_val = await self.db.scalar(
            select(
                func.coalesce(
                    func.sum(case((IPDFinalBill.status == "paid", IPDFinalBill.net_total), else_=IPDFinalBill.advance_adjusted)),
                    0.0,
                )
            ).where(
                IPDFinalBill.is_deleted.is_(False),
                func.year(ipd_dt) == year,
                func.month(ipd_dt) == month,
                or_(IPDFinalBill.status == "paid", IPDFinalBill.advance_adjusted > 0),
            )
        ) or 0.0

        return round(float(b_val + ipd_val), 2)