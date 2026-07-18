from datetime import date

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.models.user_model import User
from app.schemas.analytics_schema import (
    AppointmentAnalyticsResponse,
    DashboardSummaryResponse,
    DoctorAnalyticsResponse,
    ExportListItem,
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


@router.get("/export/pdf")
async def export_pdf(
    report_type: str,
    db: DbSession,
    current_user: CurrentUser,
    start_date: date | None = None,
    end_date: date | None = None,
    _: User = Depends(require_permission("analytics", "export")),
):
    from app.services.analytics_service import AnalyticsService
    from app.schemas.analytics_schema import ExportReportRequest
    from app.models.analytics_model import ReportExport, ReportExportFormat, ReportExportStatus
    from app.core.exceptions import NotFoundException
    import json
    import os

    filters = {}
    if start_date:
        filters["start_date"] = start_date.isoformat()
    if end_date:
        filters["end_date"] = end_date.isoformat()

    data = ExportReportRequest(
        report_type=report_type,
        start_date=start_date,
        end_date=end_date,
        filters=filters
    )

    service = AnalyticsService(db)
    export = ReportExport(
        report_type=data.report_type,
        export_format=ReportExportFormat.PDF,
        status=ReportExportStatus.PENDING,
        filters=json.dumps(data.filters or {}),
        requested_by=current_user.id,
    )
    export = await service.repo.create_export(export)
    await service.process_export(export.id)
    await db.refresh(export)

    def resolve_disk_path(path_str: str | None) -> str | None:
        if not path_str:
            return None
        p = path_str.replace("\\", "/")
        if p.startswith("/"):
            p = p.lstrip("/")
        if p.startswith("uploads/"):
            return os.path.join("app", p)
        return p

    disk_path = resolve_disk_path(export.file_path)
    if not disk_path or not os.path.exists(disk_path):
        raise NotFoundException("Exported PDF file not found or generation failed")

    return FileResponse(
        disk_path,
        media_type="application/pdf",
        filename=f"{report_type}_report_{export.id}.pdf",
    )


@router.get("/export/excel")
async def export_excel(
    report_type: str,
    db: DbSession,
    current_user: CurrentUser,
    start_date: date | None = None,
    end_date: date | None = None,
    _: User = Depends(require_permission("analytics", "export")),
):
    from app.services.analytics_service import AnalyticsService
    from app.schemas.analytics_schema import ExportReportRequest
    from app.models.analytics_model import ReportExport, ReportExportFormat, ReportExportStatus
    from app.core.exceptions import NotFoundException
    import json
    import os

    filters = {}
    if start_date:
        filters["start_date"] = start_date.isoformat()
    if end_date:
        filters["end_date"] = end_date.isoformat()

    data = ExportReportRequest(
        report_type=report_type,
        start_date=start_date,
        end_date=end_date,
        filters=filters
    )

    service = AnalyticsService(db)
    export = ReportExport(
        report_type=data.report_type,
        export_format=ReportExportFormat.EXCEL,
        status=ReportExportStatus.PENDING,
        filters=json.dumps(data.filters or {}),
        requested_by=current_user.id,
    )
    export = await service.repo.create_export(export)
    await service.process_export(export.id)
    await db.refresh(export)

    def resolve_disk_path(path_str: str | None) -> str | None:
        if not path_str:
            return None
        p = path_str.replace("\\", "/")
        if p.startswith("/"):
            p = p.lstrip("/")
        if p.startswith("uploads/"):
            return os.path.join("app", p)
        return p

    disk_path = resolve_disk_path(export.file_path)
    if not disk_path or not os.path.exists(disk_path):
        raise NotFoundException("Exported Excel file not found or generation failed")

    # Dynamically select media_type and filename based on file extension
    ext = os.path.splitext(disk_path)[1].lower()
    if ext == ".xlsx":
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = f"{report_type}_report_{export.id}.xlsx"
    elif ext == ".csv":
        media_type = "text/csv"
        filename = f"{report_type}_report_{export.id}.csv"
    else:
        media_type = "application/octet-stream"
        filename = f"{report_type}_report_{export.id}{ext}"

    return FileResponse(
        disk_path,
        media_type=media_type,
        filename=filename,
    )


@router.get("/exports", response_model=None)
async def list_exports(
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    report_type: str | None = None,
    export_id: int | None = None,
    _: User = Depends(require_permission("analytics", "read")),
):
    from app.services.analytics_service import AnalyticsService
    from app.core.exceptions import NotFoundException
    from app.schemas.common_schema import APIResponse
    import os

    # If export_id is provided, download that file
    if export_id is not None:
        service = AnalyticsService(db)
        export = await service.repo.get_export(export_id)
        if not export:
            raise NotFoundException("Export not found")
            
        def resolve_disk_path(path_str: str | None) -> str | None:
            if not path_str:
                return None
            p = path_str.replace("\\", "/")
            if p.startswith("/"):
                p = p.lstrip("/")
            if p.startswith("uploads/"):
                return os.path.join("app", p)
            return p

        disk_path = resolve_disk_path(export.file_path)
        if not disk_path or not os.path.exists(disk_path):
            raise NotFoundException("Export file not found or generation not completed")

        # Dynamically select media_type and filename based on file extension
        ext = os.path.splitext(disk_path)[1].lower()
        if ext == ".pdf":
            media_type = "application/pdf"
            filename = f"{export.report_type}_report_{export.id}.pdf"
        elif ext == ".xlsx":
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            filename = f"{export.report_type}_report_{export.id}.xlsx"
        elif ext == ".csv":
            media_type = "text/csv"
            filename = f"{export.report_type}_report_{export.id}.csv"
        else:
            media_type = "application/octet-stream"
            filename = f"{export.report_type}_report_{export.id}{ext}"

        return FileResponse(
            disk_path,
            media_type=media_type,
            filename=filename,
        )

    result = await AnalyticsService(db).list_exports(page, size, report_type)
    return APIResponse(message="Exports retrieved", data=result)


@router.get("/exports/{export_id}/download")
async def download_export(
    export_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("analytics", "read")),
):
    from app.services.analytics_service import AnalyticsService
    from app.core.exceptions import NotFoundException
    import os

    service = AnalyticsService(db)
    export = await service.repo.get_export(export_id)
    if not export:
        raise NotFoundException("Export not found")
        
    def resolve_disk_path(path_str: str | None) -> str | None:
        if not path_str:
            return None
        p = path_str.replace("\\", "/")
        if p.startswith("/"):
            p = p.lstrip("/")
        if p.startswith("uploads/"):
            return os.path.join("app", p)
        return p

    disk_path = resolve_disk_path(export.file_path)
    if not disk_path or not os.path.exists(disk_path):
        raise NotFoundException("Export file not found or generation not completed")

    # Dynamically select media_type and filename based on file extension
    ext = os.path.splitext(disk_path)[1].lower()
    if ext == ".pdf":
        media_type = "application/pdf"
        filename = f"{export.report_type}_report_{export.id}.pdf"
    elif ext == ".xlsx":
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = f"{export.report_type}_report_{export.id}.xlsx"
    elif ext == ".csv":
        media_type = "text/csv"
        filename = f"{export.report_type}_report_{export.id}.csv"
    else:
        media_type = "application/octet-stream"
        filename = f"{export.report_type}_report_{export.id}{ext}"

    return FileResponse(
        disk_path,
        media_type=media_type,
        filename=filename,
    )
