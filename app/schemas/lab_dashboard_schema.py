from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field

class RecentTestOrder(BaseModel):
    id: int
    order_number: str
    patient_id: int
    patient_name: str
    test_name: str
    status: str
    priority: str
    ordered_at: datetime

class LabDashboardCriticalAlert(BaseModel):
    result_id: int
    test_order_id: int
    order_number: str
    patient_name: str
    parameter_name: str
    result_value: str
    normal_range: Optional[str] = None
    entered_at: Optional[datetime] = None

class PendingReportApproval(BaseModel):
    report_id: int
    report_number: str
    test_order_id: int
    order_number: str
    test_name: str
    patient_name: str
    generated_at: Optional[datetime] = None

class LabDashboardResponse(BaseModel):
    total_tests: int
    pending_tests: int
    tests_in_progress: int
    completed_tests: int
    samples_collected: int
    reports_pending_approval: int
    approved_reports: int
    critical_reports: int
    reports_delivered: int
    
    recent_test_orders: List[RecentTestOrder]
    critical_alerts: List[LabDashboardCriticalAlert]
    pending_report_approvals: List[PendingReportApproval]
