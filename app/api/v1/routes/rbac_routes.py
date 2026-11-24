import hmac
from typing import List

from fastapi import APIRouter, Body, Depends, Header, Request, status

from app.core.config import settings
from app.core.constants import UserRole
from app.core.dependencies import (
    AdminUser,
    CurrentUser,
    DbSession,
    bearer_scheme,
    require_permission,
    require_role,
)
from app.core.exceptions import BadRequestException, ForbiddenException
from app.core.security import decode_token
from app.repositories.audit_repository import AuditRepository
from app.models.user_model import User
from app.schemas.common_schema import APIResponse, MessageResponse
from app.schemas.rbac_schema import (
    PermissionCreate,
    PermissionResponse,
    PermissionUpdate,
    RoleCreate,
    RolePermissionCreate,
    RolePermissionOverrideRequest,
    RolePermissionOverrideResponse,
    RolePermissionResponse,
    RoleResponse,
    RoleUpdate,
    RBACSeedDefaultsRequest,
    RBACSeedDefaultsResponse,
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
    hospital_id = admin.hospital_id if admin.role and admin.role.name == UserRole.HOSPITAL_ADMIN else data.hospital_id
    role = await RBACService(db).create_role(data, admin.id, hospital_id=hospital_id)
    return APIResponse(message="Role created", data=role)


@router.get("/roles", response_model=APIResponse[List[RoleResponse]])
async def list_roles(
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("roles", "read")),
):
    hospital_id = current_user.hospital_id if current_user.role and current_user.role.name != UserRole.SUPER_ADMIN else None
    roles = await RBACService(db).list_roles(hospital_id=hospital_id)
    return APIResponse(message="Roles retrieved", data=roles)


@router.get("/roles/{role_id}", response_model=APIResponse[RoleResponse])
async def get_role(
    role_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("roles", "read")),
):
    hospital_id = current_user.hospital_id if current_user.role and current_user.role.name != UserRole.SUPER_ADMIN else None
    role = await RBACService(db).get_role(role_id, hospital_id=hospital_id)
    return APIResponse(message="Role retrieved", data=role)


@router.put("/roles/{role_id}", response_model=APIResponse[RoleResponse])
async def update_role(
    role_id: int,
    data: RoleUpdate,
    db: DbSession,
    admin: AdminUser,
    _: User = Depends(require_permission("roles", "update")),
):
    hospital_id = admin.hospital_id if admin.role and admin.role.name == UserRole.HOSPITAL_ADMIN else None
    role = await RBACService(db).update_role(role_id, data, admin.id, hospital_id=hospital_id)
    return APIResponse(message="Role updated", data=role)


@router.delete("/roles/{role_id}", response_model=APIResponse[MessageResponse])
async def delete_role(
    role_id: int,
    db: DbSession,
    admin: AdminUser,
    _: User = Depends(require_permission("roles", "delete")),
):
    hospital_id = admin.hospital_id if admin.role and admin.role.name == UserRole.HOSPITAL_ADMIN else None
    await RBACService(db).delete_role(role_id, admin.id, hospital_id=hospital_id)
    return APIResponse(message="Role deleted", data=MessageResponse(message="Deleted"))


@router.post("/roles/{role_id}/overrides", response_model=APIResponse[RolePermissionOverrideResponse], status_code=201)
async def set_role_override(
    role_id: int,
    data: RolePermissionOverrideRequest,
    db: DbSession,
    admin: AdminUser,
    _: User = Depends(require_permission("roles", "update")),
):
    hospital_id = admin.hospital_id if admin.role and admin.role.name == UserRole.HOSPITAL_ADMIN else admin.hospital_id
    if not hospital_id:
        # If Super Admin, retrieve the role's hospital_id
        target_role = await RBACService(db).get_role(role_id)
        hospital_id = target_role.hospital_id
    if not hospital_id:
        raise BadRequestException("Overrides can only be configured for hospital-specific custom roles.")
    override = await RBACService(db).set_role_override(
        hospital_id=hospital_id,
        role_id=role_id,
        permission_id=data.permission_id,
        is_granted=data.is_granted,
        user_id=admin.id,
    )
    return APIResponse(message="Role override saved", data=override)


@router.get("/roles/{role_id}/overrides", response_model=APIResponse[List[RolePermissionOverrideResponse]])
async def list_role_overrides(
    role_id: int,
    db: DbSession,
    admin: AdminUser,
    _: User = Depends(require_permission("roles", "read")),
):
    hospital_id = admin.hospital_id if admin.role and admin.role.name == UserRole.HOSPITAL_ADMIN else None
    if not hospital_id:
        target_role = await RBACService(db).get_role(role_id)
        hospital_id = target_role.hospital_id
    if not hospital_id:
        return APIResponse(message="Overrides retrieved", data=[])
    overrides = await RBACService(db).list_role_overrides(hospital_id=hospital_id, role_id=role_id)
    return APIResponse(message="Overrides retrieved", data=overrides)



