from pathlib import Path

from fastapi import UploadFile

from app.core.config import settings
from app.core.exceptions import BadRequestException, NotFoundException
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

    async def _get_doctor_id(self, user_id: int) -> int | None:
        doctor = await self.repo.get_doctor_by_user_id(user_id)
        return doctor.id if doctor else None

    async def upload_report(
        self,
        patient_id: int,
        patient_name: str,
        report_title: str,
        report_type: str,
        diagnosis: str | None,
        notes: str | None,
        file: UploadFile,
        user_id: int,
    ) -> MedicalRecordResponse:
        patient = await self.patient_repo.get_by_id(patient_id)
        if not patient:
            raise NotFoundException("Patient not found")

        # Check if patient name matches the database record
        db_full_name = f"{patient.first_name} {patient.last_name}".strip()
        if patient_name.strip().lower() != db_full_name.lower():
            raise BadRequestException(
                f"Provided patient name '{patient_name}' does not match the actual patient record '{db_full_name}'"
            )

        allowed_types = {"application/pdf", "image/jpeg", "image/png"}
        if file.content_type not in allowed_types:
            raise BadRequestException("Only PDF, JPG and PNG files are allowed")

        doctor_id = await self._get_doctor_id(user_id)

        file_path = await save_upload_file(file, settings.UPLOAD_DIR)

        record = DoctorMedicalRecord(
            patient_id=patient_id,
            doctor_id=doctor_id,
            patient_name=patient_name,
            report_title=report_title,
            report_type=report_type,
            diagnosis=diagnosis,
            notes=notes,
            file_path=file_path,
            file_name=file.filename or "report",
            file_type=file.content_type,
        )

        record = await self.repo.create_record(record)
        return MedicalRecordResponse.model_validate(record)

    async def list_reports(self, page: int = 1, size: int = 20):
        skip = (page - 1) * size
        items = await self.repo.list_records(skip=skip, limit=size)
        total = await self.repo.count_records()

        return build_paginated_result(
            [MedicalRecordResponse.model_validate(item) for item in items],
            total,
            page,
            size,
        )

    async def get_report_file(self, record_id: int):
        record = await self.repo.get_record_by_id(record_id)

        if not record:
            raise NotFoundException("Medical record not found")

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