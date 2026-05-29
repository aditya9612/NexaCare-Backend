from typing import List

from fastapi import APIRouter, Depends

from app.core.dependencies import AdminUser, CurrentUser, DbSession, require_permission
from app.models.user_model import User
from app.schemas.common_schema import APIResponse, MessageResponse
from app.schemas.rbac_schema import (
    PermissionCreate,
    PermissionResponse,
    RoleCreate,
    RolePermissionCreate,
    RolePermissionResponse,
    RoleResponse,
    RoleUpdate,
)
from app.services.rbac_service import RBACService

router = APIRouter()


@router.post("/roles", response_model=APIResponse[RoleResponse], status_code=201)
async def create_role(
    data: RoleCreate,
    db: DbSession,
    admin: AdminUser,
    _: User = Depends(require_permission("roles", "create")),
):
    role = await RBACService(db).create_role(data, admin.id)
    return APIResponse(message="Role created", data=role)


@router.get("/roles", response_model=APIResponse[List[RoleResponse]])
async def list_roles(db: DbSession, _: User = Depends(require_permission("roles", "read"))):
    roles = await RBACService(db).list_roles()
    return APIResponse(message="Roles retrieved", data=roles)


@router.get("/roles/{role_id}", response_model=APIResponse[RoleResponse])
async def get_role(
    role_id: int,
    db: DbSession,
    _: User = Depends(require_permission("roles", "read")),
):
    role = await RBACService(db).get_role(role_id)
    return APIResponse(message="Role retrieved", data=role)


@router.put("/roles/{role_id}", response_model=APIResponse[RoleResponse])
async def update_role(
    role_id: int,
    data: RoleUpdate,
    db: DbSession,
    admin: AdminUser,
    _: User = Depends(require_permission("roles", "update")),
):
    role = await RBACService(db).update_role(role_id, data, admin.id)
    return APIResponse(message="Role updated", data=role)


@router.delete("/roles/{role_id}", response_model=APIResponse[MessageResponse])
async def delete_role(
    role_id: int,
    db: DbSession,
    admin: AdminUser,
    _: User = Depends(require_permission("roles", "delete")),
):
    await RBACService(db).delete_role(role_id, admin.id)
    return APIResponse(message="Role deleted", data=MessageResponse(message="Deleted"))


@router.post("/permissions", response_model=APIResponse[PermissionResponse], status_code=201)
async def create_permission(
    data: PermissionCreate,
    db: DbSession,
    admin: AdminUser,
    _: User = Depends(require_permission("permissions", "create")),
):
    perm = await RBACService(db).create_permission(data, admin.id)
    return APIResponse(message="Permission created", data=perm)


@router.get("/permissions", response_model=APIResponse[List[PermissionResponse]])
async def list_permissions(
    db: DbSession,
    _: User = Depends(require_permission("permissions", "read")),
):
    perms = await RBACService(db).list_permissions()
    return APIResponse(message="Permissions retrieved", data=perms)


@router.post("/role-permissions", response_model=APIResponse[RolePermissionResponse], status_code=201)
async def assign_role_permission(
    data: RolePermissionCreate,
    db: DbSession,
    admin: AdminUser,
    _: User = Depends(require_permission("permissions", "assign")),
):
    rp = await RBACService(db).assign_permission(data, admin.id)
    return APIResponse(message="Permission assigned", data=rp)


@router.get("/role-permissions", response_model=APIResponse[List[RolePermissionResponse]])
async def list_role_permissions(
    db: DbSession,
    role_id: int | None = None,
    _: User = Depends(require_permission("permissions", "read")),
):
    items = await RBACService(db).list_role_permissions(role_id)
    return APIResponse(message="Role permissions retrieved", data=items)


@router.post("/roles/assign-permissions", response_model=APIResponse[RolePermissionResponse], status_code=201)
async def assign_role_permission_path(
    data: RolePermissionCreate,
    db: DbSession,
    admin: AdminUser,
    _: User = Depends(require_permission("permissions", "assign")),
):
    rp = await RBACService(db).assign_permission(data, admin.id)
    return APIResponse(message="Permission assigned to role successfully", data=rp)


@router.get("/roles/{role_id}/permissions", response_model=APIResponse[List[RolePermissionResponse]])
async def get_role_permissions(
    role_id: int,
    db: DbSession,
    _: User = Depends(require_permission("permissions", "read")),
):
    items = await RBACService(db).list_role_permissions(role_id)
    return APIResponse(message="Role permissions retrieved successfully", data=items)
