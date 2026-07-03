from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.doctor_model import Doctor
from app.models.doctor_medical_record_model import (
    DoctorMedicalRecord,
    PatientDiagnosis,
    TreatmentNote,
)


class DoctorMedicalRecordRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_doctor_by_user_id(self, user_id: int) -> Doctor | None:
        result = await self.db.execute(
            select(Doctor).where(
                Doctor.user_id == user_id,
                Doctor.is_deleted == False,
            )
        )
        return result.scalar_one_or_none()

    async def create_record(self, record: DoctorMedicalRecord) -> DoctorMedicalRecord:
        self.db.add(record)
        await self.db.flush()
        await self.db.refresh(record)
        return record

    async def list_records(
        self,
        skip: int = 0,
        limit: int = 20,
    ) -> list[DoctorMedicalRecord]:
        result = await self.db.execute(
            select(DoctorMedicalRecord)
            .order_by(DoctorMedicalRecord.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_records(self) -> int:
        return await self.db.scalar(
            select(func.count()).select_from(DoctorMedicalRecord)
        ) or 0

    async def get_record_by_id(
        self,
        record_id: int,
    ) -> DoctorMedicalRecord | None:
        result = await self.db.execute(
            select(DoctorMedicalRecord).where(
                DoctorMedicalRecord.id == record_id
            )
        )
        return result.scalar_one_or_none()

    async def get_diagnosis(
        self,
        patient_id: int,
    ) -> PatientDiagnosis | None:
        result = await self.db.execute(
            select(PatientDiagnosis).where(
                PatientDiagnosis.patient_id == patient_id
            )
        )
        return result.scalar_one_or_none()

    async def save_diagnosis(
        self,
        diagnosis: PatientDiagnosis,
    ) -> PatientDiagnosis:
        self.db.add(diagnosis)
        await self.db.flush()
        await self.db.refresh(diagnosis)
        return diagnosis

    async def update_diagnosis(
        self,
        diagnosis: PatientDiagnosis,
    ) -> PatientDiagnosis:
        await self.db.flush()
        await self.db.refresh(diagnosis)
        return diagnosis

    async def add_treatment_note(
        self,
        note: TreatmentNote,
    ) -> TreatmentNote:
        self.db.add(note)
        await self.db.flush()
        await self.db.refresh(note)
        return note

    async def list_treatment_notes(
        self,
        patient_id: int,
        skip: int = 0,
        limit: int = 20,
    ) -> list[TreatmentNote]:
        result = await self.db.execute(
            select(TreatmentNote)
            .where(TreatmentNote.patient_id == patient_id)
            .order_by(TreatmentNote.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_treatment_notes(
        self,
        patient_id: int,
    ) -> int:
        return await self.db.scalar(
            select(func.count())
            .select_from(TreatmentNote)
            .where(TreatmentNote.patient_id == patient_id)
        ) or 0

    async def update_record(self, record: DoctorMedicalRecord) -> DoctorMedicalRecord:
        await self.db.flush()
        await self.db.refresh(record)
        return record

    async def delete_record(self, record: DoctorMedicalRecord) -> None:
        await self.db.delete(record)
        await self.db.flush()