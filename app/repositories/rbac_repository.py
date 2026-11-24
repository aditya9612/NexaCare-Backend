from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.permission_model import Permission
from app.models.role_model import Role, RolePermission, RolePermissionOverride


class RBACRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_role(self, role: Role) -> Role:
        self.db.add(role)
        await self.db.flush()
        await self.db.refresh(role)
        return role

    async def get_role_by_id(self, role_id: int) -> Role | None:
        result = await self.db.execute(select(Role).where(Role.id == role_id))
        return result.scalar_one_or_none()

    async def get_role_by_name(self, name: str, hospital_id: int | None = None) -> Role | None:
        if hospital_id is not None:
            query = select(Role).where(Role.name == name, Role.hospital_id == hospital_id)
            res = await self.db.execute(query)
            custom_role = res.scalar_one_or_none()
            if custom_role:
                return custom_role

        # Fallback to system role
        result = await self.db.execute(select(Role).where(Role.name == name, Role.hospital_id.is_(None)))
        return result.scalar_one_or_none()

    async def list_roles(self, skip: int = 0, limit: int = 100) -> list[Role]:
        result = await self.db.execute(select(Role).offset(skip).limit(limit))
        return list(result.scalars().all())

    async def list_roles_for_tenant(
        self,
        hospital_id: int | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Role]:
        if hospital_id is None:
            query = select(Role).offset(skip).limit(limit)
        else:
            query = (
                select(Role)
                .where(
                    or_(
                        Role.hospital_id.is_(None),  # System template roles
                        Role.hospital_id == hospital_id,  # Tenant custom roles
                    )
                )
                .offset(skip)
                .limit(limit)
            )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count_roles(self) -> int:
        return await self.db.scalar(select(func.count()).select_from(Role)) or 0

    async def update_role(self, role: Role) -> Role:
        await self.db.flush()
        await self.db.refresh(role)
        return role

    async def delete_role(self, role: Role) -> None:
        await self.db.delete(role)
        await self.db.flush()

    async def create_permission(self, permission: Permission) -> Permission:
        self.db.add(permission)
        await self.db.flush()
        await self.db.refresh(permission)
        return permission

    async def list_permissions(self, skip: int = 0, limit: int = 500) -> list[Permission]:
        result = await self.db.execute(select(Permission).offset(skip).limit(limit))
        return list(result.scalars().all())

    async def get_permission_by_id(self, permission_id: int) -> Permission | None:
        result = await self.db.execute(select(Permission).where(Permission.id == permission_id))
        return result.scalar_one_or_none()

    async def get_permission_by_name(self, name: str) -> Permission | None:
        result = await self.db.execute(select(Permission).where(Permission.name == name))
        return result.scalar_one_or_none()

    async def update_permission(self, permission: Permission) -> Permission:
        await self.db.flush()
        await self.db.refresh(permission)
        return permission

    async def delete_permission(self, permission: Permission) -> None:
        await self.db.delete(permission)
        await self.db.flush()

    async def assign_permission(self, role_permission: RolePermission) -> RolePermission:
        self.db.add(role_permission)
        await self.db.flush()
        await self.db.refresh(role_permission)
        return role_permission

    async def list_role_permissions(self, role_id: int | None = None) -> list[RolePermission]:
        query = select(RolePermission).options(
            joinedload(RolePermission.role),
            joinedload(RolePermission.permission),
        )
        if role_id:
            query = query.where(RolePermission.role_id == role_id)
        result = await self.db.execute(query)
        return list(result.scalars().unique().all())

    async def get_user_permissions(self, role_id: int | None) -> list[str]:
        if not role_id:
            return []
        result = await self.db.execute(
            select(Permission.name)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role_id)
        )
        return list(result.scalars().all())

    async def get_user_effective_permissions(
        self,
        role_id: int | None,
        hospital_id: int | None = None,
    ) -> set[str]:
        """
        Calculates effective permissions: Base role_permissions +/- delta overrides
        Explicit deny (is_granted=False) always supersedes grants.
        """
        if not role_id:
            return set()

        base_perms = await self.get_user_permissions(role_id)
        effective = set(base_perms)

        if hospital_id:
            query = (
                select(Permission.name, RolePermissionOverride.is_granted)
                .join(RolePermissionOverride, RolePermissionOverride.permission_id == Permission.id)
                .where(
                    RolePermissionOverride.hospital_id == hospital_id,
                    RolePermissionOverride.role_id == role_id,
                )
            )
            result = await self.db.execute(query)
            for perm_name, is_granted in result.all():
                if is_granted:
                    effective.add(perm_name)
                else:
                    effective.discard(perm_name)

        return effective

    async def set_role_override(
        self,
        hospital_id: int,
        role_id: int,
        permission_id: int,
        is_granted: bool,
    ) -> RolePermissionOverride:
        query = select(RolePermissionOverride).where(
            RolePermissionOverride.hospital_id == hospital_id,
            RolePermissionOverride.role_id == role_id,
            RolePermissionOverride.permission_id == permission_id,
        )
        res = await self.db.execute(query)
        override = res.scalar_one_or_none()
        if override:
            override.is_granted = is_granted
        else:
            override = RolePermissionOverride(
                hospital_id=hospital_id,
                role_id=role_id,
                permission_id=permission_id,
                is_granted=is_granted,
            )
            self.db.add(override)
        await self.db.flush()
        return override

    async def get_role_overrides_for_hospital(
        self,
        hospital_id: int,
        role_id: int | None = None,
    ) -> list[RolePermissionOverride]:
        query = select(RolePermissionOverride).where(
            RolePermissionOverride.hospital_id == hospital_id
        )
        if role_id:
            query = query.where(RolePermissionOverride.role_id == role_id)
        res = await self.db.execute(query)
        return list(res.scalars().all())

    async def role_permission_exists(self, role_id: int, permission_id: int) -> bool:
        result = await self.db.execute(
            select(RolePermission).where(
                RolePermission.role_id == role_id,
                RolePermission.permission_id == permission_id,
            )
        )
        return result.scalar_one_or_none() is not None

    async def get_system_role_by_archetype(self, archetype: str) -> Role | None:
        result = await self.db.execute(
            select(Role).where(
                Role.is_system == True,
                func.upper(Role.base_role_type) == archetype.upper().strip(),
            )
        )
        return result.scalar_one_or_none()

    async def clone_role_permissions(self, source_role_id: int, target_role_id: int) -> int:
        source_perms = await self.db.execute(
            select(RolePermission.permission_id).where(RolePermission.role_id == source_role_id)
        )
        perm_ids = source_perms.scalars().all()
        for pid in perm_ids:
            self.db.add(RolePermission(role_id=target_role_id, permission_id=pid))
        await self.db.flush()
        return len(perm_ids)
