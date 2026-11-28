from typing import Annotated, Callable

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import UserRole
from app.core.database import get_db
from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException, UnauthorizedException
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
        role_name = user.role.name if user.role and user.role.name else ""
        role_name_norm = role_name.lower().replace("_", " ").strip()
        allowed_roles_norm = [r.lower().replace("_", " ").strip() for r in allowed_roles]

        if role_name not in allowed_roles and role_name_norm not in allowed_roles_norm:
            if not allow_admin or (role_name not in UserRole.ADMIN_ROLES and role_name_norm not in ("super admin", "hospital admin")):
                raise ForbiddenException(f"Requires one of roles: {', '.join(allowed_roles)}")
        return user

    return role_checker


def require_permission(resource: str, action: str) -> Callable:
    async def permission_checker(db: DbSession, user: CurrentUser) -> User:
        role_name = user.role.name if user.role and user.role.name else ""
        role_name_norm = role_name.lower().replace("_", " ").strip()
        if role_name in UserRole.ADMIN_ROLES or role_name_norm in ("super admin", "hospital admin"):
            return user

        rbac_repo = RBACRepository(db)
        permissions = await rbac_repo.get_user_permissions(user.role_id)
        required = f"{resource}:{action}"
        if required not in permissions:
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


def _extract_user_attr(user: User, attr: str):
    """Safely read an attribute from User or mock object without triggering SQLAlchemy lazy loads."""
    user_dict = getattr(user, "__dict__", None)
    if user_dict is not None:
        if attr in user_dict:
            return user_dict[attr]
        if "_sa_instance_state" in user_dict:
            return None
    return getattr(user, attr, None)


def _extract_user_role_name(user: User) -> str:
    """Safely extract lowercased role name from User or mock object without triggering lazy loads."""
    role = _extract_user_attr(user, "role")
    if role and getattr(role, "name", None):
        return str(role.name).lower()
    role_name = _extract_user_attr(user, "role_name")
    return str(role_name).lower() if role_name else ""


def validate_tenant_body_match(body_hospital_id: int | None, validated_hospital_id: int) -> int:
    """
    Enforces that if a request body contains an explicit hospital_id,
    it must match the validated tenant context. Otherwise, raises HTTP 400 Bad Request.
    Returns the authoritative validated_hospital_id.
    """
    if body_hospital_id is not None and validated_hospital_id is not None and body_hospital_id != validated_hospital_id:
        raise BadRequestException(
            f"Conflicting hospital_id in request body ({body_hospital_id}) "
            f"does not match authorized hospital context ({validated_hospital_id})"
        )
    return validated_hospital_id


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

    role_name = _extract_user_role_name(user)

    if role_name in ("super admin", "super_admin"):
        if x_hospital_id is not None:
            return x_hospital_id
        active_hid = _extract_user_attr(user, "active_hospital_id")
        hid = _extract_user_attr(user, "hospital_id")
        return active_hid or hid

    # For non-super-admin users:
    user_hospital_id = _extract_user_attr(user, "hospital_id")
    if x_hospital_id is not None and (user_hospital_id is None or x_hospital_id != user_hospital_id):
        raise ForbiddenException("Access denied: Cannot access or specify another hospital's tenant context")

    return user_hospital_id


TenantHospitalId = Annotated[int | None, Depends(get_tenant_hospital_id)]
TenantWriteHospitalId = TenantHospitalId


def resolve_tenant_write_id(user: User | None, x_hospital_id: int | None = None) -> int:
    """
    Resolves tenant hospital_id specifically for tenant-bound write operations (create, update, delete).
    - Super Admin: MUST provide X-Hospital-Id (or active_hospital_id). If missing or None, raises HTTP 400 Bad Request.
    - Tenant Users: Strictly restricted to their assigned user.hospital_id. If missing, raises HTTP 403 Forbidden.
    - Invalid hospital ID (<= 0) raises HTTP 400 Bad Request.
    """
    if not user:
        raise BadRequestException("User context required for tenant write operation")

    if x_hospital_id is not None and x_hospital_id <= 0:
        raise BadRequestException("Invalid hospital ID provided in X-Hospital-Id header")

    role_name = _extract_user_role_name(user)
    if role_name in ("super admin", "super_admin"):
        tenant_id = x_hospital_id if x_hospital_id is not None else _extract_user_attr(user, "active_hospital_id")
        if tenant_id is None:
            raise BadRequestException(
                "Super Admin must explicitly specify a target hospital via X-Hospital-Id header for tenant write operations."
            )
        return tenant_id

    # For non-super-admin users:
    user_hospital_id = _extract_user_attr(user, "hospital_id")
    if not user_hospital_id:
        raise ForbiddenException("User is not assigned to any hospital tenant")

    if x_hospital_id is not None and x_hospital_id != user_hospital_id:
        raise ForbiddenException("Access denied: Cannot access or specify another hospital's tenant context")

    return user_hospital_id


async def get_tenant_write_hospital_id(
    db: DbSession,
    user: CurrentUser,
    x_hospital_id: Annotated[int | None, Header(alias="X-Hospital-Id", description="Tenant Hospital ID (Required for Super Admin writes)")] = None,
) -> int:
    """
    Async dependency that resolves and validates hospital_id for tenant write operations.
    Validates that the target hospital exists and is active in the database.
    """
    tenant_id = resolve_tenant_write_id(user, x_hospital_id)
    from app.models.hospital_model import Hospital
    hospital = await db.get(Hospital, tenant_id)
    if not hospital or not getattr(hospital, "is_active", True) or getattr(hospital, "is_deleted", False):
        raise NotFoundException(f"Hospital with ID {tenant_id} does not exist or is inactive.")
    return tenant_id


TenantWriteHospitalId = Annotated[int, Depends(get_tenant_write_hospital_id)]

