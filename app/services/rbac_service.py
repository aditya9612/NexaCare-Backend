from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.models.permission_model import Permission
from app.models.role_model import Role, RolePermission
from app.repositories.audit_repository import AuditRepository
from app.repositories.rbac_repository import RBACRepository
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
    RBACSeedDefaultsResponse,
)

VALID_TENANT_ARCHETYPES = {
    "DOCTOR",
    "NURSE",
    "RECEPTIONIST",
    "PHARMACIST",
    "LAB_TECHNICIAN",
    "ACCOUNTANT",
    "HOSPITAL_ADMIN",
    "PATIENT",
}


class RBACService:
    def __init__(self, db: AsyncSession):
        self.repo = RBACRepository(db)
        self.audit_repo = AuditRepository(db)

    async def create_role(self, data: RoleCreate, user_id: int, hospital_id: int | None = None) -> RoleResponse:
        target_hosp_id = data.hospital_id or hospital_id
        if await self.repo.get_role_by_name(data.name, target_hosp_id):
            raise BadRequestException("Role already exists")
        role_dict = data.model_dump()

        archetype = None
        if data.base_role_type:
            raw_archetype = data.base_role_type.upper().strip()
            if raw_archetype not in VALID_TENANT_ARCHETYPES:
                raise BadRequestException(
                    f"Invalid base archetype: '{data.base_role_type}'. Allowed: {', '.join(sorted(VALID_TENANT_ARCHETYPES))}"
                )
            if target_hosp_id and raw_archetype == "SUPER_ADMIN":
                raise BadRequestException("Tenant custom roles cannot be based on the SUPER_ADMIN archetype.")
            archetype = raw_archetype
            role_dict["base_role_type"] = archetype
        else:
            role_dict["base_role_type"] = None

        if target_hosp_id:
            role_dict["hospital_id"] = target_hosp_id
            role_dict["is_system"] = False
        else:
            role_dict["is_system"] = True

        role = await self.repo.create_role(Role(**role_dict))

        # Automatically clone baseline permissions from the system archetype role for new custom roles
        if archetype:
            sys_role = await self.repo.get_system_role_by_archetype(archetype)
            if isinstance(sys_role, Role):
                await self.repo.clone_role_permissions(sys_role.id, role.id)


        await self.audit_repo.create("create", "roles", user_id=user_id, resource_id=str(role.id))
        return RoleResponse.model_validate(role)

    async def list_roles(self, hospital_id: int | None = None) -> list[RoleResponse]:
        if hospital_id:
            roles = await self.repo.list_roles_for_tenant(hospital_id)
        else:
            roles = await self.repo.list_roles()
        return [RoleResponse.model_validate(r) for r in roles]

    async def get_role(self, role_id: int, hospital_id: int | None = None) -> RoleResponse:
        role = await self.repo.get_role_by_id(role_id)
        if not role:
            raise NotFoundException("Role not found")
        if hospital_id and role.hospital_id is not None and role.hospital_id != hospital_id:
            raise NotFoundException("Role not found")
        return RoleResponse.model_validate(role)

    async def update_role(
        self,
        role_id: int,
        data: RoleUpdate,
        user_id: int,
        hospital_id: int | None = None,
    ) -> RoleResponse:
        role = await self.repo.get_role_by_id(role_id)
        if not role:
            raise NotFoundException("Role not found")
        if role.is_system:
            raise BadRequestException("System roles cannot be modified.")
        if hospital_id and role.hospital_id != hospital_id:
            raise ForbiddenException("Cannot modify roles belonging to another hospital.")
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(role, key, value)
        role = await self.repo.update_role(role)
        await self.audit_repo.create("update", "roles", user_id=user_id, resource_id=str(role.id))
        return RoleResponse.model_validate(role)

    async def delete_role(self, role_id: int, user_id: int, hospital_id: int | None = None) -> None:
        role = await self.repo.get_role_by_id(role_id)
        if not role:
            raise NotFoundException("Role not found")
        if role.is_system:
            raise BadRequestException("System roles cannot be deleted.")
        if hospital_id and role.hospital_id != hospital_id:
            raise ForbiddenException("Cannot delete roles belonging to another hospital.")
        await self.repo.delete_role(role)
        await self.audit_repo.create("delete", "roles", user_id=user_id, resource_id=str(role_id))

    async def set_role_override(
        self,
        hospital_id: int,
        role_id: int,
        permission_id: int,
        is_granted: bool,
        user_id: int,
    ) -> RolePermissionOverrideResponse:
        role = await self.repo.get_role_by_id(role_id)
        if not role:
            raise NotFoundException("Role not found")
        if role.is_system:
            raise BadRequestException("Cannot set overrides on immutable system roles.")
        if role.hospital_id != hospital_id:
            raise ForbiddenException("Cannot set overrides for another hospital's role.")
        perm = await self.repo.get_permission_by_id(permission_id)
        if not perm:
            raise NotFoundException("Permission not found")

        override = await self.repo.set_role_override(
            hospital_id=hospital_id,
            role_id=role_id,
            permission_id=permission_id,
            is_granted=is_granted,
        )
        action = "grant" if is_granted else "revoke"
        await self.audit_repo.create(
            f"override_{action}",
            "role_permissions",
            user_id=user_id,
            resource_id=f"{role_id}:{permission_id}",
        )
        return RolePermissionOverrideResponse.model_validate(override)

    async def list_role_overrides(
        self,
        hospital_id: int,
        role_id: int | None = None,
    ) -> list[RolePermissionOverrideResponse]:
        overrides = await self.repo.get_role_overrides_for_hospital(hospital_id, role_id)
        return [RolePermissionOverrideResponse.model_validate(o) for o in overrides]


    async def create_permission(self, data: PermissionCreate, user_id: int) -> PermissionResponse:
        perm = await self.repo.create_permission(Permission(**data.model_dump()))
        await self.audit_repo.create("create", "permissions", user_id=user_id, resource_id=str(perm.id))
        return PermissionResponse.model_validate(perm)

    async def list_permissions(self) -> list[PermissionResponse]:
        perms = await self.repo.list_permissions()
        return [PermissionResponse.model_validate(p) for p in perms]

    async def get_permission(self, permission_id: int) -> PermissionResponse:
        perm = await self.repo.get_permission_by_id(permission_id)
        if not perm:
            raise NotFoundException("Permission not found")
        return PermissionResponse.model_validate(perm)

    async def update_permission(self, permission_id: int, data: PermissionUpdate, user_id: int) -> PermissionResponse:
        perm = await self.repo.get_permission_by_id(permission_id)
        if not perm:
            raise NotFoundException("Permission not found")
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(perm, key, value)
        perm = await self.repo.update_permission(perm)
        await self.audit_repo.create("update", "permissions", user_id=user_id, resource_id=str(perm.id))
        return PermissionResponse.model_validate(perm)

    async def delete_permission(self, permission_id: int, user_id: int) -> None:
        perm = await self.repo.get_permission_by_id(permission_id)
        if not perm:
            raise NotFoundException("Permission not found")
        await self.repo.delete_permission(perm)
        await self.audit_repo.create("delete", "permissions", user_id=user_id, resource_id=str(permission_id))

    async def assign_permission(
        self,
        data: RolePermissionCreate,
        user_id: int,
        hospital_id: int | None = None,
    ) -> RolePermissionResponse:
        role = await self.repo.get_role_by_id(data.role_id)
        if not role:
            raise NotFoundException("Role not found")
        if role.is_system:
            raise BadRequestException("Cannot assign permissions directly to immutable system roles. Use role overrides instead.")
        if hospital_id and role.hospital_id != hospital_id:
            raise ForbiddenException("Cannot assign permissions to another hospital's role.")
        perm = await self.repo.get_permission_by_id(data.permission_id)
        if not perm:
            raise NotFoundException("Permission not found")
        if await self.repo.role_permission_exists(data.role_id, data.permission_id):
            raise BadRequestException("Permission already assigned to role")
        rp = await self.repo.assign_permission(RolePermission(**data.model_dump()))
        await self.audit_repo.create("assign", "role_permissions", user_id=user_id, resource_id=str(rp.id))
        return RolePermissionResponse(
            id=rp.id,
            role_id=rp.role_id,
            permission_id=rp.permission_id,
        )

    async def list_role_permissions(self, role_id: int | None = None) -> list[RolePermissionResponse]:
        items = await self.repo.list_role_permissions(role_id)
        return [
            RolePermissionResponse(
                id=rp.id,
                role_id=rp.role_id,
                permission_id=rp.permission_id,
                role_name=rp.role.name if rp.role else None,
                permission_name=rp.permission.name if rp.permission else None,
            )
            for rp in items
        ]

    async def seed_system_defaults(
        self,
        include_test_users: bool = False,
        sync_super_admin: bool = True,
    ) -> RBACSeedDefaultsResponse:
        """
        Orchestrates full default RBAC seeding in a single atomic database transaction.
        Reuses all existing modular seed subroutines, ensures complete Super Admin & Hospital
        Admin coverage, safely creates bootstrap Super Admin without overwriting existing
        custom passwords, and optionally creates test users.
        """
        import time
        from sqlalchemy import func, select
        from app.core.config import settings
        from app.core.constants import UserRole
        from app.core.database import (
            _seed_roles_and_permissions,
            _seed_phase3_permissions,
            _seed_bed_allocation_permissions,
            _seed_icu_telemetry_permissions,
            _seed_patient_permissions,
            _seed_lab_technician_permissions,
            _seed_doctor_and_pharmacist_lab_permissions,
            _seed_expense_permissions,
            _seed_nurse_adesh,
            _seed_doctor_medical_records_and_inventory_permissions,
        )
        from app.core.security import get_password_hash
        from app.models.permission_model import Permission
        from app.models.role_model import Role, RolePermission
        from app.models.user_model import User
        from app.utils.helpers import generate_user_code

        start_time = time.perf_counter()

        try:
            # 1. Snapshot initial counts
            roles_before = await self.repo.db.scalar(select(func.count(Role.id))) or 0
            perms_before = await self.repo.db.scalar(select(func.count(Permission.id))) or 0
            rps_before = await self.repo.db.scalar(select(func.count(RolePermission.id))) or 0

            # 2. Execute existing modular seed routines
            await _seed_roles_and_permissions(self.repo.db)
            await _seed_phase3_permissions(self.repo.db)
            await _seed_bed_allocation_permissions(self.repo.db)
            await _seed_icu_telemetry_permissions(self.repo.db)
            await _seed_patient_permissions(self.repo.db)
            await _seed_lab_technician_permissions(self.repo.db)
            await _seed_doctor_and_pharmacist_lab_permissions(self.repo.db)
            await _seed_expense_permissions(self.repo.db)
            await _seed_doctor_medical_records_and_inventory_permissions(self.repo.db)

            # 3. Super Admin & Hospital Admin catch-all: ensure every single permission in DB is mapped
            admin_roles_res = await self.repo.db.execute(
                select(Role).where(Role.name.in_([UserRole.SUPER_ADMIN, UserRole.HOSPITAL_ADMIN]))
            )
            admin_roles = admin_roles_res.scalars().all()
            all_perms_res = await self.repo.db.execute(select(Permission))
            all_perms = all_perms_res.scalars().all()

            existing_rps_res = await self.repo.db.execute(select(RolePermission.role_id, RolePermission.permission_id))
            existing_rps = {(rp[0], rp[1]) for rp in existing_rps_res.all()}

            for a_role in admin_roles:
                for p in all_perms:
                    if (a_role.id, p.id) not in existing_rps:
                        self.repo.db.add(RolePermission(role_id=a_role.id, permission_id=p.id))
                        existing_rps.add((a_role.id, p.id))

            await self.repo.db.flush()

            # 4. Bootstrap Super Admin Account safely (Preserve existing custom password!)
            super_admin_status = "skipped"
            if sync_super_admin and settings.SEED_SUPER_ADMIN:
                sa_role = next((r for r in admin_roles if r.name == UserRole.SUPER_ADMIN), None)
                if not sa_role:
                    sa_role_res = await self.repo.db.execute(select(Role).where(Role.name == UserRole.SUPER_ADMIN))
                    sa_role = sa_role_res.scalar_one_or_none()

                if sa_role:
                    email = settings.SEED_SUPER_ADMIN_EMAIL.strip().lower()
                    existing_sa = (
                        await self.repo.db.scalars(select(User).where(func.lower(User.email) == email))
                    ).first()

                    if not existing_sa:
                        new_sa = User(
                            user_code=generate_user_code(),
                            email=email,
                            hashed_password=get_password_hash(settings.SEED_SUPER_ADMIN_PASSWORD),
                            full_name="System Administrator",
                            role_id=sa_role.id,
                            is_active=True,
                            is_verified=True,
                        )
                        self.repo.db.add(new_sa)
                        await self.repo.db.flush()
                        super_admin_status = "created"
                    else:
                        # Existing user: DO NOT overwrite password! Only ensure active, verified, role_id
                        existing_sa.is_active = True
                        existing_sa.is_verified = True
                        if existing_sa.role_id != sa_role.id:
                            existing_sa.role_id = sa_role.id
                        await self.repo.db.flush()
                        super_admin_status = "ready"

            # 5. Optional test users
            test_users_created: list[str] = []
            if include_test_users:
                adesh_email = "adesh.kale@staff.com"
                adesh_user = (
                    await self.repo.db.scalars(select(User).where(func.lower(User.email) == adesh_email))
                ).first()
                await _seed_nurse_adesh(self.repo.db)
                if not adesh_user:
                    test_users_created.append(adesh_email)
                else:
                    test_users_created.append(f"{adesh_email} (verified)")

            # 6. Commit transaction safely
            await self.repo.db.commit()

            # 7. Post-seeding snapshot
            roles_after = await self.repo.db.scalar(select(func.count(Role.id))) or 0
            perms_after = await self.repo.db.scalar(select(func.count(Permission.id))) or 0
            rps_after = await self.repo.db.scalar(select(func.count(RolePermission.id))) or 0

            elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

            return RBACSeedDefaultsResponse(
                environment=settings.APP_ENV,
                roles_created=max(0, roles_after - roles_before),
                roles_existing=roles_before,
                permissions_created=max(0, perms_after - perms_before),
                permissions_existing=perms_before,
                mappings_created=max(0, rps_after - rps_before),
                mappings_existing=rps_before,
                test_users_created=test_users_created,
                super_admin_status=super_admin_status,
                execution_time_ms=elapsed_ms,
            )
        except Exception:
            await self.repo.db.rollback()
            raise

