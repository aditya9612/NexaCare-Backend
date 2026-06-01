from fastapi import APIRouter, Depends, status
from app.core.dependencies import CurrentUser, DbSession
from app.core.exceptions import ForbiddenException
from app.core.constants import UserRole
from app.schemas.common_schema import APIResponse, MessageResponse
from app.schemas.hospital_schema import HospitalCreate, HospitalUpdate, HospitalResponse, HospitalStatsResponse
from app.schemas.user_schema import UserCreate, UserUpdate, UserResponse
from app.services.hospital_service import HospitalService
from app.models.user_model import User
from app.schemas.super_admin_schema import SuperAdminDashboardResponse, SuperAdminAnalyticsResponse
from app.services.super_admin_service import SuperAdminService

router = APIRouter()

async def require_super_admin(user: CurrentUser) -> User:
    if not user.role or user.role.name != UserRole.SUPER_ADMIN:
        raise ForbiddenException("Requires Super Admin role")
    return user

@router.post("/hospitals", response_model=APIResponse[HospitalResponse], status_code=201)
async def create_hospital(
    data: HospitalCreate,
    db: DbSession,
    current_user: User = Depends(require_super_admin)
):
    hospital = await HospitalService(db).create_hospital(data, current_user.id)
    return APIResponse(message="Hospital created successfully", data=hospital)

@router.get("/hospitals", response_model=APIResponse[list[HospitalResponse]])
async def list_hospitals(
    db: DbSession,
    current_user: User = Depends(require_super_admin)
):
    hospitals = await HospitalService(db).list_hospitals()
    return APIResponse(message="Hospitals retrieved successfully", data=hospitals)

@router.get("/hospitals/{id}", response_model=APIResponse[HospitalResponse])
async def get_hospital(
    id: int,
    db: DbSession,
    current_user: User = Depends(require_super_admin)
):
    hospital = await HospitalService(db).get_hospital(id)
    return APIResponse(message="Hospital retrieved successfully", data=hospital)

@router.put("/hospitals/{id}", response_model=APIResponse[HospitalResponse])
async def update_hospital(
    id: int,
    data: HospitalUpdate,
    db: DbSession,
    current_user: User = Depends(require_super_admin)
):
    hospital = await HospitalService(db).update_hospital(id, data, current_user.id)
    return APIResponse(message="Hospital updated successfully", data=hospital)

@router.delete("/hospitals/{id}", response_model=APIResponse[MessageResponse])
async def deactivate_hospital(
    id: int,
    db: DbSession,
    current_user: User = Depends(require_super_admin)
):
    await HospitalService(db).delete_hospital(id, current_user.id)
    return APIResponse(message="Hospital deactivated successfully", data=MessageResponse(message="Hospital deactivated"))

@router.get("/hospitals/{id}/stats", response_model=APIResponse[HospitalStatsResponse])
async def get_hospital_stats(
    id: int,
    db: DbSession,
    current_user: User = Depends(require_super_admin)
):
    stats = await HospitalService(db).get_hospital_stats(id)
    return APIResponse(message="Hospital stats retrieved successfully", data=stats)

# Hospital Admin Management
@router.post("/hospital-admins", response_model=APIResponse[UserResponse], status_code=201)
async def create_hospital_admin(
    data: UserCreate,
    db: DbSession,
    current_user: User = Depends(require_super_admin)
):
    admin = await HospitalService(db).create_hospital_admin(data, current_user.id)
    return APIResponse(message="Hospital Admin created successfully", data=admin)

@router.get("/hospital-admins", response_model=APIResponse[list[UserResponse]])
async def list_hospital_admins(
    db: DbSession,
    current_user: User = Depends(require_super_admin)
):
    admins = await HospitalService(db).list_hospital_admins()
    return APIResponse(message="Hospital Admins retrieved successfully", data=admins)

@router.put("/hospital-admins/{id}", response_model=APIResponse[UserResponse])
async def update_hospital_admin(
    id: int,
    data: UserUpdate,
    db: DbSession,
    current_user: User = Depends(require_super_admin)
):
    admin = await HospitalService(db).update_hospital_admin(id, data, current_user.id)
    return APIResponse(message="Hospital Admin updated successfully", data=admin)

@router.delete("/hospital-admins/{id}", response_model=APIResponse[MessageResponse])
async def deactivate_hospital_admin(
    id: int,
    db: DbSession,
    current_user: User = Depends(require_super_admin)
):
    await HospitalService(db).delete_hospital_admin(id, current_user.id)
    return APIResponse(message="Hospital Admin deactivated successfully", data=MessageResponse(message="Hospital Admin deactivated"))

@router.get("/dashboard", response_model=APIResponse[SuperAdminDashboardResponse])
async def get_super_admin_dashboard(
    db: DbSession,
    current_user: User = Depends(require_super_admin)
):
    stats = await SuperAdminService(db).get_dashboard_stats()
    return APIResponse(message="Super Admin dashboard stats retrieved successfully", data=stats)

@router.get("/dashboard/analytics", response_model=APIResponse[SuperAdminAnalyticsResponse])
async def get_super_admin_analytics(
    db: DbSession,
    current_user: User = Depends(require_super_admin)
):
    analytics = await SuperAdminService(db).get_analytics()
    return APIResponse(message="Super Admin analytics retrieved successfully", data=analytics)
