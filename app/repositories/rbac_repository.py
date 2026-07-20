from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.permission_model import Permission
from app.models.role_model import Role, RolePermission


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

    async def get_role_by_name(self, name: str) -> Role | None:
        result = await self.db.execute(select(Role).where(Role.name == name))
        return result.scalar_one_or_none()

    async def list_roles(self, skip: int = 0, limit: int = 100) -> list[Role]:
        result = await self.db.execute(select(Role).offset(skip).limit(limit))
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

    async def get_user_permissions(self, role_id: int) -> list[str]:
        result = await self.db.execute(
            select(Permission.name)
        )
        return list(result.scalars().all())

    async def role_permission_exists(self, role_id: int, permission_id: int) -> bool:
        result = await self.db.execute(
            select(RolePermission).where(
                RolePermission.role_id == role_id,
                RolePermission.permission_id == permission_id,
            )
        )
        return result.scalar_one_or_none() is not None
