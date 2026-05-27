from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException, NotFoundException
from app.models.doctor_model import Doctor, DoctorSchedule
from app.repositories.audit_repository import AuditRepository
from app.repositories.department_repository import DepartmentRepository
from app.repositories.doctor_repository import DoctorRepository
from app.schemas.appointment_schema import AppointmentResponse
from app.schemas.doctor_schema import (
    DoctorCreate,
    DoctorResponse,
    DoctorScheduleCreate,
    DoctorScheduleResponse,
    DoctorUpdate,
)
from app.utils.helpers import generate_doctor_code
from app.utils.pagination import build_paginated_result


class DoctorService:
    def __init__(self, db: AsyncSession):
        self.repo = DoctorRepository(db)
        self.audit_repo = AuditRepository(db)
        self.dept_repo = DepartmentRepository(db)

    async def _validate_department(self, department_id: int | None) -> None:
        """Raise 404 if department_id is given but doesn't exist."""
        if department_id is not None:
            dept = await self.dept_repo.get_by_id(department_id)
            if not dept:
                raise NotFoundException(f"Department with ID {department_id} not found")

    async def list_doctors(
        self,
        page: int = 1,
        size: int = 20,
        department_id: int | None = None,
        availability_status: str | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ):
        skip = (page - 1) * size
        items = await self.repo.list_all(
            skip=skip, limit=size, department_id=department_id,
            availability_status=availability_status, sort_by=sort_by, sort_order=sort_order,
        )
        total = await self.repo.count_all(department_id=department_id, availability_status=availability_status)
        return build_paginated_result(
            [DoctorResponse.model_validate(d) for d in items], total, page, size
        )

    async def get_by_id(self, doctor_id: int) -> DoctorResponse:
        doctor = await self.repo.get_by_id(doctor_id)
        if not doctor:
            raise NotFoundException("Doctor not found")
        return DoctorResponse.model_validate(doctor)

    async def create(self, data: DoctorCreate, user_id: int) -> DoctorResponse:
        existing = await self.repo.get_by_license(data.license_number)
        if existing:
            raise ConflictException("License number already registered")
        await self._validate_department(data.department_id)
        doctor = Doctor(doctor_code=generate_doctor_code(), **data.model_dump())
        doctor = await self.repo.create(doctor)
        await self.audit_repo.create("create", "doctors", user_id=user_id, resource_id=str(doctor.id))
        return DoctorResponse.model_validate(doctor)

    async def update(self, doctor_id: int, data: DoctorUpdate, user_id: int) -> DoctorResponse:
        doctor = await self.repo.get_by_id(doctor_id)
        if not doctor:
            raise NotFoundException("Doctor not found")
        if data.license_number and data.license_number != doctor.license_number:
            existing = await self.repo.get_by_license(data.license_number)
            if existing:
                raise ConflictException("License number already registered")
        await self._validate_department(data.department_id)
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(doctor, key, value)
        doctor = await self.repo.update(doctor)
        await self.audit_repo.create("update", "doctors", user_id=user_id, resource_id=str(doctor.id))
        return DoctorResponse.model_validate(doctor)

    async def delete(self, doctor_id: int, user_id: int) -> None:
        doctor = await self.repo.get_by_id(doctor_id)
        if not doctor:
            raise NotFoundException("Doctor not found")
        await self.repo.soft_delete(doctor)
        await self.audit_repo.create("delete", "doctors", user_id=user_id, resource_id=str(doctor.id))

    async def search(self, q: str, page: int = 1, size: int = 20):
        skip = (page - 1) * size
        items = await self.repo.search(q, skip=skip, limit=size)
        total = await self.repo.count_search(q)
        return build_paginated_result(
            [DoctorResponse.model_validate(d) for d in items], total, page, size
        )

    async def list_available(self) -> list[DoctorResponse]:
        doctors = await self.repo.list_available()
        return [DoctorResponse.model_validate(d) for d in doctors]

    async def get_appointments(self, doctor_id: int) -> list[AppointmentResponse]:
        await self.get_by_id(doctor_id)
        appointments = await self.repo.get_appointments(doctor_id)
        return [AppointmentResponse.model_validate(a) for a in appointments]

    async def get_schedule(self, doctor_id: int) -> list[DoctorScheduleResponse]:
        await self.get_by_id(doctor_id)
        schedules = await self.repo.get_schedule(doctor_id)
        return [DoctorScheduleResponse.model_validate(s) for s in schedules]

    async def add_schedule(self, doctor_id: int, data: DoctorScheduleCreate, user_id: int) -> DoctorScheduleResponse:
        await self.get_by_id(doctor_id)
        if data.start_time >= data.end_time:
            raise ConflictException("Start time must be before end time")
        schedule = DoctorSchedule(doctor_id=doctor_id, **data.model_dump())
        schedule = await self.repo.add_schedule(schedule)
        await self.audit_repo.create("create", "doctor_schedules", user_id=user_id, resource_id=str(schedule.id))
        return DoctorScheduleResponse.model_validate(schedule)
