from typing import Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.constants import UserRole
from app.core.dependencies import resolve_tenant_id
from app.core.exceptions import ConflictException, NotFoundException, BadRequestException, ForbiddenException
from app.models.staff_model import Staff, StaffSchedule
from app.models.user_model import User
from app.models.nurse_model import Nurse
from app.core.security import get_password_hash
from app.utils.helpers import generate_user_code, generate_nurse_code
from app.repositories.staff_repository import StaffRepository
from app.repositories.department_repository import DepartmentRepository
from app.repositories.rbac_repository import RBACRepository
from app.repositories.audit_repository import AuditRepository
from app.repositories.nurse_repository import NurseRepository
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
        self.nurse_repo = NurseRepository(db)

    async def _validate_department_and_role(
        self, department_id: int | None, role_name: str | None, hospital_id: int | None = None
    ):
        if department_id is not None:
            dept = await self.dept_repo.get_by_id(department_id, hospital_id=hospital_id)
            if not dept:
                raise NotFoundException("Department not found")
        if role_name is not None:
            role = await self.rbac_repo.get_role_by_name(role_name)
            if not role:
                raise NotFoundException("Role not found")

    async def create_staff(
        self, data: StaffCreate, current_user_id: int, current_user: Any | None = None
    ) -> StaffResponse:
        # Resolve tenant hospital context
        actor = current_user or await self.db.get(User, current_user_id)
        hospital_id = resolve_tenant_id(actor)
        if hospital_id is None and getattr(data, "hospital_id", None) is not None:
            hospital_id = data.hospital_id
        elif hospital_id is not None and getattr(data, "hospital_id", None) is not None:
            if actor and actor.role and actor.role.name != UserRole.SUPER_ADMIN and data.hospital_id != hospital_id:
                raise ForbiddenException("Cannot create staff for another hospital")

        # Validate duplicates in staff table
        existing_email = await self.repo.get_by_email(data.email)
        if existing_email:
            raise ConflictException("Email already exists")
    
        existing_code = await self.repo.get_by_staff_code(data.staff_code, hospital_id=hospital_id)
        if existing_code:
            raise ConflictException("Staff code already exists")
    
        # Validate existence of department and role within tenant scope
        await self._validate_department_and_role(data.department_id, data.role_name, hospital_id=hospital_id)

        is_nurse = bool(data.role_name and data.role_name.strip() == "Nurse")
        if is_nurse and data.license_number:
            existing_license = await self.nurse_repo.get_by_license(data.license_number)
            if existing_license:
                raise ConflictException("License number already registered")
    
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
        # Remove password, nurse-specific fields, and hospital_id so they are not passed to Staff model constructor twice
        data_dict.pop("password", None)
        data_dict.pop("hospital_id", None)
        nurse_license = data_dict.pop("license_number", None)
        nurse_shift = data_dict.pop("shift", None)

        staff = Staff(hospital_id=hospital_id, **data_dict)
        staff = await self.repo.create(staff)

        # If staff member is a Nurse, create linked Nurse profile
        if is_nurse and nurse_license:
            nurse_code = generate_nurse_code()
            while await self.nurse_repo.get_by_code(nurse_code):
                nurse_code = generate_nurse_code()

            nurse = Nurse(
                nurse_code=nurse_code,
                user_id=user.id,
                hospital_id=hospital_id,
                license_number=nurse_license,
                department_id=data.department_id,
                shift=nurse_shift,
            )
            await self.nurse_repo.create(nurse)
        
        # Eager load relationships by re-fetching
        staff = await self.repo.get_by_id(staff.id, hospital_id=hospital_id)
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
        role_name: str | None = None,
        current_user: Any | None = None,
    ):
        from app.core.dependencies import resolve_tenant_id
        hospital_id = resolve_tenant_id(current_user)
        skip = (page - 1) * size
        items = await self.repo.list_all(
            skip=skip, limit=size, q=q, department_id=department_id, status=status, role_name=role_name,
            hospital_id=hospital_id,
        )
        total = await self.repo.count_all(q=q, department_id=department_id, status=status, role_name=role_name, hospital_id=hospital_id)
        
        # Calculate overall global counts scoped by tenant
        total_staff = await self.repo.count_all(hospital_id=hospital_id)
        active_staff = await self.repo.count_all(status=1, hospital_id=hospital_id)
        inactive_staff = await self.repo.count_all(status=0, hospital_id=hospital_id)
        role_counts = await self.repo.get_role_counts(hospital_id=hospital_id)

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
            "role_counts": role_counts,
        }

    async def get_dashboard_stats(self, current_user: Any | None = None) -> dict:
        hospital_id = resolve_tenant_id(current_user)
        return await self.repo.get_dashboard_stats(hospital_id=hospital_id)

    async def get_staff_by_department(self, department_id: int, current_user: Any | None = None) -> list[StaffResponse]:
        hospital_id = resolve_tenant_id(current_user)
        if hospital_id is not None:
            dept = await self.dept_repo.get_by_id(department_id, hospital_id=hospital_id)
            if not dept:
                raise NotFoundException("Department not found")
        items = await self.repo.list_by_department(department_id, hospital_id=hospital_id)
        return [StaffResponse.model_validate(item) for item in items]

    async def get_staff_by_id(self, staff_id: int, current_user: Any | None = None) -> StaffResponse:
        hospital_id = resolve_tenant_id(current_user)
        staff = await self.repo.get_by_id(staff_id, hospital_id=hospital_id)
        if not staff:
            raise NotFoundException("Staff member not found")
        return StaffResponse.model_validate(staff)

    async def update_staff(
        self, staff_id: int, data: StaffUpdate, current_user_id: int, current_user: Any | None = None
    ) -> StaffResponse:
        actor = current_user or await self.db.get(User, current_user_id)
        hospital_id = resolve_tenant_id(actor)
        staff = await self.repo.get_by_id(staff_id, hospital_id=hospital_id)
        if not staff:
            raise NotFoundException("Staff member not found")
        
        # Check duplicate email if it is being changed
        if data.email:
            existing_email = await self.repo.get_by_email(data.email)
            if existing_email and existing_email.id != staff_id:
                raise ConflictException("Email already exists")
                
        # Check duplicate staff code if it is being changed
        if data.staff_code:
            existing_code = await self.repo.get_by_staff_code(data.staff_code, hospital_id=staff.hospital_id)
            if existing_code and existing_code.id != staff_id:
                raise ConflictException("Staff code already exists")
                
        # Validate department/role if changed within staff's hospital
        effective_hospital_id = staff.hospital_id or hospital_id
        if data.department_id is not None or data.role_name is not None:
            await self._validate_department_and_role(data.department_id, data.role_name, hospital_id=effective_hospital_id)
        
        from enum import Enum
        update_dict = data.model_dump(exclude_unset=True)
        nurse_license = update_dict.pop("license_number", None)
        nurse_shift = update_dict.pop("shift", None)

        # Sync with Nurse record if this staff member is a nurse
        effective_role = data.role_name or staff.role_name
        if effective_role == "Nurse":
            user = await self.db.scalar(
                select(User).where(func.lower(User.email) == staff.email.lower())
            )
            if user:
                nurse = await self.nurse_repo.get_by_user_id(user.id)
                if nurse:
                    if nurse_license and nurse_license != nurse.license_number:
                        existing_lic = await self.nurse_repo.get_by_license(nurse_license)
                        if existing_lic and existing_lic.id != nurse.id:
                            raise ConflictException("License number already registered")
                        nurse.license_number = nurse_license
                    if nurse_shift is not None:
                        nurse.shift = nurse_shift
                    if data.department_id is not None:
                        nurse.department_id = data.department_id
                    await self.nurse_repo.update(nurse)

        for key, value in update_dict.items():
            if isinstance(value, Enum):
                value = value.value
            setattr(staff, key, value)
            
        await self.repo.update(staff)
        
        # Eager-load relations again
        staff = await self.repo.get_by_id(staff_id, hospital_id=hospital_id)
        if not staff:
            raise NotFoundException("Staff member not found")
            
        await self.audit_repo.create("update", "staff", user_id=current_user_id, resource_id=str(staff.id))
        
        return StaffResponse.model_validate(staff)

    async def update_staff_status(
        self, staff_id: int, status: int, current_user_id: int, current_user: Any | None = None
    ) -> StaffResponse:
        actor = current_user or await self.db.get(User, current_user_id)
        hospital_id = resolve_tenant_id(actor)
        staff = await self.repo.get_by_id(staff_id, hospital_id=hospital_id)
        if not staff:
            raise NotFoundException("Staff member not found")
            
        staff.status = status
        await self.repo.update(staff)
        
        # Eager-load relations
        staff = await self.repo.get_by_id(staff_id, hospital_id=hospital_id)
        if not staff:
            raise NotFoundException("Staff member not found")
            
        await self.audit_repo.create("update_status", "staff", user_id=current_user_id, resource_id=str(staff.id))
        
        return StaffResponse.model_validate(staff)

    async def delete_staff(
        self, staff_id: int, current_user_id: int, current_user: Any | None = None
    ) -> None:
        actor = current_user or await self.db.get(User, current_user_id)
        hospital_id = resolve_tenant_id(actor)
        staff = await self.repo.get_by_id(staff_id, hospital_id=hospital_id)
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

    async def get_schedule(self, staff_id: int, current_user: Any | None = None) -> list[StaffScheduleResponse]:
        hospital_id = resolve_tenant_id(current_user)
        staff = await self.repo.get_by_id(staff_id, hospital_id=hospital_id)
        if not staff:
            raise NotFoundException("Staff member not found")
            
        result = await self.db.scalars(
            select(StaffSchedule)
            .where(StaffSchedule.staff_id == staff_id)
            .order_by(StaffSchedule.day_of_week, StaffSchedule.start_time)
        )
        return [StaffScheduleResponse.model_validate(s) for s in result.all()]

    async def add_schedule(
        self, staff_id: int, data: StaffScheduleCreate, current_user_id: int, current_user: Any | None = None
    ) -> StaffScheduleResponse:
        actor = current_user or await self.db.get(User, current_user_id)
        hospital_id = resolve_tenant_id(actor)
        staff = await self.repo.get_by_id(staff_id, hospital_id=hospital_id)
        if not staff:
            raise NotFoundException("Staff member not found")
            
        if staff.status != 1:
            raise BadRequestException("Cannot create schedule for an inactive staff member")
            
        if data.start_time >= data.end_time:
            raise BadRequestException("Start time must be before end time")
            
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

    async def delete_all_schedules(
        self, staff_id: int, current_user_id: int, current_user: Any | None = None
    ) -> None:
        actor = current_user or await self.db.get(User, current_user_id)
        hospital_id = resolve_tenant_id(actor)
        staff = await self.repo.get_by_id(staff_id, hospital_id=hospital_id)
        if not staff:
            raise NotFoundException("Staff member not found")
            
        from sqlalchemy import delete
        await self.db.execute(
            delete(StaffSchedule).where(StaffSchedule.staff_id == staff_id)
        )
        await self.db.flush()
        await self.audit_repo.create("delete_all_schedules", "staff", user_id=current_user_id, resource_id=str(staff_id))

    async def delete_schedule_slot(
        self, staff_id: int, slot_id: int, current_user_id: int, current_user: Any | None = None
    ) -> None:
        actor = current_user or await self.db.get(User, current_user_id)
        hospital_id = resolve_tenant_id(actor)
        staff = await self.repo.get_by_id(staff_id, hospital_id=hospital_id)
        if not staff:
            raise NotFoundException("Staff member not found")
            
        slot = await self.db.get(StaffSchedule, slot_id)
        if not slot or slot.staff_id != staff_id:
            raise NotFoundException("Schedule slot not found")
            
        await self.db.delete(slot)
        await self.db.flush()
        await self.audit_repo.create("delete_schedule_slot", "staff", user_id=current_user_id, resource_id=str(staff_id))

    async def update_schedule_slot(
        self, staff_id: int, slot_id: int, data: StaffScheduleUpdate, current_user_id: int, current_user: Any | None = None
    ) -> StaffScheduleResponse:
        actor = current_user or await self.db.get(User, current_user_id)
        hospital_id = resolve_tenant_id(actor)
        staff = await self.repo.get_by_id(staff_id, hospital_id=hospital_id)
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
