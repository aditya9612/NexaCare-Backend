from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import Field

from app.schemas.common_schema import BaseSchema


class DateRangeQuery(BaseSchema):
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class ChartDataPoint(BaseSchema):
    label: str
    value: float
    metadata: Optional[Dict[str, Any]] = None


class ChartSeries(BaseSchema):
    name: str
    data: List[ChartDataPoint]


class DashboardSummaryResponse(BaseSchema):
    revenue: float
    appointments_today: int
    total_patients: int
    total_doctors: int
    pending_appointments: int
    ai_chat_sessions: int
    voice_calls_today: int
    whatsapp_messages_today: int
    charts: List[ChartSeries]


class RevenueAnalyticsResponse(BaseSchema):
    total_revenue: float
    paid_amount: float
    pending_amount: float
    daily_revenue: List[ChartDataPoint]
    payment_method_breakdown: List[ChartDataPoint]


class AppointmentAnalyticsResponse(BaseSchema):
    total: int
    completed: int
    cancelled: int
    no_show: int
    status_breakdown: List[ChartDataPoint]
    daily_trend: List[ChartDataPoint]
    department_breakdown: List[ChartDataPoint]


class DoctorAnalyticsResponse(BaseSchema):
    total_doctors: int
    avg_appointments_per_doctor: float
    top_doctors: List[Dict[str, Any]]
    availability_breakdown: List[ChartDataPoint]


class PatientAnalyticsResponse(BaseSchema):
    total_patients: int
    new_patients: int
    active_patients: int
    gender_breakdown: List[ChartDataPoint]
    registration_trend: List[ChartDataPoint]


class ModuleAnalyticsResponse(BaseSchema):
    module: str
    period_start: datetime
    period_end: datetime
    metrics: Dict[str, Any]
    charts: List[ChartSeries]


class KPIResponse(BaseSchema):
    id: int
    kpi_name: str
    category: str
    current_value: float
    target_value: float
    status: str
    unit: Optional[str] = None
    updated_at: datetime


class ReportListItem(BaseSchema):
    id: int
    report_name: str
    report_type: str
    period_start: datetime
    period_end: datetime
    created_at: datetime


class ExportReportRequest(BaseSchema):
    report_type: str = Field(..., description="dashboard|revenue|appointments|doctors|patients|ai_chatbot|voice|whatsapp")
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    filters: Optional[Dict[str, Any]] = None


class ExportReportResponse(BaseSchema):
    export_id: int
    status: str
    file_path: Optional[str] = None
    message: str
