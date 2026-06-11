from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import ConflictException, NotFoundException, BadRequestException
from app.models.staff_model import Staff
from app.repositories.staff_repository import StaffRepository
from app.repositories.department_repository import DepartmentRepository
from app.repositories.rbac_repository import RBACRepository
from app.repositories.audit_repository import AuditRepository
from app.schemas.staff_schema import (
    StaffCreate,
    StaffUpdate,
    StaffResponse,
)
from app.utils.pagination import build_paginated_result, PaginatedResult

class StaffService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = StaffRepository(db)
        self.dept_repo = DepartmentRepository(db)
        self.rbac_repo = RBACRepository(db)
        self.audit_repo = AuditRepository(db)

    async def _validate_department_and_role(self, department_id: int | None, role_id: int | None):
        if department_id is not None:
            dept = await self.dept_repo.get_by_id(department_id)
            if not dept:
                raise NotFoundException("Department not found")
        if role_id is not None:
            role = await self.rbac_repo.get_role_by_id(role_id)
            if not role:
                raise NotFoundException("Role not found")

    async def create_staff(self, data: StaffCreate, current_user_id: int) -> StaffResponse:
        # Validate duplicates
        existing_email = await self.repo.get_by_email(data.email)
        if existing_email:
            raise ConflictException("Email already exists")
    
        existing_code = await self.repo.get_by_employee_code(data.employee_code)
        if existing_code:
            raise ConflictException("Employee code already exists")
    
        # Validate existence of department and role
        await self._validate_department_and_role(data.department_id, data.role_id)
    
        staff = Staff(**data.model_dump())
        staff = await self.repo.create(staff)
        
        # Eager load relationships by re-fetching
        staff = await self.repo.get_by_id(staff.id)
        if not staff:
            raise NotFoundException("Staff member not found")

        # Create audit log
        await self.audit_repo.create("create", "staff", user_id=current_user_id, resource_id=str(staff.id))
        
        return StaffResponse.model_validate(staff)

    async def list_staff(
        self,
        page: int = 1,
        size: int = 20,
        q: str | None = None,
        department_id: int | None = None,
        status: str | None = None,
    ) -> PaginatedResult[StaffResponse]:
        skip = (page - 1) * size
        items = await self.repo.list_all(
            skip=skip, limit=size, q=q, department_id=department_id, status=status
        )
        total = await self.repo.count_all(q=q, department_id=department_id, status=status)
        return build_paginated_result(
            [StaffResponse.model_validate(item) for item in items],
            total,
            page,
            size
        )

    async def get_dashboard_stats(self) -> dict:
        return await self.repo.get_dashboard_stats()

    async def get_staff_by_department(self, department_id: int) -> list[StaffResponse]:
        items = await self.repo.list_by_department(department_id)
        return [StaffResponse.model_validate(item) for item in items]

    async def get_staff_by_id(self, staff_id: int) -> StaffResponse:
        staff = await self.repo.get_by_id(staff_id)
        if not staff:
            raise NotFoundException("Staff member not found")
        return StaffResponse.model_validate(staff)

    async def update_staff(self, staff_id: int, data: StaffUpdate, current_user_id: int) -> StaffResponse:
        staff = await self.repo.get_by_id(staff_id)
        if not staff:
            raise NotFoundException("Staff member not found")
        
        # Check duplicate email if it is being changed
        if data.email:
            existing_email = await self.repo.get_by_email(data.email)
            if existing_email and existing_email.id != staff_id:
                raise ConflictException("Email already exists")
                
        # Check duplicate employee code if it is being changed
        if data.employee_code:
            existing_code = await self.repo.get_by_employee_code(data.employee_code)
            if existing_code and existing_code.id != staff_id:
                raise ConflictException("Employee code already exists")
                
        # Validate department/role if changed
        await self._validate_department_and_role(data.department_id, data.role_id)
        
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(staff, key, value)
            
        await self.repo.update(staff)
        
        # Eager-load relations again
        staff = await self.repo.get_by_id(staff_id)
        if not staff:
            raise NotFoundException("Staff member not found")
            
        await self.audit_repo.create("update", "staff", user_id=current_user_id, resource_id=str(staff.id))
        
        return StaffResponse.model_validate(staff)

    async def update_staff_status(self, staff_id: int, status: str, current_user_id: int) -> StaffResponse:
        staff = await self.repo.get_by_id(staff_id)
        if not staff:
            raise NotFoundException("Staff member not found")
            
        staff.status = status
        await self.repo.update(staff)
        
        # Eager-load relations
        staff = await self.repo.get_by_id(staff_id)
        if not staff:
            raise NotFoundException("Staff member not found")
            
        await self.audit_repo.create("update_status", "staff", user_id=current_user_id, resource_id=str(staff.id))
        
        return StaffResponse.model_validate(staff)

    async def delete_staff(self, staff_id: int, current_user_id: int) -> None:
        staff = await self.repo.get_by_id(staff_id)
        if not staff:
            raise NotFoundException("Staff member not found")
            
        await self.repo.soft_delete(staff)
        await self.audit_repo.create("delete", "staff", user_id=current_user_id, resource_id=str(staff.id))
