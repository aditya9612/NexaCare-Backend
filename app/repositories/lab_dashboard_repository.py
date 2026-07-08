from datetime import datetime
from typing import Any, Dict, List, Optional
from sqlalchemy import func, select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.lab_model import LabReport, LabTest, Sample, TestOrder, TestResult
from app.models.patient_model import Patient
from app.core.constants import LabOrderStatus, LabReportStatus, SampleStatus

class LabDashboardRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _apply_date_filter(self, query, column, start_date: Optional[datetime], end_date: Optional[datetime]):
        if start_date is not None:
            query = query.where(column >= start_date)
        if end_date is not None:
            query = query.where(column <= end_date)
        return query

    async def get_test_order_status_counts(
        self, start_date: Optional[datetime], end_date: Optional[datetime]
    ) -> Dict[str, int]:
        query = select(TestOrder.status, func.count(TestOrder.id)).where(TestOrder.is_deleted.is_(False))
        query = self._apply_date_filter(query, TestOrder.ordered_at, start_date, end_date)
        query = query.group_by(TestOrder.status)
        
        result = await self.db.execute(query)
        counts = {status: count for status, count in result.all()}
        return counts

    async def get_samples_collected_count(
        self, start_date: Optional[datetime], end_date: Optional[datetime]
    ) -> int:
        query = select(func.count(Sample.id)).where(Sample.status == SampleStatus.COLLECTED)
        query = self._apply_date_filter(query, Sample.created_at, start_date, end_date)
        return (await self.db.scalar(query)) or 0

    async def get_report_status_counts(
        self, start_date: Optional[datetime], end_date: Optional[datetime]
    ) -> Dict[str, int]:
        query = select(LabReport.status, func.count(LabReport.id))
        query = self._apply_date_filter(query, LabReport.created_at, start_date, end_date)
        query = query.group_by(LabReport.status)
        
        result = await self.db.execute(query)
        counts = {status: count for status, count in result.all()}
        return counts

    async def get_critical_reports_count(
        self, start_date: Optional[datetime], end_date: Optional[datetime]
    ) -> int:
        # Count test orders in range that have at least one critical test result
        query = (
            select(func.count(func.distinct(TestOrder.id)))
            .select_from(TestOrder)
            .join(TestResult, TestResult.test_order_id == TestOrder.id)
            .where(
                TestOrder.is_deleted.is_(False),
                TestResult.is_critical.is_(True)
            )
        )
        query = self._apply_date_filter(query, TestOrder.ordered_at, start_date, end_date)
        return (await self.db.scalar(query)) or 0

    async def get_reports_delivered_count(
        self, start_date: Optional[datetime], end_date: Optional[datetime]
    ) -> int:
        # Delivered counts are approved reports with report_path generated
        query = select(func.count(LabReport.id)).where(
            LabReport.status == LabReportStatus.APPROVED,
            LabReport.report_path.is_not(None)
        )
        query = self._apply_date_filter(query, LabReport.created_at, start_date, end_date)
        return (await self.db.scalar(query)) or 0

    async def get_recent_test_orders(
        self, start_date: Optional[datetime], end_date: Optional[datetime], limit: int = 10
    ) -> List[Dict[str, Any]]:
        query = (
            select(
                TestOrder.id,
                TestOrder.order_number,
                TestOrder.patient_id,
                Patient.first_name,
                Patient.last_name,
                LabTest.test_name,
                TestOrder.status,
                TestOrder.priority,
                TestOrder.ordered_at
            )
            .select_from(TestOrder)
            .join(Patient, Patient.id == TestOrder.patient_id)
            .join(LabTest, LabTest.id == TestOrder.lab_test_id)
            .where(TestOrder.is_deleted.is_(False))
        )
        query = self._apply_date_filter(query, TestOrder.ordered_at, start_date, end_date)
        query = query.order_by(TestOrder.ordered_at.desc()).limit(limit)
        
        result = await self.db.execute(query)
        orders = []
        for row in result.all():
            orders.append({
                "id": row[0],
                "order_number": row[1],
                "patient_id": row[2],
                "patient_name": f"{row[3]} {row[4]}".strip(),
                "test_name": row[5],
                "status": row[6],
                "priority": row[7],
                "ordered_at": row[8]
            })
        return orders

    async def get_critical_alerts(
        self, start_date: Optional[datetime], end_date: Optional[datetime], limit: int = 10
    ) -> List[Dict[str, Any]]:
        query = (
            select(
                TestResult.id,
                TestResult.test_order_id,
                TestOrder.order_number,
                Patient.first_name,
                Patient.last_name,
                TestResult.parameter_name,
                TestResult.result_value,
                TestResult.normal_range,
                TestResult.entered_at
            )
            .select_from(TestResult)
            .join(TestOrder, TestOrder.id == TestResult.test_order_id)
            .join(Patient, Patient.id == TestOrder.patient_id)
            .where(
                TestOrder.is_deleted.is_(False),
                TestResult.is_critical.is_(True)
            )
        )
        query = self._apply_date_filter(query, TestResult.created_at, start_date, end_date)
        query = query.order_by(TestResult.created_at.desc()).limit(limit)
        
        result = await self.db.execute(query)
        alerts = []
        for row in result.all():
            alerts.append({
                "result_id": row[0],
                "test_order_id": row[1],
                "order_number": row[2],
                "patient_name": f"{row[3]} {row[4]}".strip(),
                "parameter_name": row[5],
                "result_value": row[6],
                "normal_range": row[7],
                "entered_at": row[8]
            })
        return alerts

    async def get_pending_report_approvals(
        self, start_date: Optional[datetime], end_date: Optional[datetime], limit: int = 10
    ) -> List[Dict[str, Any]]:
        query = (
            select(
                LabReport.id,
                LabReport.report_number,
                LabReport.test_order_id,
                TestOrder.order_number,
                LabTest.test_name,
                Patient.first_name,
                Patient.last_name,
                LabReport.created_at
            )
            .select_from(LabReport)
            .join(TestOrder, TestOrder.id == LabReport.test_order_id)
            .join(LabTest, LabTest.id == TestOrder.lab_test_id)
            .join(Patient, Patient.id == TestOrder.patient_id)
            .where(
                TestOrder.is_deleted.is_(False),
                LabReport.status == LabReportStatus.PENDING_APPROVAL
            )
        )
        query = self._apply_date_filter(query, LabReport.created_at, start_date, end_date)
        query = query.order_by(LabReport.created_at.desc()).limit(limit)
        
        result = await self.db.execute(query)
        approvals = []
        for row in result.all():
            approvals.append({
                "report_id": row[0],
                "report_number": row[1],
                "test_order_id": row[2],
                "order_number": row[3],
                "test_name": row[4],
                "patient_name": f"{row[5]} {row[6]}".strip(),
                "generated_at": row[7]
            })
        return approvals
