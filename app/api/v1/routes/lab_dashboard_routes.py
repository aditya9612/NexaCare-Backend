from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy import select

from app.core.dependencies import CurrentUser, DbSession, get_tenant_hospital_id, require_permission, resolve_tenant_id
from app.models.user_model import User
from app.models.staff_model import Staff
from app.core.exceptions import BadRequestException
from app.schemas.common_schema import APIResponse
from app.schemas.lab_dashboard_schema import LabDashboardResponse, LabAnalyticsSummaryResponse
from app.services.lab_dashboard_service import LabDashboardService
from app.utils.lab_dashboard_pdf import generate_lab_dashboard_pdf

router = APIRouter()

ALLOWED_FILTERS = {"today", "7_days", "30_days", "month_to_date", "month", "3_month", "overall", "custom"}
ALLOWED_SECTIONS = {"all", "summary", "critical_alerts", "pending_approvals", "recent_orders"}

def _validate_filter_params(
    time_filter: str,
    start_date: Optional[date],
    end_date: Optional[date]
) -> None:
    if start_date and end_date and start_date > end_date:
        raise BadRequestException("start_date cannot be after end_date")
    if time_filter not in ALLOWED_FILTERS:
        raise BadRequestException(f"Invalid filter. Allowed values: {', '.join(sorted(ALLOWED_FILTERS))}")
    if time_filter == "custom":
        if not start_date or not end_date:
            raise BadRequestException("start_date and end_date are required when filter is 'custom'")

def _validate_section_param(section: Optional[str]) -> str:
    if not section:
        return "all"
    normalized_section = section.strip().lower()
    if normalized_section not in ALLOWED_SECTIONS:
        raise BadRequestException(f"Invalid section. Allowed values: {', '.join(sorted(ALLOWED_SECTIONS))}")
    return normalized_section

async def _get_technician_department_id(db: DbSession, current_user: User) -> Optional[int]:
    role_name = current_user.role.name.lower() if current_user and current_user.role else ""
    if role_name in ["lab technician", "lab_technician"]:
        query = select(Staff).where(
            Staff.email == current_user.email,
            Staff.is_deleted.is_(False)
        )
        if current_user.hospital_id:
            query = query.where(Staff.hospital_id == current_user.hospital_id)
        staff_result = await db.execute(query)
        staff = staff_result.scalars().first()
        if staff and staff.department_id:
            return staff.department_id
    return None

@router.get("", response_model=APIResponse[LabDashboardResponse])
async def get_lab_dashboard(
    db: DbSession,
    current_user: CurrentUser,
    time_filter: str = Query("overall", alias="filter"),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    x_hospital_id: Optional[int] = Header(None, alias="X-Hospital-Id"),
    _: User = Depends(require_permission("lab", "read")),
):
    _validate_filter_params(time_filter, start_date, end_date)
    
    dept_id = await _get_technician_department_id(db, current_user)
    hospital_id = await get_tenant_hospital_id(current_user, x_hospital_id)
    dashboard_data = await LabDashboardService(db).get_dashboard_data(
        time_filter=time_filter,
        start_date=start_date,
        end_date=end_date,
        department_id=dept_id,
        hospital_id=hospital_id,
    )
    return APIResponse(message="Lab dashboard data retrieved", data=dashboard_data)


@router.get("/analytics", response_model=APIResponse[LabAnalyticsSummaryResponse])
async def get_lab_analytics_dashboard(
    db: DbSession,
    current_user: CurrentUser,
    time_filter: str = Query("7_days", alias="filter"),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    x_hospital_id: Optional[int] = Header(None, alias="X-Hospital-Id"),
    _: User = Depends(require_permission("lab", "read")),
):
    _validate_filter_params(time_filter, start_date, end_date)

    dept_id = await _get_technician_department_id(db, current_user)
    hospital_id = await get_tenant_hospital_id(current_user, x_hospital_id)
    analytics_data = await LabDashboardService(db).get_analytics_data(
        time_filter=time_filter,
        start_date=start_date,
        end_date=end_date,
        department_id=dept_id,
        hospital_id=hospital_id,
    )
    return APIResponse(message="Lab analytics data retrieved", data=analytics_data)


@router.get("/download/pdf")
async def download_lab_dashboard_pdf(
    db: DbSession,
    current_user: CurrentUser,
    time_filter: str = Query("overall", alias="filter"),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    section: Optional[str] = Query("all"),
    x_hospital_id: Optional[int] = Header(None, alias="X-Hospital-Id"),
    _: User = Depends(require_permission("lab", "read")),
):
    _validate_filter_params(time_filter, start_date, end_date)
    validated_section = _validate_section_param(section)
    
    dept_id = await _get_technician_department_id(db, current_user)
    hospital_id = await get_tenant_hospital_id(current_user, x_hospital_id)
    service = LabDashboardService(db)
    dashboard_data = await service.get_dashboard_data(
        time_filter=time_filter,
        start_date=start_date,
        end_date=end_date,
        department_id=dept_id,
        hospital_id=hospital_id,
    )
    
    # Calculate date range string for PDF header
    start_dt, end_dt = service.get_date_range(time_filter, start_date, end_date)
    if start_dt and end_dt:
        date_range_str = f"{start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')}"
    else:
        date_range_str = "All Time (Overall)"

    hospital_name = None
    hospital_address = None
    hospital_phone = None
    hospital_email = None
    hospital_logo = None
    if hospital_id:
        from app.repositories.hospital_repository import HospitalRepository
        import os
        hospital = await HospitalRepository(db).get_by_id(hospital_id)
        if hospital:
            hospital_name = hospital.name
            hospital_address = hospital.address
            hospital_phone = hospital.phone
            hospital_email = hospital.email
            logo_attr = getattr(hospital, 'logo', None) or getattr(hospital, 'logo_path', None) or getattr(hospital, 'logo_url', None)
            if logo_attr and os.path.exists(str(logo_attr)):
                hospital_logo = os.path.abspath(str(logo_attr)).replace("\\", "/")

    pdf_bytes = await generate_lab_dashboard_pdf(
        data=dashboard_data,
        filter_applied=time_filter,
        date_range=date_range_str,
        section=validated_section,
        date_range=date_range_str,
        hospital_name=hospital_name,
        hospital_address=hospital_address,
        hospital_phone=hospital_phone,
        hospital_email=hospital_email,
        hospital_logo=hospital_logo,
    )
    
    filename = (
        f"lab_dashboard_{time_filter}.pdf"
        if validated_section == "all"
        else f"lab_dashboard_{validated_section}_{time_filter}.pdf"
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "Access-Control-Expose-Headers": "Content-Disposition"
        }
    )
