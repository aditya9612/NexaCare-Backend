from datetime import date

from fastapi import APIRouter, Depends

from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.models.user_model import User
from app.schemas.analytics_schema import (
    AppointmentAnalyticsResponse,
    DashboardSummaryResponse,
    DoctorAnalyticsResponse,
    ExportReportRequest,
    ExportReportResponse,
    KPIResponse,
    ModuleAnalyticsResponse,
    PatientAnalyticsResponse,
    ReportListItem,
    RevenueAnalyticsResponse,
)
from app.schemas.common_schema import APIResponse
from app.services.analytics_service import AnalyticsService
from app.utils.pagination import PaginatedResult

router = APIRouter()


@router.get("/dashboard", response_model=APIResponse[DashboardSummaryResponse])
async def dashboard(
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("analytics", "read")),
):
    data = await AnalyticsService(db).get_dashboard()
    return APIResponse(message="Dashboard summary retrieved", data=data)


@router.get("/revenue", response_model=APIResponse[RevenueAnalyticsResponse])
async def revenue(
    db: DbSession,
    current_user: CurrentUser,
    start_date: date | None = None,
    end_date: date | None = None,
    _: User = Depends(require_permission("analytics", "read")),
):
    data = await AnalyticsService(db).get_revenue_analytics(start_date, end_date)
    return APIResponse(message="Revenue analytics retrieved", data=data)


@router.get("/appointments", response_model=APIResponse[AppointmentAnalyticsResponse])
async def appointments(
    db: DbSession,
    current_user: CurrentUser,
    start_date: date | None = None,
    end_date: date | None = None,
    _: User = Depends(require_permission("analytics", "read")),
):
    data = await AnalyticsService(db).get_appointment_analytics(start_date, end_date)
    return APIResponse(message="Appointment analytics retrieved", data=data)


@router.get("/doctors", response_model=APIResponse[DoctorAnalyticsResponse])
async def doctors(
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("analytics", "read")),
):
    data = await AnalyticsService(db).get_doctor_analytics()
    return APIResponse(message="Doctor analytics retrieved", data=data)


@router.get("/patients", response_model=APIResponse[PatientAnalyticsResponse])
async def patients(
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("analytics", "read")),
):
    data = await AnalyticsService(db).get_patient_analytics()
    return APIResponse(message="Patient analytics retrieved", data=data)


@router.get("/ai-chatbot", response_model=APIResponse[ModuleAnalyticsResponse])
async def ai_chatbot(
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("analytics", "read")),
):
    data = await AnalyticsService(db).get_ai_chatbot_analytics()
    return APIResponse(message="AI chatbot analytics retrieved", data=data)


@router.get("/voice-reminder", response_model=APIResponse[ModuleAnalyticsResponse])
async def voice_reminder(
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("analytics", "read")),
):
    data = await AnalyticsService(db).get_voice_analytics()
    return APIResponse(message="Voice reminder analytics retrieved", data=data)


@router.get("/whatsapp", response_model=APIResponse[ModuleAnalyticsResponse])
async def whatsapp(
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("analytics", "read")),
):
    data = await AnalyticsService(db).get_whatsapp_analytics()
    return APIResponse(message="WhatsApp analytics retrieved", data=data)


@router.get("/kpi", response_model=APIResponse[list[KPIResponse]])
async def kpi_list(
    db: DbSession,
    current_user: CurrentUser,
    category: str | None = None,
    _: User = Depends(require_permission("analytics", "read")),
):
    kpis = await AnalyticsService(db).list_kpis(category)
    return APIResponse(message="KPIs retrieved", data=kpis)


@router.get("/reports", response_model=APIResponse[PaginatedResult[ReportListItem]])
async def reports(
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    report_type: str | None = None,
    _: User = Depends(require_permission("analytics", "read")),
):
    result = await AnalyticsService(db).list_reports(page, size, report_type)
    return APIResponse(message="Reports retrieved", data=result)


@router.post("/export/pdf", response_model=APIResponse[ExportReportResponse], status_code=202)
async def export_pdf(
    data: ExportReportRequest,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("analytics", "export")),
):
    result = await AnalyticsService(db).request_export(data, current_user.id)
    return APIResponse(message="PDF export queued", data=result)


@router.post("/export/excel", response_model=APIResponse[ExportReportResponse], status_code=202)
async def export_excel(
    data: ExportReportRequest,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("analytics", "export")),
):
    result = await AnalyticsService(db).request_export_excel(data, current_user.id)
    return APIResponse(message="Excel export queued", data=result)
