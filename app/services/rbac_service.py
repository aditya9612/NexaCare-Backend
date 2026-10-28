from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, NotFoundException
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
    RolePermissionResponse,
    RoleResponse,
    RoleUpdate,
)


class RBACService:
    def __init__(self, db: AsyncSession):
        self.repo = RBACRepository(db)
        self.audit_repo = AuditRepository(db)

    async def create_role(self, data: RoleCreate, user_id: int) -> RoleResponse:
        if await self.repo.get_role_by_name(data.name):
            raise BadRequestException("Role already exists")
        role = await self.repo.create_role(Role(**data.model_dump()))
        await self.audit_repo.create("create", "roles", user_id=user_id, resource_id=str(role.id))
        return RoleResponse.model_validate(role)

    async def list_roles(self) -> list[RoleResponse]:
        roles = await self.repo.list_roles()
        return [RoleResponse.model_validate(r) for r in roles]

    async def get_role(self, role_id: int) -> RoleResponse:
        role = await self.repo.get_role_by_id(role_id)
        if not role:
            raise NotFoundException("Role not found")
        return RoleResponse.model_validate(role)

    async def update_role(self, role_id: int, data: RoleUpdate, user_id: int) -> RoleResponse:
        role = await self.repo.get_role_by_id(role_id)
        if not role:
            raise NotFoundException("Role not found")
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(role, key, value)
        role = await self.repo.update_role(role)
        await self.audit_repo.create("update", "roles", user_id=user_id, resource_id=str(role.id))
        return RoleResponse.model_validate(role)

    async def delete_role(self, role_id: int, user_id: int) -> None:
        role = await self.repo.get_role_by_id(role_id)
        if not role:
            raise NotFoundException("Role not found")
        await self.repo.delete_role(role)
        await self.audit_repo.create("delete", "roles", user_id=user_id, resource_id=str(role_id))

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

    async def assign_permission(self, data: RolePermissionCreate, user_id: int) -> RolePermissionResponse:
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
