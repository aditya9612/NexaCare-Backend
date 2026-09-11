from datetime import date, datetime
from typing import List, Dict, Any

from sqlalchemy import func, select, case, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing_model import Billing, Payment, InsuranceClaim
from app.models.expense_model import Expense
from app.models.final_bill_model import IPDFinalBill


class AccountantRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_dashboard_stats(self) -> Dict[str, Any]:
        now = datetime.now()
        current_month = now.month
        current_year = now.year
        today = now.date()

        # 1. OPD Billings Counts & Amounts
        b_stats_res = await self.db.execute(
            select(
                func.count(),
                func.coalesce(func.sum(case((Billing.status == "paid", 1), else_=0)), 0),
                func.coalesce(func.sum(case((Billing.status.in_(["pending", "partial"]), 1), else_=0)), 0),
                func.coalesce(func.sum(case((Billing.status == "overdue", 1), else_=0)), 0),
                func.coalesce(func.sum(Billing.total_amount), 0),
                func.coalesce(func.sum(Billing.balance_amount), 0)
            ).where(Billing.is_deleted.is_(False))
        )
        b_total, b_paid, b_pending, b_overdue, b_billed, b_pending_amount = b_stats_res.one()

        # 2. IPD Final Bills Counts & Amounts
        ipd_stats_res = await self.db.execute(
            select(
                func.count(),
                func.coalesce(func.sum(case((IPDFinalBill.status == "paid", 1), else_=0)), 0),
                func.coalesce(func.sum(case((IPDFinalBill.status == "pending", 1), else_=0)), 0),
                func.coalesce(func.sum(IPDFinalBill.net_total), 0),
                func.coalesce(
                    func.sum(case((IPDFinalBill.status == "paid", 0.0), else_=IPDFinalBill.balance_amount)),
                    0.0
                )
            ).where(IPDFinalBill.is_deleted.is_(False))
        )
        ipd_total, ipd_paid, ipd_pending, ipd_billed, ipd_pending_amount = ipd_stats_res.one()

        # 3. Combined Bills & Billed
        total_bills = b_total + ipd_total
        paid_bills = b_paid + ipd_paid
        pending_bills = b_pending + ipd_pending
        overdue_bills = b_overdue
        total_billed = b_billed + ipd_billed
        pending_amount = b_pending_amount + ipd_pending_amount

        # 4. OPD Payments (Revenue, Refunds, Collections)
        p_stats_res = await self.db.execute(
            select(
                func.coalesce(func.sum(case((Payment.is_refund.is_(False), Payment.amount), else_=0)), 0),
                func.coalesce(func.sum(case((Payment.is_refund.is_(True), Payment.amount), else_=0)), 0),
                func.count(),
                func.coalesce(func.sum(case((
                    and_(Payment.is_refund.is_(False), func.month(Payment.payment_date) == current_month, func.year(Payment.payment_date) == current_year),
                    Payment.amount
                ), else_=0)), 0),
                func.coalesce(func.sum(case((
                    and_(Payment.is_refund.is_(False), func.year(Payment.payment_date) == current_year),
                    Payment.amount
                ), else_=0)), 0),
                func.coalesce(func.sum(case((
                    and_(Payment.is_refund.is_(False), func.date(Payment.payment_date) == today),
                    Payment.amount
                ), else_=0)), 0)
            )
        )
        b_revenue, b_refunds, b_payments_count, b_monthly_revenue, b_yearly_revenue, b_today_collection = p_stats_res.one()

        # 5. IPD Revenue & Refunds
        ipd_dt = func.coalesce(IPDFinalBill.settled_at, IPDFinalBill.updated_at, IPDFinalBill.created_at)
        ipd_amount_expr = case((IPDFinalBill.status == "paid", IPDFinalBill.net_total), else_=IPDFinalBill.advance_adjusted)
        
        ipd_rev_res = await self.db.execute(
            select(
                func.coalesce(func.sum(ipd_amount_expr), 0.0),
                func.coalesce(func.sum(IPDFinalBill.refund_amount), 0.0),
                func.coalesce(func.sum(case((or_(IPDFinalBill.status == "paid", IPDFinalBill.advance_adjusted > 0), 1), else_=0)), 0),
                func.coalesce(func.sum(case((
                    and_(func.month(ipd_dt) == current_month, func.year(ipd_dt) == current_year, or_(IPDFinalBill.status == "paid", IPDFinalBill.advance_adjusted > 0)),
                    ipd_amount_expr
                ), else_=0.0)), 0.0),
                func.coalesce(func.sum(case((
                    and_(func.year(ipd_dt) == current_year, or_(IPDFinalBill.status == "paid", IPDFinalBill.advance_adjusted > 0)),
                    ipd_amount_expr
                ), else_=0.0)), 0.0),
                func.coalesce(func.sum(case((
                    and_(func.date(ipd_dt) == today, or_(IPDFinalBill.status == "paid", IPDFinalBill.advance_adjusted > 0)),
                    ipd_amount_expr
                ), else_=0.0)), 0.0)
            ).where(IPDFinalBill.is_deleted.is_(False))
        )
        ipd_revenue, ipd_refunds, ipd_payments_count, ipd_monthly_revenue, ipd_yearly_revenue, ipd_today_collection = ipd_rev_res.one()

        total_revenue = b_revenue + ipd_revenue
        total_refunds = b_refunds + ipd_refunds
        total_payments = b_payments_count + ipd_payments_count
        monthly_revenue = b_monthly_revenue + ipd_monthly_revenue
        yearly_revenue = b_yearly_revenue + ipd_yearly_revenue
        today_collection = b_today_collection + ipd_today_collection

        # 6. Insurance Claims
        ins_res = await self.db.execute(
            select(
                func.count(),
                func.coalesce(func.sum(case((InsuranceClaim.status.in_(["submitted", "pending"]), 1), else_=0)), 0),
                func.coalesce(func.sum(case((InsuranceClaim.status == "approved", 1), else_=0)), 0)
            )
        )
        insurance_claims, pending_claims, approved_claims = ins_res.one()

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