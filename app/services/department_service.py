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

    def _to_response(self, department: Department) -> DepartmentResponse:
        return DepartmentResponse.model_validate(department)

    async def create(self, data: DepartmentCreate) -> DepartmentResponse:
        existing = await self.repo.get_by_name(data.department_name)
        if existing:
            raise ConflictException(f"Department with name '{data.department_name}' already exists")
        
        department = Department(
            department_name=data.department_name
        )
        department = await self.repo.create(department)
        return self._to_response(department)

    async def get_by_id(self, department_id: int) -> DepartmentResponse:
        department = await self.repo.get_by_id(department_id)
        if not department:
            raise NotFoundException(f"Department with ID {department_id} not found")
        return self._to_response(department)

    async def list_departments(self, page: int = 1, size: int = 20) -> PaginatedResult[DepartmentResponse]:
        skip = (page - 1) * size
        items = await self.repo.list_all(skip=skip, limit=size)
        total = await self.repo.count_all()
        return build_paginated_result(
            [self._to_response(item) for item in items],
            total,
            page,
            size
        )

    async def update(self, department_id: int, data: DepartmentUpdate) -> DepartmentResponse:
        department = await self.repo.get_by_id(department_id)
        if not department:
            raise NotFoundException(f"Department with ID {department_id} not found")

        if data.department_name is not None:
            existing = await self.repo.get_by_name(data.department_name)
            if existing and existing.department_id != department_id:
                raise ConflictException(f"Department with name '{data.department_name}' already exists")
            department.department_name = data.department_name

        department = await self.repo.update(department)
        return self._to_response(department)

    async def delete(self, department_id: int) -> None:
        from sqlalchemy.exc import IntegrityError
        department = await self.repo.get_by_id(department_id)
        if not department:
            raise NotFoundException(f"Department with ID {department_id} not found")
        try:
            await self.repo.delete(department)
        except IntegrityError as exc:
            raise ConflictException(
                "Cannot delete department because it is referenced by other records (e.g., doctors, staff, or appointments)."
            ) from exc

