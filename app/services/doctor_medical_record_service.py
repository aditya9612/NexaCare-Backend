from pathlib import Path

from fastapi import UploadFile

from app.core.config import settings
from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.models.doctor_medical_record_model import (
    DoctorMedicalRecord,
    PatientDiagnosis,
    TreatmentNote,
)
from app.repositories.doctor_medical_record_repository import DoctorMedicalRecordRepository
from app.repositories.patient_repository import PatientRepository
from app.schemas.doctor_medical_record_schema import (
    DiagnosisResponse,
    DiagnosisUpdate,
    MedicalRecordResponse,
    TreatmentNoteCreate,
    TreatmentNoteResponse,
)
from app.utils.file_upload import save_upload_file
from app.utils.pagination import build_paginated_result


class DoctorMedicalRecordService:
    def __init__(self, db):
        self.repo = DoctorMedicalRecordRepository(db)
        self.patient_repo = PatientRepository(db)
        from app.repositories.audit_repository import AuditRepository
        self.audit_repo = AuditRepository(db)

    async def _get_doctor_id(self, user_id: int) -> int | None:
        doctor = await self.repo.get_doctor_by_user_id(user_id)
        return doctor.id if doctor else None

    async def upload_report(
        self,
        patient_id: int,
        appointment_id: int,
        doctor_id: int,
        diagnosis: str,
        report_title: str | None,
        report_type: str | None,
        notes: str | None,
        symptoms: str | None,
        file: UploadFile | None,
        user_id: int,
    ) -> MedicalRecordResponse:
        logged_in_doctor_id = await self._get_doctor_id(user_id)
        if logged_in_doctor_id is not None and doctor_id != logged_in_doctor_id:
            raise ForbiddenException("You can only create medical records for your own patients")

        patient = await self.patient_repo.get_by_id(patient_id)
        if not patient:
            raise NotFoundException("Patient not found")

        from app.repositories.doctor_repository import DoctorRepository
        doctor_repo = DoctorRepository(self.repo.db)
        doctor = await doctor_repo.get_by_id(doctor_id)
        if not doctor:
            raise NotFoundException("Doctor not found")

        from sqlalchemy import select
        from app.models.appointment_model import Appointment
        stmt = select(Appointment).where(Appointment.id == appointment_id)
        res = await self.repo.db.execute(stmt)
        appointment = res.scalar_one_or_none()
        if not appointment:
            raise NotFoundException("Appointment not found")

        if appointment.patient_id != patient_id or appointment.doctor_id != doctor_id:
            raise BadRequestException("Appointment does not match patient and doctor")

        db_full_name = f"{patient.first_name} {patient.last_name}".strip()

        if file:
            allowed_types = {"application/pdf", "image/jpeg", "image/png"}
            if file.content_type not in allowed_types:
                raise BadRequestException("Only PDF, JPG and PNG files are allowed")
            file_path = await save_upload_file(file, settings.UPLOAD_DIR)
            file_name = file.filename or "report"
            file_type = file.content_type
        else:
            file_path = ""
            file_name = ""
            file_type = None

        record = DoctorMedicalRecord(
            patient_id=patient_id,
            doctor_id=doctor_id,
            patient_name=db_full_name,
            report_title=report_title or "Medical Record",
            report_type=report_type or "General",
            diagnosis=diagnosis,
            notes=notes,
            file_path=file_path,
            file_name=file_name,
            file_type=file_type,
        )

        record = await self.repo.create_record(record)

        diagnosis_record = await self.repo.get_diagnosis(patient_id)
        if diagnosis_record:
            if symptoms is not None:
                diagnosis_record.symptoms = symptoms
            diagnosis_record.diagnosis = diagnosis
            diagnosis_record.doctor_id = doctor_id
            await self.repo.update_diagnosis(diagnosis_record)
        else:
            diagnosis_record = PatientDiagnosis(
                patient_id=patient_id,
                doctor_id=doctor_id,
                diagnosis=diagnosis,
                symptoms=symptoms,
                notes=notes,
            )
            await self.repo.save_diagnosis(diagnosis_record)

        response_data = MedicalRecordResponse.model_validate(record)
        response_data.symptoms = diagnosis_record.symptoms
        return response_data

    async def list_reports(self, page: int = 1, size: int = 20, user_id: int | None = None):
        logged_in_doctor_id = None
        if user_id is not None:
            logged_in_doctor_id = await self._get_doctor_id(user_id)

        skip = (page - 1) * size
        items = await self.repo.list_records(skip=skip, limit=size, doctor_id=logged_in_doctor_id)
        total = await self.repo.count_records(doctor_id=logged_in_doctor_id)

        res_list = []
        for item in items:
            response_data = MedicalRecordResponse.model_validate(item)
            diagnosis_record = await self.repo.get_diagnosis(item.patient_id)
            if diagnosis_record:
                response_data.symptoms = diagnosis_record.symptoms
            res_list.append(response_data)

        return build_paginated_result(
            res_list,
            total,
            page,
            size,
        )

    async def get_report_by_id(self, record_id: int, user_id: int | None = None) -> MedicalRecordResponse:
        record = await self.repo.get_record_by_id(record_id)
        if not record:
            raise NotFoundException("Medical record not found")

        if user_id is not None:
            logged_in_doctor_id = await self._get_doctor_id(user_id)
            if logged_in_doctor_id is not None and record.doctor_id != logged_in_doctor_id:
                raise ForbiddenException("You can only view your own patients' medical records")

        response_data = MedicalRecordResponse.model_validate(record)
        diagnosis_record = await self.repo.get_diagnosis(record.patient_id)
        if diagnosis_record:
            response_data.symptoms = diagnosis_record.symptoms
        return response_data

    async def update_report(
        self,
        record_id: int,
        report_title: str | None,
        report_type: str | None,
        diagnosis: str | None,
        notes: str | None,
        file: UploadFile | None,
        user_id: int,
    ) -> MedicalRecordResponse:
        record = await self.repo.get_record_by_id(record_id)
        if not record:
            raise NotFoundException("Medical record not found")

        logged_in_doctor_id = await self._get_doctor_id(user_id)
        if logged_in_doctor_id is not None and record.doctor_id != logged_in_doctor_id:
            raise ForbiddenException("You can only modify your own medical records")

        if report_title is not None:
            record.report_title = report_title or "Medical Record"
        if report_type is not None:
            record.report_type = report_type or "General"
        if diagnosis is not None:
            record.diagnosis = diagnosis
        if notes is not None:
            record.notes = notes

        if file:
            allowed_types = {"application/pdf", "image/jpeg", "image/png"}
            if file.content_type not in allowed_types:
                raise BadRequestException("Only PDF, JPG and PNG files are allowed")
            file_path = await save_upload_file(file, settings.UPLOAD_DIR)
            record.file_path = file_path
            record.file_name = file.filename or "report"
            record.file_type = file.content_type

        record = await self.repo.update_record(record)
        await self.audit_repo.create("update", "doctor_medical_records", user_id=user_id, resource_id=str(record.id))

        response_data = MedicalRecordResponse.model_validate(record)
        diagnosis_record = await self.repo.get_diagnosis(record.patient_id)
        if diagnosis_record:
            response_data.symptoms = diagnosis_record.symptoms
        return response_data

    async def delete_report(self, record_id: int, user_id: int) -> None:
        record = await self.repo.get_record_by_id(record_id)
        if not record:
            raise NotFoundException("Medical record not found")

        logged_in_doctor_id = await self._get_doctor_id(user_id)
        if logged_in_doctor_id is not None and record.doctor_id != logged_in_doctor_id:
            raise ForbiddenException("You can only delete your own medical records")

        await self.repo.delete_record(record)
        await self.audit_repo.create("delete", "doctor_medical_records", user_id=user_id, resource_id=str(record.id))

    async def get_report_file(self, record_id: int, user_id: int | None = None):
        record = await self.repo.get_record_by_id(record_id)

        if not record:
            raise NotFoundException("Medical record not found")

        if user_id is not None:
            logged_in_doctor_id = await self._get_doctor_id(user_id)
            if logged_in_doctor_id is not None and record.doctor_id != logged_in_doctor_id:
                raise ForbiddenException("You can only access your own patients' medical record files")

        path = Path(record.file_path)
        if not path.exists():
            raise NotFoundException("Report file not found")

        return record

    async def get_diagnosis(self, patient_id: int) -> DiagnosisResponse:
        patient = await self.patient_repo.get_by_id(patient_id)

        if not patient:
            raise NotFoundException("Patient not found")

        diagnosis = await self.repo.get_diagnosis(patient_id)

        if not diagnosis:
            raise NotFoundException("Diagnosis not found")

        return DiagnosisResponse.model_validate(diagnosis)

    async def update_diagnosis(
        self,
        patient_id: int,
        data: DiagnosisUpdate,
        user_id: int,
    ) -> DiagnosisResponse:
        patient = await self.patient_repo.get_by_id(patient_id)

        if not patient:
            raise NotFoundException("Patient not found")

        doctor_id = await self._get_doctor_id(user_id)
        diagnosis = await self.repo.get_diagnosis(patient_id)

        if not diagnosis:
            diagnosis = PatientDiagnosis(
                patient_id=patient_id,
                doctor_id=doctor_id,
                **data.model_dump(),
            )
            diagnosis = await self.repo.save_diagnosis(diagnosis)
        else:
            diagnosis.diagnosis = data.diagnosis
            diagnosis.symptoms = data.symptoms
            diagnosis.notes = data.notes
            diagnosis.doctor_id = doctor_id
            diagnosis = await self.repo.update_diagnosis(diagnosis)

        return DiagnosisResponse.model_validate(diagnosis)

    async def list_treatment_notes(
        self,
        patient_id: int,
        page: int = 1,
        size: int = 20,
    ):
        patient = await self.patient_repo.get_by_id(patient_id)

        if not patient:
            raise NotFoundException("Patient not found")

        skip = (page - 1) * size

        notes = await self.repo.list_treatment_notes(
            patient_id=patient_id,
            skip=skip,
            limit=size,
        )
        total = await self.repo.count_treatment_notes(patient_id)

        return build_paginated_result(
            [TreatmentNoteResponse.model_validate(note) for note in notes],
            total,
            page,
            size,
        )

    async def add_treatment_note(
        self,
        patient_id: int,
        data: TreatmentNoteCreate,
        user_id: int,
    ) -> TreatmentNoteResponse:
        patient = await self.patient_repo.get_by_id(patient_id)

        if not patient:
            raise NotFoundException("Patient not found")

        doctor_id = await self._get_doctor_id(user_id)

        note = TreatmentNote(
            patient_id=patient_id,
            doctor_id=doctor_id,
            **data.model_dump(),
        )

        note = await self.repo.add_treatment_note(note)
        return TreatmentNoteResponse.model_validate(note)