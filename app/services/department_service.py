from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import NotFoundException, ConflictException
from app.models.department_model import Department
from app.repositories.department_repository import DepartmentRepository
from app.schemas.department_schema import DepartmentCreate, DepartmentUpdate, DepartmentResponse
from app.utils.pagination import build_paginated_result, PaginatedResult

class DepartmentService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = DepartmentRepository(db)

    def _to_response(self, department: Department, staff_count: int = 0) -> DepartmentResponse:
        res = DepartmentResponse.model_validate(department)
        res.staff_linked = staff_count
        return res

    async def create(self, data: DepartmentCreate) -> DepartmentResponse:
        existing = await self.repo.get_by_name(data.department_name)
        if existing:
            raise ConflictException(f"Department with name '{data.department_name}' already exists")
        
        if data.department_code:
            existing_code = await self.repo.get_by_code(data.department_code)
            if existing_code:
                raise ConflictException(f"Department with code '{data.department_code}' already exists")
        
        department = Department(
            department_code=data.department_code,
            department_name=data.department_name
        )
        department = await self.repo.create(department)
        return self._to_response(department, 0)

    async def get_by_id(self, department_id: int) -> DepartmentResponse:
        department = await self.repo.get_by_id(department_id)
        if not department:
            raise NotFoundException(f"Department with ID {department_id} not found")
        
        from app.models.staff_model import Staff
        from sqlalchemy import select, func
        staff_count = await self.db.scalar(
            select(func.count(Staff.id)).where(Staff.department_id == department_id, Staff.is_deleted.is_(False))
        ) or 0
        return self._to_response(department, staff_count)

    async def list_departments(self, page: int = 1, size: int = 20) -> PaginatedResult[DepartmentResponse]:
        skip = (page - 1) * size
        items = await self.repo.list_all(skip=skip, limit=size)
        total = await self.repo.count_all()

        # Batch fetch staff count for each department to avoid N+1 queries
        from app.models.staff_model import Staff
        from sqlalchemy import select, func
        dept_ids = [d.department_id for d in items]
        
        staff_counts = {}
        if dept_ids:
            stmt = (
                select(Staff.department_id, func.count(Staff.id))
                .where(Staff.department_id.in_(dept_ids), Staff.is_deleted.is_(False))
                .group_by(Staff.department_id)
            )
            res = await self.db.execute(stmt)
            staff_counts = {dept_id: count for dept_id, count in res.all()}

        return build_paginated_result(
            [self._to_response(item, staff_counts.get(item.department_id, 0)) for item in items],
            total,
            page,
            size
        )

    async def update(self, department_id: int, data: DepartmentUpdate) -> DepartmentResponse:
        department = await self.repo.get_by_id(department_id)
        if not department:
            raise NotFoundException(f"Department with ID {department_id} not found")

        if data.department_code is not None:
            existing_code = await self.repo.get_by_code(data.department_code)
            if existing_code and existing_code.department_id != department_id:
                raise ConflictException(f"Department with code '{data.department_code}' already exists")
            department.department_code = data.department_code

        if data.department_name is not None:
            existing = await self.repo.get_by_name(data.department_name)
            if existing and existing.department_id != department_id:
                raise ConflictException(f"Department with name '{data.department_name}' already exists")
            department.department_name = data.department_name

        department = await self.repo.update(department)
        
        from app.models.staff_model import Staff
        from sqlalchemy import select, func
        staff_count = await self.db.scalar(
            select(func.count(Staff.id)).where(Staff.department_id == department_id, Staff.is_deleted.is_(False))
        ) or 0
        return self._to_response(department, staff_count)

    async def delete(self, department_id: int) -> None:
        from sqlalchemy.exc import SQLAlchemyError
        department = await self.repo.get_by_id(department_id)
        if not department:
            raise NotFoundException(f"Department with ID {department_id} not found")
        try:
            await self.repo.delete(department)
            await self.db.commit()
        except SQLAlchemyError as exc:
            await self.db.rollback()
            raise ConflictException(
                "Cannot delete department because it is referenced by other records (e.g., doctors, staff, or appointments)."
            ) from exc

