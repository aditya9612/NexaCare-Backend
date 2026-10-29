import hmac
from typing import List

from fastapi import APIRouter, Body, Depends, Header, Request, status

from app.core.config import settings
from app.core.dependencies import AdminUser, CurrentUser, DbSession, require_permission
from app.core.exceptions import ForbiddenException
from app.core.security import decode_token
from app.models.user_model import User
from app.schemas.common_schema import APIResponse, MessageResponse
from app.schemas.rbac_schema import (
    PermissionCreate,
    PermissionResponse,
    PermissionUpdate,
    RoleCreate,
    RolePermissionCreate,
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
    perm = await RBACService(db).update_permission(permission_id, data, admin.id)
    return APIResponse(message="Permission updated", data=perm)


@router.delete("/permissions/{permission_id}", response_model=APIResponse[MessageResponse])
async def delete_permission(
    permission_id: int,
    db: DbSession,
    admin: AdminUser,
    _: User = Depends(require_permission("permissions", "delete")),
):
    await RBACService(db).delete_permission(permission_id, admin.id)
    return APIResponse(message="Permission deleted", data=MessageResponse(message="Deleted"))


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


@router.post(
    "/rbac/seed-defaults",
    response_model=APIResponse[RBACSeedDefaultsResponse],
    status_code=status.HTTP_200_OK,
    summary="One-Click Default RBAC & Roles Seeder",
    description=(
        "Initializes all default roles, module permissions, complete role-permission matrices, "
        "and bootstrap Super Admin in one click after database reset. Accessible unauthenticated "
        "in development/testing environments, or via Super Admin auth / X-Seed-Key in production."
    ),
)
@router.post(
    "/seed-defaults",
    response_model=APIResponse[RBACSeedDefaultsResponse],
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
async def seed_default_rbac(
    request: Request,
    db: DbSession,
    data: RBACSeedDefaultsRequest = Body(default_factory=RBACSeedDefaultsRequest),
    x_seed_key: str | None = Header(None, alias="X-Seed-Key"),
):
    # 1. Feature flag guard
    if not getattr(settings, "ENABLE_DEV_RBAC_SEED", True):
        raise ForbiddenException("The RBAC seed-defaults endpoint is disabled.")

    # 2. Environment & Authorization check
    is_dev_or_test = settings.APP_ENV.lower() not in ("production", "prod")

    if not is_dev_or_test:
        authenticated = False
        # Secret key check (timing-safe)
        if x_seed_key and hmac.compare_digest(x_seed_key, settings.SECRET_KEY):
            authenticated = True
        else:
            # Bearer token check for Super Admin
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header.replace("Bearer ", "").strip()
                try:
                    payload = decode_token(token)
                    role_name = (payload.get("role") or "").lower().replace("_", " ").strip()
                    if role_name == "super admin":
                        authenticated = True
                except Exception:
                    pass

        if not authenticated:
            raise ForbiddenException(
                "Access denied: In production, seed-defaults requires a Super Admin token or valid X-Seed-Key header."
            )

    # 3. Execute unified seeding service
    result = await RBACService(db).seed_system_defaults(
        include_test_users=data.include_test_users,
        sync_super_admin=data.sync_super_admin,
    )

    return APIResponse(
        message="Default RBAC configuration initialized successfully.",
        data=result,
    )

