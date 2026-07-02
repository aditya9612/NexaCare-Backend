from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.lab_dashboard_repository import LabDashboardRepository
from app.schemas.lab_dashboard_schema import (
    LabDashboardResponse,
    RecentTestOrder,
    LabDashboardCriticalAlert,
    PendingReportApproval,
)
from app.core.constants import LabOrderStatus, LabReportStatus
from app.utils.helpers import utc_now

class LabDashboardService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = LabDashboardRepository(db)

    def get_date_range(
        self,
        time_filter: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> tuple[Optional[datetime], Optional[datetime]]:
        now_dt = utc_now()
        today_date = now_dt.date()

        if time_filter == "today":
            start = datetime.combine(today_date, time.min)
            end = datetime.combine(today_date, time.max)
            return start, end

        elif time_filter == "month":
            start = datetime.combine(today_date.replace(day=1), time.min)
            end = now_dt
            return start, end

        elif time_filter == "3_month":
            # Roughly 90 days ago
            start_date_val = today_date - timedelta(days=90)
            start = datetime.combine(start_date_val, time.min)
            end = now_dt
            return start, end

        elif time_filter == "custom":
            if not start_date or not end_date:
                # Fallback to today if custom is selected but dates are not provided
                start = datetime.combine(today_date, time.min)
                end = datetime.combine(today_date, time.max)
                return start, end
            start = datetime.combine(start_date, time.min)
            end = datetime.combine(end_date, time.max)
            return start, end

        else: # overall
            return None, None

    async def get_dashboard_data(
        self,
        time_filter: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> LabDashboardResponse:
        start_dt, end_dt = self.get_date_range(time_filter, start_date, end_date)

        # Get status counts for test orders
        order_counts = await self.repo.get_test_order_status_counts(start_dt, end_dt)
        total_tests = sum(order_counts.values())
        pending_tests = order_counts.get(LabOrderStatus.ORDERED, 0)
        tests_in_progress = order_counts.get(LabOrderStatus.IN_PROGRESS, 0)
        completed_tests = order_counts.get(LabOrderStatus.COMPLETED, 0)

        # Get samples collected count
        samples_collected = await self.repo.get_samples_collected_count(start_dt, end_dt)

        # Get report counts
        report_counts = await self.repo.get_report_status_counts(start_dt, end_dt)
        reports_pending_approval = report_counts.get(LabReportStatus.PENDING_APPROVAL, 0)
        approved_reports = report_counts.get(LabReportStatus.APPROVED, 0)

        # Get critical and delivered counts
        critical_reports = await self.repo.get_critical_reports_count(start_dt, end_dt)
        reports_delivered = await self.repo.get_reports_delivered_count(start_dt, end_dt)

        # Fetch detailed lists
        recent_orders_data = await self.repo.get_recent_test_orders(start_dt, end_dt)
        critical_alerts_data = await self.repo.get_critical_alerts(start_dt, end_dt)
        pending_approvals_data = await self.repo.get_pending_report_approvals(start_dt, end_dt)

        # Convert to Pydantic responses
        recent_test_orders = [RecentTestOrder(**o) for o in recent_orders_data]
        critical_alerts = [LabDashboardCriticalAlert(**a) for a in critical_alerts_data]
        pending_report_approvals = [PendingReportApproval(**p) for p in pending_approvals_data]

        return LabDashboardResponse(
            total_tests=total_tests,
            pending_tests=pending_tests,
            tests_in_progress=tests_in_progress,
            completed_tests=completed_tests,
            samples_collected=samples_collected,
            reports_pending_approval=reports_pending_approval,
            approved_reports=approved_reports,
            critical_reports=critical_reports,
            reports_delivered=reports_delivered,
            recent_test_orders=recent_test_orders,
            critical_alerts=critical_alerts,
            pending_report_approvals=pending_report_approvals,
        )
