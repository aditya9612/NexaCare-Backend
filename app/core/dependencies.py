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

TENANT_WRITE_ACTIONS = frozenset({
    "create", "update", "delete", "approve", "assign", "write",
    "upload", "import", "cancel", "restore", "transfer", "share",
    "release", "allocate", "dispense",
})

CANONICAL_RESOURCE_MAP = {
    "expense": "expenses",
    "expenses": "expenses",
    "vendor": "vendors",
    "vendors": "vendors",
    "doctor": "doctors",
    "doctors": "doctors",
    "nurse": "nurses",
    "nurses": "nurses",
    "staff": "staff",
    "department": "departments",
    "departments": "departments",
    "patient": "patients",
    "patients": "patients",
    "patient_document": "patient_documents",
    "patient_documents": "patient_documents",
    "vital": "vitals",
    "vitals": "vitals",
    "clinical_record": "clinical_records",
    "clinical_records": "clinical_records",
    "appointment": "appointments",
    "appointments": "appointments",
    "discharge": "discharges",
    "discharges": "discharges",
    "billing": "billing",
    "invoice": "invoices",
    "invoices": "invoices",
    "payment": "payments",
    "payments": "payments",
    "tariff": "tariffs",
    "tariffs": "tariffs",
    "room_tariff": "tariffs",
    "room_tariffs": "tariffs",
    "pharmacy": "pharmacy",
    "prescription": "prescriptions",
    "prescriptions": "prescriptions",
    "medicine": "medicines",
    "medicines": "medicines",
    "lab": "lab",
    "lab_order": "lab_orders",
    "lab_orders": "lab_orders",
    "lab_report": "lab_reports",
    "lab_reports": "lab_reports",
    "inventory": "inventory",
    "bed": "beds",
    "beds": "beds",
    "bed_allocation": "bed_allocation",
    "floor": "beds",
    "floors": "beds",
    "room": "beds",
    "rooms": "beds",
    "icu": "icu",
    "icu_telemetry": "icu_telemetry",
    "voice_reminder": "voice_reminder",
    "whatsapp": "whatsapp",
    "hospital_voice": "voice_reminder",
}

TENANT_BOUND_RESOURCES = frozenset({
    "patients", "patient_documents", "vitals",
    "clinical_records", "appointments", "discharges",
    "billing", "invoices", "payments", "tariffs",
    "pharmacy", "prescriptions", "medicines",
    "lab", "lab_orders", "lab_reports",
    "inventory", "vendors", "vendor", "expenses", "expense",
    "beds", "bed_allocation", "icu", "icu_telemetry",
    "doctors", "doctor", "nurses", "nurse", "staff", "departments", "department",
    "voice_reminder", "whatsapp",
})


def normalize_resource(resource: str) -> str:
    r = resource.lower().strip()
    return CANONICAL_RESOURCE_MAP.get(r, r)


def validate_tenant_body_match(body_hospital_id: int | None, validated_hospital_id: int) -> int:
    """
    Enforces that if a request body contains an explicit hospital_id,
    it must match the validated tenant context. Otherwise, raises HTTP 400 Bad Request.
    Returns the authoritative validated_hospital_id.
    """
    if body_hospital_id is not None and body_hospital_id != validated_hospital_id:
        raise BadRequestException(
            f"Conflicting hospital_id in request body ({body_hospital_id}) "
            f"does not match authorized hospital context ({validated_hospital_id})"
        )
    return validated_hospital_id


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
        base_role = getattr(user.role, "base_role_type", None) or ""
        role_name_norm = role_name.lower().replace("_", " ").strip()
        base_role_norm = base_role.lower().replace("_", " ").strip()
        allowed_roles_norm = [r.lower().replace("_", " ").strip() for r in allowed_roles]

        matches_role = (
            role_name in allowed_roles
            or role_name_norm in allowed_roles_norm
            or base_role in allowed_roles
            or base_role_norm in allowed_roles_norm
        )

        if not matches_role:
            is_admin = (role_name in UserRole.ADMIN_ROLES or role_name_norm in ("super admin", "hospital admin"))
            if not allow_admin or not is_admin:
                raise ForbiddenException(f"Requires one of roles: {', '.join(allowed_roles)}")
        return user

    return role_checker


def require_role(role: str, allow_admin: bool = False) -> Callable:
    """
    Enforces that the user has the specified exact role (or base role type).
    By default allow_admin=False so Hospital Admin cannot bypass Super Admin requirements.
    """
    return require_roles(role, allow_admin=allow_admin)


