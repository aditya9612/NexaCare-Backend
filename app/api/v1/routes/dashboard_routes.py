from datetime import date
from fastapi import APIRouter, Depends

from app.core.constants import UserRole
from app.core.dependencies import CurrentUser, DbSession, require_permission, require_roles
from app.models.user_model import User
from app.schemas.common_schema import APIResponse
from app.schemas.dashboard_schema import (
    AdminDashboardResponse,
    DoctorDashboardResponse,
    PatientDashboardResponse,
    ReceptionDashboardResponse,
)
from app.services.dashboard_service import DashboardService

router = APIRouter()


@router.get("/admin", response_model=APIResponse[AdminDashboardResponse])
async def admin_dashboard(
    db: DbSession,
    _: User = Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.HOSPITAL_ADMIN)),
    __: User = Depends(require_permission("dashboard", "read")),
):
    data = await DashboardService(db).admin_dashboard()
    return APIResponse(message="Admin dashboard", data=data)


@router.get("/doctor", response_model=APIResponse[DoctorDashboardResponse])
async def doctor_dashboard(
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_roles(UserRole.DOCTOR)),
    __: User = Depends(require_permission("dashboard", "read")),
):
    data = await DashboardService(db).doctor_dashboard(current_user)
    return APIResponse(message="Doctor dashboard", data=data)


@router.get("/patient", response_model=APIResponse[PatientDashboardResponse])
async def patient_dashboard(
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_roles(UserRole.PATIENT)),
    __: User = Depends(require_permission("dashboard", "read")),
):
    data = await DashboardService(db).patient_dashboard(current_user)
    return APIResponse(message="Patient dashboard", data=data)


@router.get("/reception", response_model=APIResponse[ReceptionDashboardResponse])
async def reception_dashboard(
    db: DbSession,
    date: date | None = None,
    _: User = Depends(require_roles(UserRole.RECEPTIONIST)),
    __: User = Depends(require_permission("dashboard", "read")),
):
    data = await DashboardService(db).reception_dashboard(date)
    return APIResponse(message="Receptionist dashboard stats retrieved successfully", data=data)
