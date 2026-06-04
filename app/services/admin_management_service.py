from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import NotFoundException, BadRequestException
from app.core.constants import UserRole
from app.core.security import get_password_hash
from app.models.user_model import User
from app.repositories.admin_management_repository import AdminManagementRepository
from app.repositories.hospital_repository import HospitalRepository
from app.repositories.rbac_repository import RBACRepository
from app.repositories.audit_repository import AuditRepository
from app.schemas.admin_management_schema import AdminCreate, AdminUpdate, AdminResponse
from app.utils.helpers import generate_user_code
from app.utils.pagination import build_paginated_result, PaginatedResult

class AdminManagementService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = AdminManagementRepository(db)
        self.hospital_repo = HospitalRepository(db)
        self.rbac_repo = RBACRepository(db)
        self.audit_repo = AuditRepository(db)

    def _to_response(self, user: User) -> AdminResponse:
        return AdminResponse(
            id=user.id,
            user_code=user.user_code,
            email=user.email,
            full_name=user.full_name,
            phone=user.phone,
            role_id=user.role_id,
            role_name=user.role.name if user.role else None,
            hospital_id=user.hospital_id,
            hospital_name=user.hospital.name if user.hospital else None,
            profile_image=user.profile_image,
            gender=user.gender,
            date_of_birth=user.date_of_birth,
            is_active=user.is_active,
            is_verified=user.is_verified,
            last_login=user.last_login,
            created_at=user.created_at,
            updated_at=user.updated_at
        )

    async def create_admin(self, data: AdminCreate, current_user: User) -> AdminResponse:
        # Check duplicate email globally
        existing = await self.repo.get_by_email(data.email)
        if existing:
            raise BadRequestException("Email already registered")

        # Check duplicate phone globally
        if data.phone:
            existing_phone = await self.repo.get_by_phone(data.phone)
            if existing_phone:
                raise BadRequestException("Phone number already in use")

        # Validate hospital
        if data.hospital_id:
            hospital = await self.hospital_repo.get_by_id(data.hospital_id)
            if not hospital:
                raise NotFoundException("Hospital not found")



        # Resolve role
        role = await self.rbac_repo.get_role_by_name(UserRole.HOSPITAL_ADMIN)
        if not role:
            raise BadRequestException("Hospital Admin role not seeded")

        # Create user
        user = User(
            user_code=generate_user_code(),
            email=data.email.strip().lower(),
            hashed_password=get_password_hash(data.password),
            full_name=data.full_name,
            phone=data.phone,
            role_id=role.id,
            hospital_id=data.hospital_id,
            gender=data.gender,
            date_of_birth=data.date_of_birth,
            is_active=True,
            is_verified=True,
        )
        
        user = await self.repo.create(user)
        # Re-fetch to load relationships properly
        user = await self.repo.get_by_id(user.id)
        
        await self.audit_repo.create("create", "users", user_id=current_user.id, resource_id=str(user.id))
        return self._to_response(user)

    async def list_admins(
        self,
        page: int = 1,
        size: int = 20,
        search: str | None = None,
        hospital_id: int | None = None,
        is_active: bool | None = None
    ) -> PaginatedResult[AdminResponse]:
        skip = (page - 1) * size
        items = await self.repo.list_admins(
            skip=skip,
            limit=size,
            search=search,
            hospital_id=hospital_id,
            is_active=is_active
        )
        total = await self.repo.count_admins(
            search=search,
            hospital_id=hospital_id,
            is_active=is_active
        )

        return build_paginated_result(
            [self._to_response(item) for item in items],
            total,
            page,
            size
        )

    async def get_admin(self, admin_id: int) -> AdminResponse:
        admin = await self.repo.get_by_id(admin_id)
        if not admin:
            raise NotFoundException("Admin not found")
        return self._to_response(admin)

    async def update_admin(self, admin_id: int, data: AdminUpdate, current_user: User) -> AdminResponse:
        admin = await self.repo.get_by_id(admin_id)
        if not admin:
            raise NotFoundException("Admin not found")

        # Check duplicate phone (excluding this admin's own record)
        if data.phone is not None:
            existing_phone = await self.repo.get_by_phone(data.phone, exclude_user_id=admin_id)
            if existing_phone:
                raise BadRequestException("Phone number already in use by another user")

        # Resolve hospital_id context
        target_hospital_id = data.hospital_id if data.hospital_id is not None else admin.hospital_id
        if data.hospital_id is not None:
            hospital = await self.hospital_repo.get_by_id(data.hospital_id)
            if not hospital:
                raise NotFoundException("Hospital not found")



        # Update fields
        update_data = data.model_dump(exclude_unset=True)
        for key, val in update_data.items():
            setattr(admin, key, val)

        admin = await self.repo.update(admin)
        # Re-fetch to ensure relationships are updated
        admin = await self.repo.get_by_id(admin.id)

        await self.audit_repo.create("update", "users", user_id=current_user.id, resource_id=str(admin.id))
        return self._to_response(admin)

    async def update_status(self, admin_id: int, is_active: bool, current_user: User) -> AdminResponse:
        admin = await self.repo.get_by_id(admin_id)
        if not admin:
            raise NotFoundException("Admin not found")

        admin.is_active = is_active
        admin = await self.repo.update(admin)
        admin = await self.repo.get_by_id(admin.id)
        
        await self.audit_repo.create("update_status", "users", user_id=current_user.id, resource_id=str(admin.id))
        return self._to_response(admin)

    async def reset_password(self, admin_id: int, new_password: str, current_user: User) -> None:
        admin = await self.repo.get_by_id(admin_id)
        if not admin:
            raise NotFoundException("Admin not found")

        admin.hashed_password = get_password_hash(new_password)
        await self.repo.update(admin)
        
        await self.audit_repo.create("reset_password", "users", user_id=current_user.id, resource_id=str(admin.id))

    async def delete_admin(self, admin_id: int, current_user: User) -> None:
        admin = await self.repo.get_by_id(admin_id)
        if not admin:
            raise NotFoundException("Admin not found")

        admin.is_active = False
        await self.repo.update(admin)
        
        await self.audit_repo.create("deactivate", "users", user_id=current_user.id, resource_id=str(admin_id))
