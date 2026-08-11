from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.exceptions import ConflictException, NotFoundException, BadRequestException
from app.models.staff_model import Staff, StaffSchedule
from app.models.user_model import User
from app.core.security import get_password_hash
from app.utils.helpers import generate_user_code
from app.repositories.staff_repository import StaffRepository
from app.repositories.department_repository import DepartmentRepository
from app.repositories.rbac_repository import RBACRepository
from app.repositories.audit_repository import AuditRepository
from app.schemas.staff_schema import (
    StaffCreate,
    StaffUpdate,
    StaffResponse,
    StaffScheduleCreate,
    StaffScheduleResponse,
    StaffScheduleUpdate,
)
from app.utils.pagination import build_paginated_result, PaginatedResult

class StaffService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = StaffRepository(db)
        self.dept_repo = DepartmentRepository(db)
        self.rbac_repo = RBACRepository(db)
        self.audit_repo = AuditRepository(db)

    async def _validate_department_and_role(self, department_id: int | None, role_name: str | None):
        if department_id is not None:
            dept = await self.dept_repo.get_by_id(department_id)
            if not dept:
                raise NotFoundException("Department not found")
        if role_name is not None:
            role = await self.rbac_repo.get_role_by_name(role_name)
            if not role:
                raise NotFoundException("Role not found")

    async def create_staff(self, data: StaffCreate, current_user_id: int) -> StaffResponse:
        # Validate duplicates in staff table
        existing_email = await self.repo.get_by_email(data.email)
        if existing_email:
            raise ConflictException("Email already exists")
    
        existing_code = await self.repo.get_by_staff_code(data.staff_code)
        if existing_code:
            raise ConflictException("Staff code already exists")
    
        # Validate existence of department and role
        await self._validate_department_and_role(data.department_id, data.role_name)
    
        # Validate duplicates in users table
        email_norm = data.email.strip().lower()
        existing_user_email = await self.db.scalar(
            select(User).where(func.lower(User.email) == email_norm)
        )
        if existing_user_email:
            raise ConflictException("User account with this email already exists")

        if data.phone:
            existing_user_phone = await self.db.scalar(
                select(User).where(User.phone == data.phone)
            )
            if existing_user_phone:
                raise ConflictException("User account with this phone already exists")

        # Resolve role
        role = await self.rbac_repo.get_role_by_name(data.role_name)
        if not role:
            raise NotFoundException("Role not found")

        # Retrieve actor's hospital context
        current_user = await self.db.get(User, current_user_id)
        hospital_id = current_user.hospital_id if current_user else None

        # Create user account for login
        user = User(
            user_code=generate_user_code(),
            email=email_norm,
            hashed_password=get_password_hash(data.password),
            full_name=data.full_name,
            phone=data.phone,
            role_id=role.id,
            hospital_id=hospital_id,
            is_active=True,
            is_verified=True,
        )
        self.db.add(user)
        await self.db.flush()

        from enum import Enum
        data_dict = {
            k: (v.value if isinstance(v, Enum) else v)
            for k, v in data.model_dump().items()
        }
        # Remove password from data_dict so it is not passed to Staff model constructor
        data_dict.pop("password", None)

        staff = Staff(**data_dict)
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
        status: int | None = None,
    ):
        skip = (page - 1) * size
        items = await self.repo.list_all(
            skip=skip, limit=size, q=q, department_id=department_id, status=status
        )
        total = await self.repo.count_all(q=q, department_id=department_id, status=status)
        
        # Calculate overall global counts (not affected by pagination, search query, department, or status filters)
        total_staff = await self.repo.count_all()
        active_staff = await self.repo.count_all(status=1)
        inactive_staff = await self.repo.count_all(status=0)

        paginated = build_paginated_result(
            [StaffResponse.model_validate(item) for item in items],
            total,
            page,
            size
        )
        return {
            "items": paginated.items,
            "total": paginated.total,
            "page": paginated.page,
            "size": paginated.size,
            "pages": paginated.pages,
            "total_staff": total_staff,
            "active_staff": active_staff,
            "inactive_staff": inactive_staff,
        }

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
                
        # Check duplicate staff code if it is being changed
        if data.staff_code:
            existing_code = await self.repo.get_by_staff_code(data.staff_code)
            if existing_code and existing_code.id != staff_id:
                raise ConflictException("Staff code already exists")
                
        # Validate department/role if changed
        await self._validate_department_and_role(data.department_id, data.role_name)
        
        from enum import Enum
        for key, value in data.model_dump(exclude_unset=True).items():
            if isinstance(value, Enum):
                value = value.value
            setattr(staff, key, value)
            
        await self.repo.update(staff)
        
        # Eager-load relations again
        staff = await self.repo.get_by_id(staff_id)
        if not staff:
            raise NotFoundException("Staff member not found")
            
        await self.audit_repo.create("update", "staff", user_id=current_user_id, resource_id=str(staff.id))
        
        return StaffResponse.model_validate(staff)

    async def update_staff_status(self, staff_id: int, status: int, current_user_id: int) -> StaffResponse:
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
        if staff.email:
            from app.models.user_model import User
            user = await self.db.scalar(
                select(User).where(func.lower(User.email) == staff.email.lower())
            )
            if user:
                user.is_active = False
        await self.audit_repo.create("delete", "staff", user_id=current_user_id, resource_id=str(staff.id))

    async def get_schedule(self, staff_id: int) -> list[StaffScheduleResponse]:
        staff = await self.repo.get_by_id(staff_id)
        if not staff:
            raise NotFoundException("Staff member not found")
            
        result = await self.db.scalars(
            select(StaffSchedule)
            .where(StaffSchedule.staff_id == staff_id)
            .order_by(StaffSchedule.day_of_week, StaffSchedule.start_time)
        )
        return [StaffScheduleResponse.model_validate(s) for s in result.all()]

    async def add_schedule(self, staff_id: int, data: StaffScheduleCreate, current_user_id: int) -> StaffScheduleResponse:
        staff = await self.repo.get_by_id(staff_id)
        if not staff:
            raise NotFoundException("Staff member not found")
            
        if staff.status != 1:
            raise BadRequestException("Cannot create schedule for an inactive staff member")
            
        # Check for overlaps
        existing_schedules = await self.db.scalars(
            select(StaffSchedule)
            .where(
                StaffSchedule.staff_id == staff_id,
                StaffSchedule.day_of_week == data.day_of_week
            )
        )
        for sched in existing_schedules.all():
            if not (data.end_time <= sched.start_time or data.start_time >= sched.end_time):
                raise ConflictException("Schedule overlaps with an existing slot")
                
        new_schedule = StaffSchedule(
            staff_id=staff_id,
            **data.model_dump()
        )
        self.db.add(new_schedule)
        await self.db.flush()
        
        await self.audit_repo.create("create_schedule", "staff", user_id=current_user_id, resource_id=str(staff_id))
        return StaffScheduleResponse.model_validate(new_schedule)

    async def delete_all_schedules(self, staff_id: int, current_user_id: int) -> None:
        staff = await self.repo.get_by_id(staff_id)
        if not staff:
            raise NotFoundException("Staff member not found")
            
        from sqlalchemy import delete
        await self.db.execute(
            delete(StaffSchedule).where(StaffSchedule.staff_id == staff_id)
        )
        await self.db.flush()
        await self.audit_repo.create("delete_all_schedules", "staff", user_id=current_user_id, resource_id=str(staff_id))

    async def delete_schedule_slot(self, staff_id: int, slot_id: int, current_user_id: int) -> None:
        staff = await self.repo.get_by_id(staff_id)
        if not staff:
            raise NotFoundException("Staff member not found")
            
        slot = await self.db.get(StaffSchedule, slot_id)
        if not slot or slot.staff_id != staff_id:
            raise NotFoundException("Schedule slot not found")
            
        await self.db.delete(slot)
        await self.db.flush()
        await self.audit_repo.create("delete_schedule_slot", "staff", user_id=current_user_id, resource_id=str(staff_id))

    async def update_schedule_slot(
        self, staff_id: int, slot_id: int, data: StaffScheduleUpdate, current_user_id: int
    ) -> StaffScheduleResponse:
        staff = await self.repo.get_by_id(staff_id)
        if not staff:
            raise NotFoundException("Staff member not found")

        slot = await self.db.get(StaffSchedule, slot_id)
        if not slot or slot.staff_id != staff_id:
            raise NotFoundException("Schedule slot not found")

        update_data = data.model_dump(exclude_unset=True)
        if not update_data:
            return StaffScheduleResponse.model_validate(slot)

        new_day = update_data.get("day_of_week", slot.day_of_week)
        new_start = update_data.get("start_time", slot.start_time)
        new_end = update_data.get("end_time", slot.end_time)

        if new_start >= new_end:
            raise ConflictException("Start time must be before end time")

        # Check for overlaps
        existing_schedules = await self.db.scalars(
            select(StaffSchedule)
            .where(
                StaffSchedule.staff_id == staff_id,
                StaffSchedule.day_of_week == new_day
            )
        )
        for sched in existing_schedules.all():
            if sched.id != slot_id:
                if not (new_end <= sched.start_time or new_start >= sched.end_time):
                    raise ConflictException("Schedule overlaps with an existing slot")

        for key, val in update_data.items():
            setattr(slot, key, val)

        await self.db.flush()
        await self.audit_repo.create("update_schedule_slot", "staff", user_id=current_user_id, resource_id=str(staff_id))
        return StaffScheduleResponse.model_validate(slot)
