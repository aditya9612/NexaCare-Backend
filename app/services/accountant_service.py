import calendar
from datetime import date
from typing import List, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.accountant_repository import AccountantRepository
from app.schemas.accountant_schema import (
    AccountantDashboardResponse,
    RevenueForecast,
    ClaimPending,
    ForecastMonthlyData,
    AIRevenueForecast,
    ExpensePrediction,
)


class AccountantService:
    def __init__(self, db: AsyncSession):
        self.repo = AccountantRepository(db)

    async def get_dashboard(self) -> AccountantDashboardResponse:
        stats = await self.repo.get_dashboard_stats()

        now = date.today()
        current_year = now.year
        current_month = now.month
        days_elapsed = max(1, now.day)
        total_days_in_month = calendar.monthrange(current_year, current_month)[1]

        # 1. Revenue Forecast
        revenue_forecast = await self._calculate_revenue_forecast(
            stats=stats,
            current_year=current_year,
            current_month=current_month,
            days_elapsed=days_elapsed,
            total_days_in_month=total_days_in_month,
        )

        # 2. Claim Pending
        claim_pending = self._calculate_claim_pending(stats)

        # 3. AI Revenue Forecast (Past 6 months Actual vs Predicted)
        ai_revenue_forecast = await self._calculate_ai_revenue_forecast(
            current_year=current_year,
            current_month=current_month,
            current_projected=revenue_forecast.projected_revenue,
        )

        # 4. Expense Prediction (Past 6 months Actual vs Predicted)
        expense_prediction = await self._calculate_expense_prediction(
            current_year=current_year,
            current_month=current_month,
            days_elapsed=days_elapsed,
            total_days_in_month=total_days_in_month,
        )

        return AccountantDashboardResponse(
            **stats,
            revenue_forecast=revenue_forecast,
            claim_pending=claim_pending,
            ai_revenue_forecast=ai_revenue_forecast,
            expense_prediction=expense_prediction,
        )

    async def _calculate_revenue_forecast(
        self,
        stats: Dict[str, Any],
        current_year: int,
        current_month: int,
        days_elapsed: int,
        total_days_in_month: int,
    ) -> RevenueForecast:
        current_month_revenue = float(stats.get("monthly_revenue", 0.0))
        projected_revenue = round((current_month_revenue / days_elapsed) * total_days_in_month, 2)

        if current_month == 1:
            prev_month, prev_year = 12, current_year - 1
        else:
            prev_month, prev_year = current_month - 1, current_year

        prev_month_revenue = await self.repo.get_month_revenue(prev_year, prev_month)

        if prev_month_revenue > 0:
            growth_percentage = round(((projected_revenue - prev_month_revenue) / prev_month_revenue) * 100, 1)
        elif projected_revenue > 0:
            growth_percentage = 100.0
        else:
            growth_percentage = 0.0

        if growth_percentage > 0.5:
            trend = "up"
        elif growth_percentage < -0.5:
            trend = "down"
        else:
            trend = "stable"

        month_name = calendar.month_name[current_month]
        proj_str = self._format_amount_k(projected_revenue)
        sign = "+" if growth_percentage >= 0 else ""
        message = f"{month_name} projected at ₹{proj_str} ({sign}{growth_percentage:.1f}%)"

        return RevenueForecast(
            projected_revenue=projected_revenue,
            growth_percentage=growth_percentage,
            trend=trend,
            message=message,
        )

    def _calculate_claim_pending(self, stats: Dict[str, Any]) -> ClaimPending:
        count = int(stats.get("pending_claims", 0))
        status = "attention" if count > 10 else ("stable" if count > 0 else "up")
        message = f"{count} insurance claims awaiting verification" if count > 0 else "No pending insurance claims"

        return ClaimPending(
            count=count,
            status=status,
            message=message,
        )

    async def _calculate_ai_revenue_forecast(
        self,
        current_year: int,
        current_month: int,
        current_projected: float,
    ) -> AIRevenueForecast:
        # Build 6-month window
        months_window = self._get_past_months_window(current_year, current_month, count=6)
        start_date = date(months_window[0]["year"], months_window[0]["month"], 1)
        end_date = date(
            current_year,
            current_month,
            calendar.monthrange(current_year, current_month)[1],
        )

        history = await self.repo.get_monthly_revenue_history(start_date, end_date)
        rev_map = {(row["year"], row["month"]): row["revenue"] for row in history}

        chart_data: List[ForecastMonthlyData] = []
        recent_actuals: List[float] = []

        for item in months_window:
            y, m, m_label = item["year"], item["month"], item["label"]
            actual = rev_map.get((y, m), 0.0)

            # Predict based on prior trend
            if y == current_year and m == current_month:
                predicted = current_projected if current_projected > 0 else round(actual * 1.05, 2)
            else:
                if recent_actuals and any(v > 0 for v in recent_actuals):
                    valid_vals = [v for v in recent_actuals if v > 0]
                    avg_val = sum(valid_vals) / len(valid_vals)
                    predicted = round(avg_val * 1.05, 2)
                elif actual > 0:
                    predicted = round(actual * 1.05, 2)
                else:
                    predicted = 0.0

            recent_actuals.append(actual)
            chart_data.append(
                ForecastMonthlyData(
                    month=m_label,
                    actual=round(actual, 2),
                    predicted=round(predicted, 2),
                )
            )

        return AIRevenueForecast(chart_data=chart_data)

    async def _calculate_expense_prediction(
        self,
        current_year: int,
        current_month: int,
        days_elapsed: int,
        total_days_in_month: int,
    ) -> ExpensePrediction:
        months_window = self._get_past_months_window(current_year, current_month, count=6)
        start_date = date(months_window[0]["year"], months_window[0]["month"], 1)
        end_date = date(
            current_year,
            current_month,
            calendar.monthrange(current_year, current_month)[1],
        )

        history = await self.repo.get_monthly_expense_history(start_date, end_date)
        exp_map = {(row["year"], row["month"]): row["expense"] for row in history}

        chart_data: List[ForecastMonthlyData] = []
        recent_actuals: List[float] = []

        for item in months_window:
            y, m, m_label = item["year"], item["month"], item["label"]
            actual = exp_map.get((y, m), 0.0)

            if y == current_year and m == current_month:
                current_projected = round((actual / days_elapsed) * total_days_in_month, 2) if actual > 0 else 0.0
                predicted = current_projected if current_projected > 0 else round(actual * 1.03, 2)
            else:
                if recent_actuals and any(v > 0 for v in recent_actuals):
                    valid_vals = [v for v in recent_actuals if v > 0]
                    avg_val = sum(valid_vals) / len(valid_vals)
                    predicted = round(avg_val * 1.03, 2)
                elif actual > 0:
                    predicted = round(actual * 1.03, 2)
                else:
                    predicted = 0.0

            recent_actuals.append(actual)
            chart_data.append(
                ForecastMonthlyData(
                    month=m_label,
                    actual=round(actual, 2),
                    predicted=round(predicted, 2),
                )
            )

        return ExpensePrediction(chart_data=chart_data)

    def _get_past_months_window(self, year: int, month: int, count: int = 6) -> List[Dict[str, Any]]:
        window = []
        for i in range(count - 1, -1, -1):
            m = month - i
            y = year
            while m <= 0:
                m += 12
                y -= 1
            window.append({
                "year": y,
                "month": m,
                "label": calendar.month_abbr[m],
            })
        return window

    def _format_amount_k(self, amount: float) -> str:
        abs_amt = abs(amount)
        if abs_amt >= 1000:
            return f"{amount / 1000:.0f}K"
        return f"{amount:.0f}"