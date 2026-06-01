from fastapi import APIRouter, Depends, Query, status

from app.core.dependencies import CurrentUser, DbSession
from app.core.exceptions import ForbiddenException
from app.core.constants import UserRole
from app.models.user_model import User
from app.schemas.common_schema import APIResponse, MessageResponse
from app.schemas.admin_management_schema import (
    AdminCreate,
    AdminUpdate,
    AdminStatusUpdate,
    AdminPasswordReset,
    AdminResponse
)
from app.services.admin_management_service import AdminManagementService
from app.utils.pagination import PaginatedResult
from app.api.v1.routes.super_admin_routes import require_super_admin

router = APIRouter()

@router.post("", response_model=APIResponse[AdminResponse], status_code=status.HTTP_201_CREATED)
async def create_admin(
    data: AdminCreate,
    db: DbSession,
    current_user: User = Depends(require_super_admin)
):
    admin = await AdminManagementService(db).create_admin(data, current_user)
    return APIResponse(message="Admin created successfully", data=admin)

@router.get("", response_model=APIResponse[PaginatedResult[AdminResponse]])
async def list_admins(
    db: DbSession,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None),
    hospital_id: int | None = Query(None),
    is_active: bool | None = Query(None),
    current_user: User = Depends(require_super_admin)
):
    result = await AdminManagementService(db).list_admins(
        page=page,
        size=size,
        search=search,
        hospital_id=hospital_id,
        is_active=is_active
    )
    return APIResponse(message="Admins listed successfully", data=result)

@router.get("/{admin_id}", response_model=APIResponse[AdminResponse])
async def get_admin(
    admin_id: int,
    db: DbSession,
    current_user: User = Depends(require_super_admin)
):
    admin = await AdminManagementService(db).get_admin(admin_id)
    return APIResponse(message="Admin retrieved successfully", data=admin)

@router.put("/{admin_id}", response_model=APIResponse[AdminResponse])
async def update_admin(
    admin_id: int,
    data: AdminUpdate,
    db: DbSession,
    current_user: User = Depends(require_super_admin)
):
    admin = await AdminManagementService(db).update_admin(admin_id, data, current_user)
    return APIResponse(message="Admin updated successfully", data=admin)

@router.delete("/{admin_id}", response_model=APIResponse[MessageResponse])
async def delete_admin(
    admin_id: int,
    db: DbSession,
    current_user: User = Depends(require_super_admin)
):
    await AdminManagementService(db).delete_admin(admin_id, current_user)
    return APIResponse(
        message="Admin deleted (deactivated) successfully",
        data=MessageResponse(message="Admin profile deactivated")
    )

@router.patch("/{admin_id}/status", response_model=APIResponse[AdminResponse])
async def update_status(
    admin_id: int,
    data: AdminStatusUpdate,
    db: DbSession,
    current_user: User = Depends(require_super_admin)
):
    admin = await AdminManagementService(db).update_status(admin_id, data.is_active, current_user)
    return APIResponse(message="Admin status updated successfully", data=admin)

@router.post("/{admin_id}/reset-password", response_model=APIResponse[MessageResponse])
async def reset_password(
    admin_id: int,
    data: AdminPasswordReset,
    db: DbSession,
    current_user: User = Depends(require_super_admin)
):
    await AdminManagementService(db).reset_password(admin_id, data.new_password, current_user)
    return APIResponse(
        message="Admin password reset successfully",
        data=MessageResponse(message="Password updated successfully")
    )
