from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundException, ConflictException
from app.models.patient_model import FamilyMember, Patient, PatientDocument
from app.repositories.audit_repository import AuditRepository
from app.repositories.patient_repository import PatientRepository
from app.schemas.patient_schema import (
    FamilyMemberCreate,
    FamilyMemberResponse,
    PatientCreate,
    PatientDocumentResponse,
    PatientResponse,
    PatientUpdate,
)
from app.utils.file_upload import save_upload_file
from app.utils.helpers import generate_mrn
from app.utils.pagination import build_paginated_result


class PatientService:
    def __init__(self, db: AsyncSession):
        self.repo = PatientRepository(db)
        self.audit_repo = AuditRepository(db)

    async def list_patients(self, page: int = 1, size: int = 20, sort_by: str = "created_at", sort_order: str = "desc"):
        skip = (page - 1) * size
        items = await self.repo.list_all(skip=skip, limit=size, sort_by=sort_by, sort_order=sort_order)
        total = await self.repo.count_all()
        return build_paginated_result(
            [PatientResponse.model_validate(p) for p in items], total, page, size
        )

    async def get_by_id(self, patient_id: int) -> PatientResponse:
        patient = await self.repo.get_by_id(patient_id)
        if not patient:
            raise NotFoundException("Patient not found")
        return PatientResponse.model_validate(patient)

    async def create(self, data: PatientCreate, user_id: int) -> PatientResponse:
        if data.phone:
            existing_phone = await self.repo.get_by_phone(data.phone)
            if existing_phone:
                raise ConflictException("Patient with this phone number already exists")

        if data.email:
            existing_email = await self.repo.get_by_email(data.email)
            if existing_email:
                raise ConflictException("Patient with this email already exists")

        patient = Patient(patient_code=generate_mrn(), **data.model_dump())
        patient = await self.repo.create(patient)
        await self.audit_repo.create("create", "patients", user_id=user_id, resource_id=str(patient.id))
        return PatientResponse.model_validate(patient)

    async def update(self, patient_id: int, data: PatientUpdate, user_id: int) -> PatientResponse:
        patient = await self.repo.get_by_id(patient_id)
        if not patient:
            raise NotFoundException("Patient not found")

        if data.phone is not None and data.phone != patient.phone:
            existing_phone = await self.repo.get_by_phone(data.phone)
            if existing_phone:
                raise ConflictException("Patient with this phone number already exists")

        if data.email is not None and data.email != patient.email:
            existing_email = await self.repo.get_by_email(data.email)
            if existing_email:
                raise ConflictException("Patient with this email already exists")

        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(patient, key, value)
        patient = await self.repo.update(patient)
        await self.audit_repo.create("update", "patients", user_id=user_id, resource_id=str(patient.id))
        return PatientResponse.model_validate(patient)

    async def delete(self, patient_id: int, user_id: int) -> None:
        patient = await self.repo.get_by_id(patient_id)
        if not patient:
            raise NotFoundException("Patient not found")
        await self.repo.soft_delete(patient)
        if patient.user_id:
            from app.models.user_model import User
            user = await self.db.get(User, patient.user_id)
            if user:
                user.is_active = False
        await self.audit_repo.create("delete", "patients", user_id=user_id, resource_id=str(patient.id))

    async def search(self, q: str, page: int = 1, size: int = 20):
        skip = (page - 1) * size
        items = await self.repo.search(q, skip=skip, limit=size)
        total = await self.repo.count_search(q)
        return build_paginated_result(
            [PatientResponse.model_validate(p) for p in items], total, page, size
        )

    async def filter_patients(
        self,
        gender: str | None = None,
        blood_group: str | None = None,
        city: str | None = None,
        state: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ):
        skip = (page - 1) * size
        items = await self.repo.filter_patients(
            gender=gender, blood_group=blood_group, city=city, state=state, status=status,
            skip=skip, limit=size,
        )
        total = await self.repo.count_filter(
            gender=gender, blood_group=blood_group, city=city, state=state, status=status
        )
        return build_paginated_result(
            [PatientResponse.model_validate(p) for p in items], total, page, size
        )

    async def get_appointments(self, patient_id: int):
        await self.get_by_id(patient_id)
        from app.schemas.appointment_schema import AppointmentResponse

        appointments = await self.repo.get_appointments(patient_id)
        return [AppointmentResponse.model_validate(a) for a in appointments]

    async def get_history(self, patient_id: int):
        return await self.get_appointments(patient_id)

    async def add_family_member(self, patient_id: int, data: FamilyMemberCreate, user_id: int) -> FamilyMemberResponse:
        await self.get_by_id(patient_id)
        member = FamilyMember(patient_id=patient_id, **data.model_dump())
        member = await self.repo.add_family_member(member)
        await self.audit_repo.create("create", "family_members", user_id=user_id, resource_id=str(member.id))
        return FamilyMemberResponse.model_validate(member)

    async def list_family_members(self, patient_id: int) -> list[FamilyMemberResponse]:
        await self.get_by_id(patient_id)
        members = await self.repo.list_family_members(patient_id)
        return [FamilyMemberResponse.model_validate(m) for m in members]

    async def upload_document(
        self, patient_id: int, file: UploadFile, document_type: str, user_id: int
    ) -> PatientDocumentResponse:
        await self.get_by_id(patient_id)
        file_path = await save_upload_file(file, settings.UPLOAD_DIR)
        doc = PatientDocument(
            patient_id=patient_id,
            document_name=file.filename or "document",
            document_type=document_type,
            file_path=file_path,
            uploaded_by=user_id,
        )
        doc = await self.repo.add_document(doc)
        await self.audit_repo.create("upload", "patient_documents", user_id=user_id, resource_id=str(doc.id))
        return PatientDocumentResponse.model_validate(doc)

    async def list_documents(self, patient_id: int) -> list[PatientDocumentResponse]:
        await self.get_by_id(patient_id)
        docs = await self.repo.list_documents(patient_id)
        return [PatientDocumentResponse.model_validate(d) for d in docs]
