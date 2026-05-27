from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=False,  # aiomysql async ping() incompatible with SQLAlchemy pre-ping
    pool_recycle=3600,
)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    from app.models import (  # noqa: F401
        analytics_model,
        appointment_model,
        audit_log_model,
        billing_model,
        chat_model,
        department_model,
        doctor_model,
        inventory_model,
        lab_model,
        patient_model,
        permission_model,
        pharmacy_model,
        refresh_token_model,
        role_model,
        user_model,
        voice_model,
        whatsapp_model,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        await _seed_roles_and_permissions(session)
        await _seed_phase3_permissions(session)
        await _seed_patient_permissions(session)
        await _seed_default_super_admin(session)
        await session.commit()


async def _seed_roles_and_permissions(session: AsyncSession) -> None:
    from app.core.constants import PermissionAction, UserRole
    from app.models.permission_model import Permission
    from app.models.role_model import Role, RolePermission

    role_names = list(UserRole.ALL)
    result = await session.execute(select(Role).limit(1))
    if result.scalar_one_or_none():
        return

    roles = {name: Role(name=name, description=f"{name} role") for name in role_names}
    session.add_all(roles.values())
    await session.flush()

    resources = [
        "users", "roles", "permissions", "patients", "doctors", "appointments", "dashboard",
        "billing", "pharmacy", "lab", "inventory",
        "ai_chat", "voice_reminder", "whatsapp", "analytics", "departments",
    ]
    actions = [
        PermissionAction.CREATE,
        PermissionAction.READ,
        PermissionAction.UPDATE,
        PermissionAction.DELETE,
        PermissionAction.EXPORT,
        PermissionAction.APPROVE,
        PermissionAction.ASSIGN,
    ]

    permissions: list[Permission] = []
    for resource in resources:
        for action in actions:
            permissions.append(
                Permission(
                    name=f"{resource}:{action}",
                    resource=resource,
                    action=action,
                    description=f"{action} {resource}",
                )
            )
    session.add_all(permissions)
    await session.flush()

    super_admin = roles[UserRole.SUPER_ADMIN]
    hospital_admin = roles[UserRole.HOSPITAL_ADMIN]
    for perm in permissions:
        session.add(RolePermission(role_id=super_admin.id, permission_id=perm.id))
    admin_resources = {
        "users", "roles", "permissions", "patients", "doctors", "appointments", "dashboard",
        "billing", "pharmacy", "lab", "inventory",
        "ai_chat", "voice_reminder", "whatsapp", "analytics", "departments",
    }
    for perm in permissions:
        if perm.resource in admin_resources:
            session.add(RolePermission(role_id=hospital_admin.id, permission_id=perm.id))


async def _seed_phase3_permissions(session: AsyncSession) -> None:
    """Add Phase 3 permissions to existing deployments."""
    from app.core.constants import PermissionAction, UserRole
    from app.models.permission_model import Permission
    from app.models.role_model import Role, RolePermission

    phase3_resources = ["ai_chat", "voice_reminder", "whatsapp", "analytics"]
    actions = [
        PermissionAction.CREATE,
        PermissionAction.READ,
        PermissionAction.UPDATE,
        PermissionAction.DELETE,
        PermissionAction.EXPORT,
        PermissionAction.APPROVE,
        PermissionAction.ASSIGN,
    ]

    result = await session.execute(select(Role).where(Role.name == UserRole.SUPER_ADMIN))
    super_admin = result.scalar_one_or_none()
    if not super_admin:
        return

    result = await session.execute(select(Role).where(Role.name == UserRole.HOSPITAL_ADMIN))
    hospital_admin = result.scalar_one_or_none()

    for resource in phase3_resources:
        for action in actions:
            perm_name = f"{resource}:{action}"
            existing = await session.execute(select(Permission).where(Permission.name == perm_name))
            perm = existing.scalar_one_or_none()
            if not perm:
                perm = Permission(
                    name=perm_name,
                    resource=resource,
                    action=action,
                    description=f"{action} {resource}",
                )
                session.add(perm)
                await session.flush()

            for role in (super_admin, hospital_admin):
                if not role:
                    continue
                rp = await session.execute(
                    select(RolePermission).where(
                        RolePermission.role_id == role.id,
                        RolePermission.permission_id == perm.id,
                    )
                )
                if not rp.scalar_one_or_none():
                    session.add(RolePermission(role_id=role.id, permission_id=perm.id))


async def _seed_patient_permissions(session: AsyncSession) -> None:
    """Grant Patient role permissions for chat, appointments, and voice read."""
    from app.core.constants import PermissionAction, UserRole
    from app.models.permission_model import Permission
    from app.models.role_model import Role, RolePermission

    result = await session.execute(select(Role).where(Role.name == UserRole.PATIENT))
    patient_role = result.scalar_one_or_none()
    if not patient_role:
        return

    patient_grants = [
        ("ai_chat", PermissionAction.CREATE),
        ("ai_chat", PermissionAction.READ),
        ("ai_chat", PermissionAction.UPDATE),
        ("appointments", PermissionAction.CREATE),
        ("appointments", PermissionAction.READ),
        ("appointments", PermissionAction.UPDATE),
        ("dashboard", PermissionAction.READ),
        ("patients", PermissionAction.READ),
        ("doctors", PermissionAction.READ),
        ("voice_reminder", PermissionAction.READ),
    ]

    for resource, action in patient_grants:
        perm_name = f"{resource}:{action}"
        result = await session.execute(select(Permission).where(Permission.name == perm_name))
        perm = result.scalar_one_or_none()
        if not perm:
            continue
        rp = await session.execute(
            select(RolePermission).where(
                RolePermission.role_id == patient_role.id,
                RolePermission.permission_id == perm.id,
            )
        )
        if not rp.scalar_one_or_none():
            session.add(RolePermission(role_id=patient_role.id, permission_id=perm.id))


async def _seed_default_super_admin(session: AsyncSession) -> None:
    """Ensure bootstrap Super Admin exists and can log in (fixes stale / manual DB rows)."""
    if not settings.SEED_SUPER_ADMIN:
        return

    from app.core.constants import UserRole
    from app.core.logger import logger
    from app.core.security import get_password_hash, verify_password
    from app.models.role_model import Role
    from app.models.user_model import User
    from app.utils.helpers import generate_user_code

    result = await session.execute(select(Role).where(Role.name == UserRole.SUPER_ADMIN))
    role = result.scalar_one_or_none()
    if not role:
        logger.warning("Super Admin role missing; cannot seed bootstrap admin.")
        return

    email = settings.SEED_SUPER_ADMIN_EMAIL.strip().lower()
    seed_pw = settings.SEED_SUPER_ADMIN_PASSWORD

    allow_resync = settings.SEED_SUPER_ADMIN_RESYNC_PASSWORD or (
        settings.APP_ENV.lower() not in ("production", "prod")
    )

    result = await session.execute(select(User).where(func.lower(User.email) == email))
    user = result.scalar_one_or_none()

    if not user:
        session.add(
            User(
                user_code=generate_user_code(),
                email=email,
                hashed_password=get_password_hash(seed_pw),
                full_name="System Administrator",
                role_id=role.id,
                is_active=True,
                is_verified=True,
            )
        )
        logger.info("Bootstrap Super Admin created for %s", email)
        return

    if user.role_id != role.id:
        logger.warning(
            "SEED_SUPER_ADMIN_EMAIL %s is already used by a non-Super-Admin account; "
            "use another email for SEED_SUPER_ADMIN_EMAIL or delete/rename that user.",
            email,
        )
        return

    changed = False
    if not user.is_active or not user.is_verified:
        user.is_active = True
        user.is_verified = True
        changed = True

    pw_ok = False
    if user.hashed_password:
        try:
            pw_ok = verify_password(seed_pw, user.hashed_password)
        except (ValueError, TypeError):
            pw_ok = False

    if not pw_ok and allow_resync:
        user.hashed_password = get_password_hash(seed_pw)
        changed = True
        logger.info(
            "Bootstrap Super Admin password was synchronized from settings for %s "
            "(non-production APP_ENV or SEED_SUPER_ADMIN_RESYNC_PASSWORD).",
            email,
        )
    elif not pw_ok:
        logger.warning(
            "Super Admin %s exists but the password in the DB does not match "
            "SEED_SUPER_ADMIN_PASSWORD. Set SEED_SUPER_ADMIN_RESYNC_PASSWORD=true once, "
            "or reset the password via /auth/reset-password.",
            email,
        )

    if changed:
        await session.flush()
