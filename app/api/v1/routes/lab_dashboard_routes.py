from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select

from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.models.user_model import User
from app.models.staff_model import Staff
from app.core.exceptions import BadRequestException
from app.schemas.common_schema import APIResponse
from app.schemas.lab_dashboard_schema import LabDashboardResponse, LabAnalyticsSummaryResponse
from app.services.lab_dashboard_service import LabDashboardService
from app.utils.lab_dashboard_pdf import generate_lab_dashboard_pdf

router = APIRouter()

ALLOWED_FILTERS = {"today", "7_days", "30_days", "month_to_date", "month", "3_month", "overall", "custom"}

def _validate_filter_params(
    time_filter: str,
    start_date: Optional[date],
    end_date: Optional[date]
) -> None:
    if time_filter not in ALLOWED_FILTERS:
        raise BadRequestException(f"Invalid filter. Allowed values: {', '.join(sorted(ALLOWED_FILTERS))}")
    if time_filter == "custom":
        if not start_date or not end_date:
            raise BadRequestException("start_date and end_date are required when filter is 'custom'")
        if start_date > end_date:
            raise BadRequestException("start_date cannot be after end_date")

async def _get_technician_department_id(db: DbSession, current_user: User) -> Optional[int]:
    role_name = current_user.role.name.lower() if current_user and current_user.role else ""
    if role_name in ["lab technician", "lab_technician"]:
        staff_result = await db.execute(
            select(Staff).where(Staff.email == current_user.email)
        )
        staff = staff_result.scalar_one_or_none()
        if not staff or not staff.department_id:
            raise BadRequestException("Lab technician department is not assigned")
        return staff.department_id
    return None

@router.get("", response_model=APIResponse[LabDashboardResponse])
async def get_lab_dashboard(
    db: DbSession,
    current_user: CurrentUser,
    time_filter: str = Query("today", alias="filter"),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    _: User = Depends(require_permission("lab", "read")),
):
    _validate_filter_params(time_filter, start_date, end_date)
    
    dept_id = await _get_technician_department_id(db, current_user)
    dashboard_data = await LabDashboardService(db).get_dashboard_data(
        time_filter=time_filter,
        start_date=start_date,
        end_date=end_date,
        department_id=dept_id
    )
    return APIResponse(message="Lab dashboard data retrieved", data=dashboard_data)


@router.get("/analytics", response_model=APIResponse[LabAnalyticsSummaryResponse])
async def get_lab_analytics_dashboard(
    db: DbSession,
    current_user: CurrentUser,
    time_filter: str = Query("7_days", alias="filter"),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    _: User = Depends(require_permission("lab", "read")),
):
    _validate_filter_params(time_filter, start_date, end_date)

    dept_id = await _get_technician_department_id(db, current_user)
    analytics_data = await LabDashboardService(db).get_analytics_data(
        time_filter=time_filter,
        start_date=start_date,
        end_date=end_date,
        department_id=dept_id
    )
    return APIResponse(message="Lab reports & analytics retrieved", data=analytics_data)


@router.get("/download/pdf")
async def download_lab_dashboard_pdf(
    db: DbSession,
    current_user: CurrentUser,
    time_filter: str = Query("today", alias="filter"),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    _: User = Depends(require_permission("lab", "read")),
):
    _validate_filter_params(time_filter, start_date, end_date)
    
    dept_id = await _get_technician_department_id(db, current_user)
    service = LabDashboardService(db)
    dashboard_data = await service.get_dashboard_data(
        time_filter=time_filter,
        start_date=start_date,
        end_date=end_date,
        department_id=dept_id
    )
    
    # Calculate date range string for PDF header
    start_dt, end_dt = service.get_date_range(time_filter, start_date, end_date)
    if start_dt and end_dt:
        date_range_str = f"{start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')}"
    else:
        date_range_str = "All Time (Overall)"
        
    pdf_bytes = await generate_lab_dashboard_pdf(
        data=dashboard_data,
        filter_applied=time_filter,
        date_range=date_range_str
    )
    
    filename = f"lab_dashboard_{time_filter}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "Access-Control-Expose-Headers": "Content-Disposition"
        }
    )
