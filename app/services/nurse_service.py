from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException, NotFoundException
from app.models.nurse_model import Nurse
from app.repositories.audit_repository import AuditRepository
from app.repositories.department_repository import DepartmentRepository
from app.repositories.nurse_repository import NurseRepository
from app.schemas.nurse_schema import NurseCreate, NurseResponse, NurseUpdate
from app.utils.helpers import generate_nurse_code
from app.utils.pagination import build_paginated_result


class NurseService:
    def __init__(self, db: AsyncSession):
        self.repo = NurseRepository(db)
        self.audit_repo = AuditRepository(db)
        self.dept_repo = DepartmentRepository(db)

    async def _validate_department(self, department_id: int | None) -> None:
        """Raise 404 if department_id is given but doesn't exist."""
        if department_id is not None:
            dept = await self.dept_repo.get_by_id(department_id)
            if not dept:
                raise NotFoundException(f"Department with ID {department_id} not found")

    async def list_nurses(
        self,
        page: int = 1,
        size: int = 20,
        department_id: int | None = None,
        shift: str | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ):
        skip = (page - 1) * size
        items = await self.repo.list_all(
            skip=skip, limit=size, department_id=department_id,
            shift=shift, sort_by=sort_by, sort_order=sort_order,
        )
        total = await self.repo.count_all(department_id=department_id, shift=shift)
        return build_paginated_result(
            [NurseResponse.model_validate(n) for n in items], total, page, size
        )

    async def get_by_id(self, nurse_id: int) -> NurseResponse:
        nurse = await self.repo.get_by_id(nurse_id)
        if not nurse:
            raise NotFoundException("Nurse not found")
        return NurseResponse.model_validate(nurse)

    async def create(self, data: NurseCreate, user_id: int) -> NurseResponse:
        existing = await self.repo.get_by_license(data.license_number)
        if existing:
            raise ConflictException("License number already registered")
        await self._validate_department(data.department_id)
        nurse = Nurse(nurse_code=generate_nurse_code(), **data.model_dump())
        nurse = await self.repo.create(nurse)
        await self.audit_repo.create("create", "nurses", user_id=user_id, resource_id=str(nurse.id))
        return NurseResponse.model_validate(nurse)

    async def update(self, nurse_id: int, data: NurseUpdate, user_id: int) -> NurseResponse:
        nurse = await self.repo.get_by_id(nurse_id)
        if not nurse:
            raise NotFoundException("Nurse not found")
        if data.license_number and data.license_number != nurse.license_number:
            existing = await self.repo.get_by_license(data.license_number)
            if existing:
                raise ConflictException("License number already registered")
        await self._validate_department(data.department_id)
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(nurse, key, value)
        nurse = await self.repo.update(nurse)
        await self.audit_repo.create("update", "nurses", user_id=user_id, resource_id=str(nurse.id))
        return NurseResponse.model_validate(nurse)

    async def delete(self, nurse_id: int, user_id: int) -> None:
        nurse = await self.repo.get_by_id(nurse_id)
        if not nurse:
            raise NotFoundException("Nurse not found")
        await self.repo.delete(nurse)
        await self.audit_repo.create("delete", "nurses", user_id=user_id, resource_id=str(nurse_id))

    async def search(self, q: str, page: int = 1, size: int = 20):
        skip = (page - 1) * size
        items = await self.repo.search(q, skip=skip, limit=size)
        total = await self.repo.count_search(q)
        return build_paginated_result(
            [NurseResponse.model_validate(n) for n in items], total, page, size
        )
