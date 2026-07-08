from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import AppointmentStatus
from app.core.exceptions import ConflictException, NotFoundException
from app.models.appointment_model import Appointment
from app.repositories.appointment_repository import AppointmentRepository
from app.repositories.audit_repository import AuditRepository
from app.repositories.doctor_repository import DoctorRepository
from app.repositories.patient_repository import PatientRepository
from app.schemas.appointment_schema import (
    AppointmentCreate,
    AppointmentResponse,
    AppointmentUpdate,
    CancelRequest,
    ConfirmRequest,
    RescheduleRequest,
    TokenResponse,
)
from app.utils.helpers import generate_appointment_number
from app.utils.pagination import build_paginated_result


class AppointmentService:
    def __init__(self, db: AsyncSession):
        self.repo = AppointmentRepository(db)
        self.patient_repo = PatientRepository(db)
        self.doctor_repo = DoctorRepository(db)
        self.audit_repo = AuditRepository(db)

    async def _validate_entities(self, patient_id: int, doctor_id: int) -> None:
        if not await self.patient_repo.get_by_id(patient_id):
            raise NotFoundException("Patient not found")
        doctor = await self.doctor_repo.get_by_id(doctor_id)
        if not doctor:
            raise NotFoundException("Doctor not found")
        if doctor.availability_status not in ("available", "busy"):
            raise ConflictException("Doctor is not available for appointments")

    async def _check_conflict(self, doctor_id: int, appointment_date: date, appointment_time, exclude_id=None):
        if await self.repo.exists_conflict(doctor_id, appointment_date, appointment_time, exclude_id):
            raise ConflictException("Doctor already has an appointment at this slot")

    async def list_appointments(
        self,
        page: int = 1,
        size: int = 20,
        patient_id: int | None = None,
        doctor_id: int | None = None,
        department_id: int | None = None,
        status: str | None = None,
        appointment_date: date | None = None,
    ):
        skip = (page - 1) * size
        items = await self.repo.list_all(
            skip=skip, limit=size, patient_id=patient_id, doctor_id=doctor_id,
            department_id=department_id, status=status, appointment_date=appointment_date,
        )
        total = await self.repo.count_all(
            patient_id=patient_id, doctor_id=doctor_id,
            department_id=department_id, status=status, appointment_date=appointment_date,
        )
        return build_paginated_result(
            [AppointmentResponse.model_validate(a) for a in items], total, page, size
        )

    async def get_by_id(self, appointment_id: int) -> AppointmentResponse:
        appointment = await self.repo.get_by_id(appointment_id)
        if not appointment:
            raise NotFoundException("Appointment not found")
        return AppointmentResponse.model_validate(appointment)

    async def get_token(self, appointment_id: int) -> TokenResponse:
        appointment = await self.repo.get_by_id(appointment_id)

        if not appointment:
           raise NotFoundException("Appointment not found")

        return TokenResponse(
            appointment_id=appointment.id,
            token_number=appointment.token_number,
    )     

    async def create(self, data: AppointmentCreate, user_id: int) -> AppointmentResponse:
        await self._validate_entities(data.patient_id, data.doctor_id)
        await self._check_conflict(data.doctor_id, data.appointment_date, data.appointment_time)

        token = await self.repo.get_next_token(data.doctor_id, data.appointment_date)
        appointment = Appointment(
            appointment_number=generate_appointment_number(),
            token_number=token,
            appointment_status=AppointmentStatus.PENDING,
            **data.model_dump(),
        )
        appointment = await self.repo.create(appointment)
        await self.audit_repo.create("create", "appointments", user_id=user_id, resource_id=str(appointment.id))
        return AppointmentResponse.model_validate(appointment)

    async def update(self, appointment_id: int, data: AppointmentUpdate, user_id: int) -> AppointmentResponse:
        appointment = await self.repo.get_by_id(appointment_id)
        if not appointment:
            raise NotFoundException("Appointment not found")

        update_data = data.model_dump(exclude_unset=True)
        new_date = update_data.get("appointment_date", appointment.appointment_date)
        new_time = update_data.get("appointment_time", appointment.appointment_time)
        if "appointment_date" in update_data or "appointment_time" in update_data:
            await self._check_conflict(appointment.doctor_id, new_date, new_time, exclude_id=appointment_id)

        for key, value in update_data.items():
            setattr(appointment, key, value)
        appointment = await self.repo.update(appointment)
        await self.audit_repo.create("update", "appointments", user_id=user_id, resource_id=str(appointment.id))
        return AppointmentResponse.model_validate(appointment)

    async def delete(self, appointment_id: int, user_id: int) -> None:
        appointment = await self.repo.get_by_id(appointment_id)
        if not appointment:
            raise NotFoundException("Appointment not found")
        await self.repo.delete(appointment)
        await self.audit_repo.create("delete", "appointments", user_id=user_id, resource_id=str(appointment.id))

    async def reschedule(self, data: RescheduleRequest, user_id: int) -> AppointmentResponse:
        appointment = await self.repo.get_by_id(data.appointment_id)
        if not appointment:
            raise NotFoundException("Appointment not found")
        await self._check_conflict(
            appointment.doctor_id, data.appointment_date, data.appointment_time, exclude_id=appointment.id
        )
        appointment.appointment_date = data.appointment_date
        appointment.appointment_time = data.appointment_time
        appointment.appointment_status = AppointmentStatus.PENDING
        if data.notes:
            appointment.notes = data.notes
        appointment = await self.repo.update(appointment)
        await self.audit_repo.create("reschedule", "appointments", user_id=user_id, resource_id=str(appointment.id))
        return AppointmentResponse.model_validate(appointment)

    async def cancel(self, data: CancelRequest, user_id: int) -> AppointmentResponse:
        appointment = await self.repo.get_by_id(data.appointment_id)
        if not appointment:
            raise NotFoundException("Appointment not found")
        appointment.appointment_status = AppointmentStatus.CANCELLED
        if data.reason:
            appointment.notes = data.reason
        appointment = await self.repo.update(appointment)
        await self.audit_repo.create("cancel", "appointments", user_id=user_id, resource_id=str(appointment.id))
        return AppointmentResponse.model_validate(appointment)

    async def confirm(self, data: ConfirmRequest, user_id: int) -> AppointmentResponse:
        appointment = await self.repo.get_by_id(data.appointment_id)
        if not appointment:
            raise NotFoundException("Appointment not found")
        appointment.appointment_status = AppointmentStatus.CONFIRMED
        appointment = await self.repo.update(appointment)
        await self.audit_repo.create("confirm", "appointments", user_id=user_id, resource_id=str(appointment.id))
        return AppointmentResponse.model_validate(appointment)

    async def get_calendar(self, start_date: date, end_date: date, doctor_id: int | None = None):
        appointments = await self.repo.get_calendar(start_date, end_date, doctor_id)
        return [AppointmentResponse.model_validate(a) for a in appointments]

    async def get_today(self):
        appointments = await self.repo.get_today()
        return [AppointmentResponse.model_validate(a) for a in appointments]

    async def get_upcoming(self, limit: int = 20):
        appointments = await self.repo.get_upcoming(limit)
        return [AppointmentResponse.model_validate(a) for a in appointments]
