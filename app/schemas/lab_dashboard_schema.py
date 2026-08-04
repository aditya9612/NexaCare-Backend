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


class CategoryVolumeMetric(BaseModel):
    category: str
    count: int
    percentage: float = 0.0


class TurnaroundTrendMetric(BaseModel):
    label: str
    avg_hours: float


class CategoryPerformanceMetric(BaseModel):
    category: str
    total_tests: int
    approved_reports: int
    avg_turnaround_hours: float
    completion_rate: float
    abnormal_rate: float


class DailyReportSummary(BaseModel):
    total_reports: int
    approved_reports: int
    pending_reports: int


class MonthlyReportSummary(BaseModel):
    total_reports: int
    approved_reports: int
    pending_reports: int


class RevenueReport(BaseModel):
    total_revenue: float
    period_revenue: float
    currency: str = "USD"


class PerformanceMetric(BaseModel):
    staff_name: str
    samples_collected: int
    avg_turnaround_hours: float


class PerformanceTracking(BaseModel):
    overall_efficiency: float
    metrics: List[PerformanceMetric]


class LabAnalyticsSummaryResponse(BaseModel):
    total_approved_reports: int
    approved_reports_growth_percentage: float = 0.0
    approved_reports_subtext: str = "+0% from previous period"
    avg_turnaround_hours: float
    turnaround_target_benchmark_hours: float = 3.0
    turnaround_subtext: str = "Target benchmark: < 3.0 Hours"
    abnormal_detect_rate: float
    abnormal_detect_subtext: str = "Includes critical STAT values"
    completion_rate: float
    completion_rate_subtext: str = "Specimen to verified report ratio"
    volume_by_category: List[CategoryVolumeMetric]
    turnaround_time_trend: List[TurnaroundTrendMetric]
    category_performance_metrics: List[CategoryPerformanceMetric]
    daily_report_summary: DailyReportSummary
    monthly_report_summary: MonthlyReportSummary
    revenue_report: RevenueReport
    performance_tracking: PerformanceTracking

