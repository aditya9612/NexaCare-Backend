from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import NotFoundException, ForbiddenException, BadRequestException
from app.core.constants import UserRole
from app.models.branch_model import Branch
from app.models.user_model import User
from app.repositories.branch_repository import BranchRepository
from app.repositories.hospital_repository import HospitalRepository
from app.repositories.audit_repository import AuditRepository
from app.schemas.branch_schema import BranchCreate, BranchUpdate, BranchResponse
from app.utils.helpers import generate_branch_code
from app.utils.pagination import build_paginated_result, PaginatedResult

class BranchService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = BranchRepository(db)
        self.hospital_repo = HospitalRepository(db)
        self.audit_repo = AuditRepository(db)

    def _to_response(self, branch: Branch) -> BranchResponse:
        return BranchResponse.model_validate(branch)

    async def create_branch(self, data: BranchCreate, current_user: User) -> BranchResponse:
        is_super = current_user.role and current_user.role.name == UserRole.SUPER_ADMIN
        is_hospital_admin = current_user.role and current_user.role.name == UserRole.HOSPITAL_ADMIN

        if is_super:
            if not data.hospital_id:
                raise BadRequestException("hospital_id is required for Super Admin to create a branch")
            hospital_id = data.hospital_id
        elif is_hospital_admin:
            if not current_user.hospital_id:
                raise ForbiddenException("Hospital Admin is not associated with any hospital")
            hospital_id = current_user.hospital_id
        else:
            raise ForbiddenException("Only administrators can create branches")

        # Validate hospital exists
        hospital = await self.hospital_repo.get_by_id(hospital_id)
        if not hospital:
            raise NotFoundException(f"Hospital with ID {hospital_id} not found")

        # Create branch
        branch = Branch(
            hospital_id=hospital_id,
            name=data.name,
            phone=data.phone,
            email=data.email,
            address=data.address,
            code=generate_branch_code(),
            is_active=True
        )
        branch = await self.repo.create(branch)
        await self.audit_repo.create("create", "branches", user_id=current_user.id, resource_id=str(branch.id))
        return self._to_response(branch)

    async def list_branches(self, current_user: User, page: int = 1, size: int = 20, hospital_id: int | None = None) -> PaginatedResult[BranchResponse]:
        is_super = current_user.role and current_user.role.name == UserRole.SUPER_ADMIN
        is_hospital_admin = current_user.role and current_user.role.name == UserRole.HOSPITAL_ADMIN

        if is_hospital_admin:
            target_hospital_id = current_user.hospital_id
        elif is_super:
            target_hospital_id = hospital_id
        else:
            raise ForbiddenException("Access denied")

        skip = (page - 1) * size
        items = await self.repo.list_branches(hospital_id=target_hospital_id, skip=skip, limit=size)
        total = await self.repo.count_branches(hospital_id=target_hospital_id)

        return build_paginated_result(
            [self._to_response(item) for item in items],
            total,
            page,
            size
        )

    async def get_branch(self, branch_id: int, current_user: User) -> BranchResponse:
        branch = await self.repo.get_by_id(branch_id)
        if not branch:
            raise NotFoundException(f"Branch with ID {branch_id} not found")

        is_super = current_user.role and current_user.role.name == UserRole.SUPER_ADMIN
        is_hospital_admin = current_user.role and current_user.role.name == UserRole.HOSPITAL_ADMIN

        if is_hospital_admin and branch.hospital_id != current_user.hospital_id:
            raise ForbiddenException("Access denied to this branch")
        elif not is_super and not is_hospital_admin:
            raise ForbiddenException("Access denied")

        return self._to_response(branch)

    async def update_branch(self, branch_id: int, data: BranchUpdate, current_user: User) -> BranchResponse:
        branch = await self.repo.get_by_id(branch_id)
        if not branch:
            raise NotFoundException(f"Branch with ID {branch_id} not found")

        is_super = current_user.role and current_user.role.name == UserRole.SUPER_ADMIN
        is_hospital_admin = current_user.role and current_user.role.name == UserRole.HOSPITAL_ADMIN

        if is_hospital_admin and branch.hospital_id != current_user.hospital_id:
            raise ForbiddenException("Access denied to edit this branch")
        elif not is_super and not is_hospital_admin:
            raise ForbiddenException("Access denied")

        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(branch, key, value)

        branch = await self.repo.update(branch)
        await self.audit_repo.create("update", "branches", user_id=current_user.id, resource_id=str(branch.id))
        return self._to_response(branch)

    async def delete_branch(self, branch_id: int, current_user: User) -> None:
        branch = await self.repo.get_by_id(branch_id)
        if not branch:
            raise NotFoundException(f"Branch with ID {branch_id} not found")

        is_super = current_user.role and current_user.role.name == UserRole.SUPER_ADMIN
        is_hospital_admin = current_user.role and current_user.role.name == UserRole.HOSPITAL_ADMIN

        if is_hospital_admin and branch.hospital_id != current_user.hospital_id:
            raise ForbiddenException("Access denied to delete this branch")
        elif not is_super and not is_hospital_admin:
            raise ForbiddenException("Access denied")

        await self.repo.delete(branch)
        await self.audit_repo.create("delete", "branches", user_id=current_user.id, resource_id=str(branch.id))
