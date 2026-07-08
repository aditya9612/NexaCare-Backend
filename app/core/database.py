from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.SQLALCHEMY_ECHO,
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


def run_migrations():
    import logging
    from alembic.config import Config
    from alembic import command
    logger = logging.getLogger("nexacare.db")
    try:
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")
        logger.info("Alembic database migrations successfully upgraded to head.")
    except Exception as e:
        logger.warning(f"Alembic auto-migration failed: {e}")


async def init_db():
    run_migrations()

    from app.models import (  # noqa: F401
        analytics_model,
        appointment_model,
        audit_log_model,
        bed_allocation_model,
        icu_telemetry_model,
        billing_model,
        chat_model,
        department_model,
        doctor_model,
        inventory_model,
        lab_model,
        nurse_model,
        patient_model,
        permission_model,
        pharmacy_model,
        refresh_token_model,
        role_model,
        user_model,
        voice_model,
        whatsapp_model,
        expense_model,
        vendor_model,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        await _seed_roles_and_permissions(session)
        await _seed_phase3_permissions(session)
        await _seed_patient_permissions(session)
        await _seed_bed_allocation_permissions(session)
        await _seed_icu_telemetry_permissions(session)
        await _seed_expense_permissions(session)
        await _seed_default_super_admin(session)
        await _seed_nurse_adesh(session)
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
        "users", "roles", "permissions", "patients", "doctors", "nurses", "staff", "appointments", "dashboard",
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
        "users", "roles", "permissions", "patients", "doctors", "nurses", "staff", "appointments",
        "dashboard", "billing", "pharmacy", "lab", "inventory", "ai_chat", "voice_reminder",
        "whatsapp", "analytics", "departments",
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

async def _seed_bed_allocation_permissions(session: AsyncSession) -> None:
    """Seed permissions for the Bed Allocation & Hospital Infrastructure module."""
    from app.core.constants import PermissionAction, UserRole
    from app.models.permission_model import Permission
    from app.models.role_model import Role, RolePermission

    resource = "bed_allocation"
    actions = [
        PermissionAction.CREATE,
        PermissionAction.READ,
        PermissionAction.UPDATE,
        PermissionAction.DELETE,
        PermissionAction.EXPORT,
        PermissionAction.APPROVE,
        PermissionAction.ASSIGN,
    ]

    # Create permissions if they don't exist
    perms = []
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
        perms.append(perm)

    # Roles that should receive all bed allocation permissions
    admin_role_names = [UserRole.SUPER_ADMIN, UserRole.HOSPITAL_ADMIN]
    for r_name in admin_role_names:
        result = await session.execute(select(Role).where(Role.name == r_name))
        role = result.scalar_one_or_none()
        if role:
            for perm in perms:
                rp = await session.execute(
                    select(RolePermission).where(
                        RolePermission.role_id == role.id,
                        RolePermission.permission_id == perm.id,
                    )
                )
                if not rp.scalar_one_or_none():
                    session.add(RolePermission(role_id=role.id, permission_id=perm.id))

    # Roles that should receive read/update/create/assign permissions
    clinical_role_names = [UserRole.DOCTOR, UserRole.NURSE, UserRole.RECEPTIONIST]
    clinical_actions = {PermissionAction.READ, PermissionAction.UPDATE, PermissionAction.CREATE, PermissionAction.ASSIGN}
    for r_name in clinical_role_names:
        result = await session.execute(select(Role).where(Role.name == r_name))
        role = result.scalar_one_or_none()
        if role:
            for perm in perms:
                if perm.action in clinical_actions:
                    rp = await session.execute(
                        select(RolePermission).where(
                            RolePermission.role_id == role.id,
                            RolePermission.permission_id == perm.id,
                        )
                    )
                    if not rp.scalar_one_or_none():
                        session.add(RolePermission(role_id=role.id, permission_id=perm.id))


async def _seed_icu_telemetry_permissions(session: AsyncSession) -> None:
    """Seed permissions for ICU telemetry module."""
    from app.core.constants import PermissionAction, UserRole
    from app.models.permission_model import Permission
    from app.models.role_model import Role, RolePermission

    resource = "icu_telemetry"
    actions = [
        PermissionAction.CREATE,
        PermissionAction.READ,
        PermissionAction.UPDATE,
        PermissionAction.DELETE,
        PermissionAction.EXPORT,
        PermissionAction.APPROVE,
        PermissionAction.ASSIGN,
    ]

    perms = []
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
        perms.append(perm)

    admin_role_names = [UserRole.SUPER_ADMIN, UserRole.HOSPITAL_ADMIN]
    for r_name in admin_role_names:
        result = await session.execute(select(Role).where(Role.name == r_name))
        role = result.scalar_one_or_none()
        if role:
            for perm in perms:
                rp = await session.execute(
                    select(RolePermission).where(
                        RolePermission.role_id == role.id,
                        RolePermission.permission_id == perm.id,
                    )
                )
                if not rp.scalar_one_or_none():
                    session.add(RolePermission(role_id=role.id, permission_id=perm.id))

    clinical_role_names = [UserRole.DOCTOR, UserRole.NURSE]
    clinical_actions = {PermissionAction.READ, PermissionAction.UPDATE}
    for r_name in clinical_role_names:
        result = await session.execute(select(Role).where(Role.name == r_name))
        role = result.scalar_one_or_none()
        if role:
            for perm in perms:
                if perm.action in clinical_actions:
                    rp = await session.execute(
                        select(RolePermission).where(
                            RolePermission.role_id == role.id,
                            RolePermission.permission_id == perm.id,
                        )
                    )
                    if not rp.scalar_one_or_none():
                        session.add(RolePermission(role_id=role.id, permission_id=perm.id))


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


async def _seed_nurse_adesh(session: AsyncSession) -> None:
    """Ensure the specific nurse user adesh.kale@staff.com exists, is active/verified, and has a Nurse profile."""
    from app.core.constants import UserRole
    from app.core.logger import logger
    from app.core.security import get_password_hash
    from app.models.role_model import Role
    from app.models.user_model import User
    from app.models.nurse_model import Nurse
    from app.utils.helpers import generate_user_code

    # 1. Find the Nurse role
    result = await session.execute(select(Role).where(Role.name == UserRole.NURSE))
    role = result.scalar_one_or_none()
    if not role:
        logger.warning("Nurse role missing; cannot seed adesh.kale@staff.com.")
        return

    email = "adesh.kale@staff.com"
    result = await session.execute(select(User).where(func.lower(User.email) == email))
    user = result.scalar_one_or_none()

    if not user:
        user = User(
            user_code=generate_user_code(),
            email=email,
            hashed_password=get_password_hash("123456"),
            full_name="Adesh Kale",
            role_id=role.id,
            is_active=True,
            is_verified=True,
        )
        session.add(user)
        await session.flush()
        logger.info("Nurse user created for %s", email)
    else:
        # Ensure user is active, verified, has the right role, and password
        user.is_active = True
        user.is_verified = True
        user.role_id = role.id
        user.hashed_password = get_password_hash("123456")
        await session.flush()

    # 2. Ensure Nurse profile exists
    result_nurse = await session.execute(select(Nurse).where(Nurse.user_id == user.id))
    nurse = result_nurse.scalar_one_or_none()
    if not nurse:
        nurse = Nurse(
            nurse_code=f"N-{user.user_code}",
            user_id=user.id,
            license_number="LIC-ADESHKALE-123",
            shift="Day Shift (07:00 AM - 07:00 PM)",
        )
        session.add(nurse)
        await session.flush()
        logger.info("Nurse profile created for %s", email)


async def _seed_expense_permissions(session: AsyncSession) -> None:
    """Seed permissions for the Expense Management & Vendor modules and assign to Admin and Accountant roles."""
    from app.core.constants import PermissionAction, UserRole
    from app.models.permission_model import Permission
    from app.models.role_model import Role, RolePermission

    resources = ["expense", "vendor"]
    actions = [
        PermissionAction.CREATE,
        PermissionAction.READ,
        PermissionAction.UPDATE,
        PermissionAction.DELETE,
        PermissionAction.EXPORT,
        PermissionAction.APPROVE,
        PermissionAction.ASSIGN,
    ]

    # Create permissions if they don't exist
    perms = []
    for resource in resources:
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
            perms.append(perm)

    # Roles to receive all expense and vendor permissions: Super Admin, Hospital Admin, Accountant
    target_roles = [UserRole.SUPER_ADMIN, UserRole.HOSPITAL_ADMIN, UserRole.ACCOUNTANT]
    for r_name in target_roles:
        result = await session.execute(select(Role).where(Role.name == r_name))
        role = result.scalar_one_or_none()
        if role:
            for perm in perms:
                rp = await session.execute(
                    select(RolePermission).where(
                        RolePermission.role_id == role.id,
                        RolePermission.permission_id == perm.id,
                    )
                )
                if not rp.scalar_one_or_none():
                    session.add(RolePermission(role_id=role.id, permission_id=perm.id))