def require_module(module_code: str) -> Callable:
    async def module_checker(
        db: DbSession,
        user: CurrentUser,
        x_hospital_id: Annotated[int | None, Header(alias="X-Hospital-Id")] = None,
    ) -> bool:
        role_name = user.role.name if user.role and user.role.name else ""
        role_name_norm = role_name.lower().replace("_", " ").strip()

        # Platform Super Admin operating globally bypasses module check
        tenant_id = resolve_tenant_id(user, x_hospital_id)
        if tenant_id is None and role_name_norm in ("super admin",):
            return True

        from app.services.module_service import ModuleService
        module_service = ModuleService(db)
        is_active = await module_service.is_module_active(tenant_id, module_code)
        if not is_active:
            raise ForbiddenException(
                f"Module '{module_code}' is not activated for this hospital.",
            )
        return True

    return module_checker


def require_permission(resource: str, action: str) -> Callable:
    async def permission_checker(
        db: DbSession,
        user: CurrentUser,
        x_hospital_id: Annotated[int | None, Header(alias="X-Hospital-Id")] = None,
    ) -> User:
        role_name = user.role.name if user.role and user.role.name else ""
        role_name_norm = role_name.lower().replace("_", " ").strip()
        tenant_id = resolve_tenant_id(user, x_hospital_id)

        # 1. Super Admin universal bypass (scoped to tenant if X-Hospital-Id passed)
        if role_name_norm in ("super admin",) or role_name == UserRole.SUPER_ADMIN:
            # SEC-03: Tenant-bound write operations MUST specify a target hospital tenant
            norm_res = normalize_resource(resource)
            act_norm = action.lower().strip()
            if act_norm in TENANT_WRITE_ACTIONS and (norm_res in TENANT_BOUND_RESOURCES or resource.lower().strip() in TENANT_BOUND_RESOURCES):
                if tenant_id is None:
                    raise BadRequestException(
                        f"Super Admin must explicitly specify a target hospital via X-Hospital-Id header for {action} on {resource}."
                    )
            return user

        # 2. Module Entitlement Check for the resource
        from app.services.module_service import ModuleService
        governing_module = ModuleService.get_module_for_resource(resource)
        if governing_module and tenant_id:
            module_service = ModuleService(db)
            if not await module_service.is_module_active(tenant_id, governing_module):
                raise ForbiddenException(
                    f"Module '{governing_module}' is not activated for this hospital.",
                )

        # 3. Hospital Admin bypass for administrative/billing/reports, but NOT clinical write actions
        CLINICAL_RESTRICTED_RESOURCES = {"clinical_records", "prescriptions", "discharges"}
        is_hosp_admin = (role_name == UserRole.HOSPITAL_ADMIN or role_name_norm == "hospital admin")
        if is_hosp_admin:
            if resource not in CLINICAL_RESTRICTED_RESOURCES or action == "read":
                return user

        # 4. Check effective permissions (role permissions + tenant delta overrides)
        rbac_repo = RBACRepository(db)
        effective_permissions = await rbac_repo.get_user_effective_permissions(
            role_id=user.role_id,
            hospital_id=tenant_id,
        )
        required = f"{resource}:{action}"
        if required not in effective_permissions:
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
        return getattr(user, "active_hospital_id", None)

    # For non-super-admin users:
    user_hospital_id = getattr(user, "hospital_id", None)
    if x_hospital_id is not None and (user_hospital_id is None or x_hospital_id != user_hospital_id):
        raise ForbiddenException("Access denied: Cannot access or specify another hospital's tenant context")

    return user_hospital_id


TenantHospitalId = Annotated[int | None, Depends(get_tenant_hospital_id)]


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

    role = getattr(user, "role", None)
    role_name = role.name.lower() if role and getattr(role, "name", None) else ""
    if role_name in ("super admin", "super_admin"):
        tenant_id = x_hospital_id or getattr(user, "active_hospital_id", None)
        if tenant_id is None:
            raise BadRequestException(
                "Super Admin must explicitly specify a target hospital via X-Hospital-Id header for tenant write operations."
            )
        return tenant_id

    # For non-super-admin users:
    user_hospital_id = getattr(user, "hospital_id", None)
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
    if not hospital or not getattr(hospital, "is_active", True):
        raise NotFoundException(f"Hospital with ID {tenant_id} does not exist or is inactive.")
    return tenant_id


TenantWriteHospitalId = Annotated[int, Depends(get_tenant_write_hospital_id)]

