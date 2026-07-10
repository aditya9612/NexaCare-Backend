from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException, BadRequestException, ConflictException
from app.models.clinical_record_model import ClinicalRecord
from app.repositories.clinical_record_repository import ClinicalRecordRepository
from app.repositories.patient_repository import PatientRepository
from app.repositories.doctor_repository import DoctorRepository
from app.repositories.appointment_repository import AppointmentRepository
from app.repositories.audit_repository import AuditRepository
from app.schemas.clinical_record_schema import (
    ClinicalRecordCreate,
    ClinicalRecordUpdate,
    ClinicalRecordResponse,
)
from app.utils.pagination import build_paginated_result


class ClinicalRecordService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.record_repo = ClinicalRecordRepository(db)
        self.patient_repo = PatientRepository(db)
        self.doctor_repo = DoctorRepository(db)
        self.appointment_repo = AppointmentRepository(db)
        self.audit_repo = AuditRepository(db)

    async def _validate_related_entities(self, patient_id: int, doctor_id: int, appointment_id: int | None = None, exclude_record_id: int | None = None):
        patient = await self.patient_repo.get_by_id(patient_id)
        if not patient:
            raise NotFoundException(f"Patient with ID {patient_id} not found")
        
        doctor = await self.doctor_repo.get_by_id(doctor_id)
        if not doctor:
            raise NotFoundException(f"Doctor with ID {doctor_id} not found")

        if appointment_id is not None:
            appointment = await self.appointment_repo.get_by_id(appointment_id)
            if not appointment:
                raise NotFoundException(f"Appointment with ID {appointment_id} not found")
            if appointment.patient_id != patient_id or appointment.doctor_id != doctor_id:
                raise BadRequestException(
                    f"Appointment ID {appointment_id} does not match patient ID {patient_id} and doctor ID {doctor_id}"
                )
            
            # Prevent duplicate records with the same appointment_id
            existing_records = await self.record_repo.list_all(appointment_id=appointment_id)
            if exclude_record_id is not None:
                existing_records = [r for r in existing_records if r.id != exclude_record_id]
            if len(existing_records) > 0:
                raise ConflictException(f"Clinical record already exists for appointment ID {appointment_id}")
        else:
            has_appointment = await self.appointment_repo.count_all(patient_id=patient_id, doctor_id=doctor_id) > 0
            if not has_appointment:
                raise BadRequestException(
                    f"No appointment exists for patient ID {patient_id} and doctor ID {doctor_id}. A clinical record can only be created if an appointment exists."
                )

    def _to_response_schema(self, record: ClinicalRecord) -> ClinicalRecordResponse:
        resp = ClinicalRecordResponse.model_validate(record)
        if record.patient:
            resp.patient_name = f"{record.patient.first_name} {record.patient.last_name}"
        if record.doctor:
            resp.doctor_name = f"{record.doctor.first_name} {record.doctor.last_name}"
        return resp

    async def create_record(self, data: ClinicalRecordCreate, user_id: int) -> ClinicalRecordResponse:
        await self._validate_related_entities(data.patient_id, data.doctor_id, data.appointment_id)
        record = ClinicalRecord(**data.model_dump())
        record = await self.record_repo.create(record)
        await self.audit_repo.create("create", "clinical_records", user_id=user_id, resource_id=str(record.id))
        return self._to_response_schema(record)

    async def get_record(self, record_id: int) -> ClinicalRecordResponse:
        record = await self.record_repo.get_by_id(record_id)
        if not record:
            raise NotFoundException(f"Clinical record with ID {record_id} not found")
        return self._to_response_schema(record)

    async def list_records(
        self,
        page: int = 1,
        size: int = 20,
        patient_id: int | None = None,
        doctor_id: int | None = None,
        appointment_id: int | None = None
    ):
        skip = (page - 1) * size
        items = await self.record_repo.list_all(
            skip=skip, limit=size, patient_id=patient_id, doctor_id=doctor_id, appointment_id=appointment_id
        )
        total = await self.record_repo.count_all(
            patient_id=patient_id, doctor_id=doctor_id, appointment_id=appointment_id
        )
        return build_paginated_result(
            [self._to_response_schema(r) for r in items], total, page, size
        )

    async def update_record(self, record_id: int, data: ClinicalRecordUpdate, user_id: int) -> ClinicalRecordResponse:
        record = await self.record_repo.get_by_id(record_id)
        if not record:
            raise NotFoundException(f"Clinical record with ID {record_id} not found")

        patient_id = data.patient_id if data.patient_id is not None else record.patient_id
        doctor_id = data.doctor_id if data.doctor_id is not None else record.doctor_id
        appointment_id = data.appointment_id if data.appointment_id is not None else record.appointment_id
        await self._validate_related_entities(patient_id, doctor_id, appointment_id, exclude_record_id=record_id)

        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(record, key, value)

        record = await self.record_repo.update(record)
        await self.audit_repo.create("update", "clinical_records", user_id=user_id, resource_id=str(record.id))
        return self._to_response_schema(record)

    async def delete_record(self, record_id: int, user_id: int) -> None:
        record = await self.record_repo.get_by_id(record_id)
        if not record:
            raise NotFoundException(f"Clinical record with ID {record_id} not found")

        await self.record_repo.soft_delete(record)
        await self.audit_repo.create("delete", "clinical_records", user_id=user_id, resource_id=str(record.id))