@router.post("/permissions", response_model=APIResponse[PermissionResponse], status_code=201)
async def create_permission(
    data: PermissionCreate,
    db: DbSession,
    admin: AdminUser,
    _: User = Depends(require_permission("permissions", "create")),
):
    if admin.role and admin.role.name != UserRole.SUPER_ADMIN:
        raise ForbiddenException("Only Super Admin can manage global permissions.")
    perm = await RBACService(db).create_permission(data, admin.id)
    return APIResponse(message="Permission created", data=perm)


@router.get("/permissions", response_model=APIResponse[List[PermissionResponse]])
async def list_permissions(
    db: DbSession,
    _: User = Depends(require_permission("permissions", "read")),
):
    perms = await RBACService(db).list_permissions()
    return APIResponse(message="Permissions retrieved", data=perms)


@router.get("/permissions/{permission_id}", response_model=APIResponse[PermissionResponse])
async def get_permission(
    permission_id: int,
    db: DbSession,
    _: User = Depends(require_permission("permissions", "read")),
):
    perm = await RBACService(db).get_permission(permission_id)
    return APIResponse(message="Permission retrieved", data=perm)


@router.put("/permissions/{permission_id}", response_model=APIResponse[PermissionResponse])
async def update_permission(
    permission_id: int,
    data: PermissionUpdate,
    db: DbSession,
    admin: AdminUser,
    _: User = Depends(require_permission("permissions", "update")),
):
    if admin.role and admin.role.name != UserRole.SUPER_ADMIN:
        raise ForbiddenException("Only Super Admin can manage global permissions.")
    perm = await RBACService(db).update_permission(permission_id, data, admin.id)
    return APIResponse(message="Permission updated", data=perm)


@router.delete("/permissions/{permission_id}", response_model=APIResponse[MessageResponse])
async def delete_permission(
    permission_id: int,
    db: DbSession,
    admin: AdminUser,
    _: User = Depends(require_permission("permissions", "delete")),
):
    if admin.role and admin.role.name != UserRole.SUPER_ADMIN:
        raise ForbiddenException("Only Super Admin can manage global permissions.")
    await RBACService(db).delete_permission(permission_id, admin.id)
    return APIResponse(message="Permission deleted", data=MessageResponse(message="Deleted"))


@router.post("/role-permissions", response_model=APIResponse[RolePermissionResponse], status_code=201)
async def assign_role_permission(
    data: RolePermissionCreate,
    db: DbSession,
    admin: AdminUser,
    _: User = Depends(require_permission("permissions", "assign")),
):
    hospital_id = admin.hospital_id if admin.role and admin.role.name == UserRole.HOSPITAL_ADMIN else None
    rp = await RBACService(db).assign_permission(data, admin.id, hospital_id=hospital_id)
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
    hospital_id = admin.hospital_id if admin.role and admin.role.name == UserRole.HOSPITAL_ADMIN else None
    rp = await RBACService(db).assign_permission(data, admin.id, hospital_id=hospital_id)
    return APIResponse(message="Permission assigned to role successfully", data=rp)


@router.get("/roles/{role_id}/permissions", response_model=APIResponse[List[RolePermissionResponse]])
async def get_role_permissions(
    role_id: int,
    db: DbSession,
    _: User = Depends(require_permission("permissions", "read")),
):
    items = await RBACService(db).list_role_permissions(role_id)
    return APIResponse(message="Role permissions retrieved successfully", data=items)


@router.post(
    "/rbac/seed-defaults",
    response_model=APIResponse[RBACSeedDefaultsResponse],
    status_code=status.HTTP_200_OK,
    summary="One-Click Default RBAC & Roles Seeder (Super Admin Only)",
    description=(
        "Initializes all default roles, module permissions, complete role-permission matrices, "
        "and bootstrap Super Admin. Requires Super Admin authentication in all environments."
    ),
    dependencies=[Depends(bearer_scheme)],
)
@router.post(
    "/seed-defaults",
    response_model=APIResponse[RBACSeedDefaultsResponse],
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
    dependencies=[Depends(bearer_scheme)],
)
async def seed_default_rbac(
    db: DbSession,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN)),
    data: RBACSeedDefaultsRequest = Body(default_factory=RBACSeedDefaultsRequest),
):
    # 1. Feature flag guard (fail-closed by default)
    if not getattr(settings, "ENABLE_DEV_RBAC_SEED", False):
        raise ForbiddenException("The RBAC seed-defaults endpoint is disabled.")

    # 2. Execute unified seeding service
    result = await RBACService(db).seed_system_defaults(
        include_test_users=data.include_test_users,
        sync_super_admin=data.sync_super_admin,
    )

    # 3. Structured audit logging
    await AuditRepository(db).create(
        action="seed_rbac_defaults",
        resource="rbac",
        user_id=current_user.id,
        details=f"roles_created={result.roles_created}, perms_created={result.permissions_created}",
    )

    return APIResponse(
        message="Default RBAC configuration initialized successfully.",
        data=result,
    )

