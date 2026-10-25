from typing import Annotated, Callable

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import UserRole
from app.core.database import get_db
from app.core.exceptions import BadRequestException, ForbiddenException, UnauthorizedException
from app.core.security import decode_token
from app.models.user_model import User
from app.repositories.auth_repository import AuthRepository
from app.repositories.rbac_repository import RBACRepository

bearer_scheme = HTTPBearer(
    scheme_name="JWT",
    description="Paste the access_token from POST /auth/login (data.access_token). Do not include the Bearer prefix.",
)

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    x_hospital_id: Annotated[int | None, Header(alias="X-Hospital-Id", description="Tenant Hospital ID (Super Admin override)")] = None,
) -> User:
    token = credentials.credentials
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise UnauthorizedException("Invalid token type")
        user_id = payload.get("sub")
        if not user_id:
            raise UnauthorizedException("Invalid token")
    except ValueError as exc:
        raise UnauthorizedException("Invalid token") from exc

    repo = AuthRepository(db)
    user = await repo.get_by_id(int(user_id))
    if not user or not user.is_active:
        raise UnauthorizedException("User not found or inactive")

    if user.last_logout_at:
        iat = payload.get("iat")
        if not iat and "exp" in payload:
            from app.core.config import settings
            iat = payload["exp"] - (settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)
        if iat:
            from datetime import datetime, timezone
            last_logout = user.last_logout_at
            if last_logout.tzinfo is not None:
                last_logout = last_logout.replace(tzinfo=None)
            iat_dt = datetime.fromtimestamp(iat, tz=timezone.utc).replace(tzinfo=None)
            if iat_dt < last_logout:
                raise UnauthorizedException("Token has been revoked by logout")

    role_name = user.role.name.lower() if user.role and user.role.name else ""
    if x_hospital_id is not None and role_name in ("super admin", "super_admin"):
        try:
            user.active_hospital_id = int(x_hospital_id)
        except (ValueError, TypeError):
            user.active_hospital_id = None
    else:
        user.active_hospital_id = None

    return user


async def get_current_active_user(user: Annotated[User, Depends(get_current_user)]) -> User:
    if not user.is_active:
        raise UnauthorizedException("Inactive user")
    return user


CurrentUser = Annotated[User, Depends(get_current_active_user)]


def require_roles(*allowed_roles: str, allow_admin: bool = True) -> Callable:
    async def role_checker(user: CurrentUser) -> User:
        role_name = user.role.name if user.role else None
        if role_name not in allowed_roles:
            if not allow_admin or role_name not in UserRole.ADMIN_ROLES:
                raise ForbiddenException(f"Requires one of roles: {', '.join(allowed_roles)}")
        return user

    return role_checker


def require_permission(resource: str, action: str) -> Callable:
    async def permission_checker(db: DbSession, user: CurrentUser) -> User:
        rbac_repo = RBACRepository(db)
        permissions = await rbac_repo.get_user_permissions(user.role_id)
        required = f"{resource}:{action}"
        if required not in permissions:
            role_name = user.role.name if user.role else ""
            if role_name not in UserRole.ADMIN_ROLES:
                raise ForbiddenException(f"Missing permission: {required}")
        return user

    return permission_checker


AdminUser = Annotated[User, Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.HOSPITAL_ADMIN))]
PatientUser = Annotated[User, Depends(require_roles(UserRole.PATIENT, allow_admin=False))]


async def get_tenant_hospital_id(
    user: CurrentUser,
    x_hospital_id: Annotated[int | None, Header(description="Tenant Hospital ID (Super Admin override)")] = None,
) -> int | None:
    """
    Resolves the active tenant (hospital_id) for the current request.
    - If user is Super Admin: can pass X-Hospital-Id header to scope to a tenant, or None for global view.
    - If user is Hospital Staff/Doctor/Admin: strictly restricted to their user.hospital_id.
    """
    return resolve_tenant_id(user, x_hospital_id)


def resolve_tenant_id(user: User | None, x_hospital_id: int | None = None) -> int | None:
    """
    Convenience function to extract tenant hospital_id from a User instance.
    Returns active_hospital_id or x_hospital_id override for Super Admin, or user.hospital_id for tenant users.
    Returns None for Super Admin without active_hospital_id/x_hospital_id override.
    Validates x_hospital_id and prevents regular users from specifying a different tenant.
    """
    if not user:
        return None

    if x_hospital_id is not None and x_hospital_id <= 0:
        raise BadRequestException("Invalid hospital ID provided in X-Hospital-Id header")

    role = getattr(user, "role", None)
    role_name = role.name.lower() if role and getattr(role, "name", None) else ""
    if role_name in ("super admin", "super_admin"):
        if x_hospital_id is not None:
            return x_hospital_id
        return getattr(user, "active_hospital_id", None) or getattr(user, "hospital_id", None)

    # For non-super-admin users:
    user_hospital_id = getattr(user, "hospital_id", None)
    if x_hospital_id is not None and (user_hospital_id is None or x_hospital_id != user_hospital_id):
        raise ForbiddenException("Access denied: Cannot access or specify another hospital's tenant context")

    return user_hospital_id


TenantHospitalId = Annotated[int | None, Depends(get_tenant_hospital_id)]

