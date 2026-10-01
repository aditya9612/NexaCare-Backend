from typing import Annotated, Callable

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import UserRole
from app.core.database import get_db
from app.core.exceptions import ForbiddenException, UnauthorizedException
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
            iat_dt = datetime.fromtimestamp(iat, tz=timezone.utc).replace(tzinfo=None)
            if iat_dt < user.last_logout_at:
                raise UnauthorizedException("Token has been revoked by logout")

    role_name = user.role.name if user.role else ""
    if x_hospital_id is not None and role_name == UserRole.SUPER_ADMIN:
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


def require_roles(*allowed_roles: str) -> Callable:
    async def role_checker(user: CurrentUser) -> User:
        role_name = user.role.name if user.role else None
        if role_name not in allowed_roles and role_name not in UserRole.ADMIN_ROLES:
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


async def get_tenant_hospital_id(
    user: CurrentUser,
    x_hospital_id: Annotated[int | None, Header(description="Tenant Hospital ID (Super Admin override)")] = None,
) -> int | None:
    """
    Resolves the active tenant (hospital_id) for the current request.
    - If user is Super Admin: can pass X-Hospital-Id header to scope to a tenant, or None for global view.
    - If user is Hospital Staff/Doctor/Admin: strictly restricted to their user.hospital_id.
    """
    role_name = user.role.name if user.role else ""
    if role_name == UserRole.SUPER_ADMIN:
        return x_hospital_id if x_hospital_id is not None else getattr(user, "active_hospital_id", user.hospital_id)
    return user.hospital_id


def resolve_tenant_id(user: User | None) -> int | None:
    """
    Convenience function to extract tenant hospital_id from a User instance.
    Returns active_hospital_id if explicitly set on Super Admin, or user.hospital_id for tenant users.
    Returns None for Super Admin without active_hospital_id override.
    """
    if not user:
        return None
    role_name = user.role.name if user.role else ""
    if role_name == UserRole.SUPER_ADMIN:
        return getattr(user, "active_hospital_id", None)
    return user.hospital_id


TenantHospitalId = Annotated[int | None, Depends(get_tenant_hospital_id)]

