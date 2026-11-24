import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import UploadFile
import io

from app.core.exceptions import NotFoundException, BadRequestException, ForbiddenException
from app.models.clinical_record_model import ClinicalRecord
from app.models.patient_model import Patient, PatientDocument
from app.models.doctor_model import Doctor
from app.models.user_model import User
from app.schemas.clinical_record_schema import ClinicalRecordCreate, ClinicalRecordUpdate
from app.services.clinical_record_service import ClinicalRecordService
from app.services.patient_service import PatientService


@pytest.fixture
def mock_db():
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.delete = AsyncMock()
    session.commit = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_clinical_record_create_persists_hospital_id(mock_db):
    service = ClinicalRecordService(mock_db)

    # Patient and doctor belong to Hospital 1
    now = datetime.now(timezone.utc)
    patient = Patient(
        id=101, hospital_id=1, patient_code="PAT-101", first_name="Amit", last_name="Sharma",
        status="active", created_at=now, updated_at=now
    )
    doctor = Doctor(id=201, hospital_id=1, first_name="Raj", last_name="Verma")

    service.patient_repo.get_by_id = AsyncMock(return_value=patient)
    service.doctor_repo.get_by_id = AsyncMock(return_value=doctor)
    service.appointment_repo.count_all = AsyncMock(return_value=1)

    # Mock repository create returning created record
    now = datetime.now(timezone.utc)
    created_rec = ClinicalRecord(
        id=1, hospital_id=1, patient_id=101, doctor_id=201, symptoms="Fever", diagnosis="Flu",
        created_at=now, updated_at=now
    )
    created_rec.patient = patient
    created_rec.doctor = doctor
    service.record_repo.create = AsyncMock(return_value=created_rec)
    service.audit_repo.create = AsyncMock()

    current_user = MagicMock(spec=User)
    current_user.id = 5
    current_user.hospital_id = 1
    current_user.role = MagicMock()
    current_user.role.name = "Doctor"

    data = ClinicalRecordCreate(patient_id=101, doctor_id=201, symptoms="Fever", diagnosis="Flu")
    resp = await service.create_record(data, user_id=5, current_user=current_user)

    assert resp.id == 1
    assert resp.patient_id == 101
    assert resp.doctor_id == 201
    assert resp.hospital_id == 1

    # Verify that record was created with hospital_id=1
    create_args = service.record_repo.create.call_args[0][0]
    assert create_args.hospital_id == 1


@pytest.mark.asyncio
async def test_clinical_record_cross_hospital_patient_rejected(mock_db):
    service = ClinicalRecordService(mock_db)

    # Patient in Hospital 2, Doctor in Hospital 1
    patient = Patient(id=102, hospital_id=2, first_name="Other", last_name="Patient")
    doctor = Doctor(id=201, hospital_id=1, first_name="Raj", last_name="Verma")

    # Hospital 1 user cannot find patient from hospital 2
    service.patient_repo.get_by_id = AsyncMock(return_value=None)
    service.doctor_repo.get_by_id = AsyncMock(return_value=doctor)

    current_user = MagicMock(spec=User)
    current_user.id = 5
    current_user.hospital_id = 1
    current_user.role = MagicMock()
    current_user.role.name = "Doctor"

    data = ClinicalRecordCreate(patient_id=102, doctor_id=201, symptoms="Cough", diagnosis="Cold")
    with pytest.raises(NotFoundException):
        await service.create_record(data, user_id=5, current_user=current_user)


@pytest.mark.asyncio
async def test_clinical_record_cross_hospital_mismatch_rejected(mock_db):
    service = ClinicalRecordService(mock_db)

    # If super admin bypasses repo scoping, cross-hospital reference is still rejected
    patient = Patient(id=102, hospital_id=2, first_name="Other", last_name="Patient")
    doctor = Doctor(id=201, hospital_id=1, first_name="Raj", last_name="Verma")

    service.patient_repo.get_by_id = AsyncMock(return_value=patient)
    service.doctor_repo.get_by_id = AsyncMock(return_value=doctor)

    current_user = MagicMock(spec=User)
    current_user.id = 1
    current_user.hospital_id = None
    current_user.active_hospital_id = 1
    current_user.role = MagicMock()
    current_user.role.name = "Super Admin"

    data = ClinicalRecordCreate(patient_id=102, doctor_id=201, symptoms="Cough", diagnosis="Cold")
    with pytest.raises(BadRequestException) as exc_info:
        await service.create_record(data, user_id=1, current_user=current_user, hospital_id=1)
    assert "Cross-hospital reference" in str(exc_info.value)


@pytest.mark.asyncio
async def test_clinical_record_read_tenant_isolation(mock_db):
    service = ClinicalRecordService(mock_db)

    # Record belongs to Hospital 1. User from Hospital 2 queries it.
    service.record_repo.get_by_id = AsyncMock(return_value=None)

    current_user = MagicMock(spec=User)
    current_user.id = 10
    current_user.hospital_id = 2
    current_user.role = MagicMock()
    current_user.role.name = "Doctor"

    with pytest.raises(NotFoundException):
        await service.get_record(record_id=1, current_user=current_user)

    # Verify that hospital_id=2 was passed to repository
    service.record_repo.get_by_id.assert_called_with(1, hospital_id=2)


@pytest.mark.asyncio
async def test_clinical_record_update_tenant_isolation(mock_db):
    service = ClinicalRecordService(mock_db)

    # Record belongs to Hospital 1. User from Hospital 2 attempts update.
    service.record_repo.get_by_id = AsyncMock(return_value=None)

    current_user = MagicMock(spec=User)
    current_user.id = 10
    current_user.hospital_id = 2
    current_user.role = MagicMock()
    current_user.role.name = "Doctor"

    data = ClinicalRecordUpdate(diagnosis="Updated Diagnosis")
    with pytest.raises(NotFoundException):
        await service.update_record(record_id=1, data=data, user_id=10, current_user=current_user)

    service.record_repo.get_by_id.assert_called_with(1, hospital_id=2)


@pytest.mark.asyncio
async def test_clinical_record_delete_tenant_isolation(mock_db):
    service = ClinicalRecordService(mock_db)

    service.record_repo.get_by_id = AsyncMock(return_value=None)

    current_user = MagicMock(spec=User)
    current_user.id = 10
    current_user.hospital_id = 2
    current_user.role = MagicMock()
    current_user.role.name = "Doctor"

    with pytest.raises(NotFoundException):
        await service.delete_record(record_id=1, user_id=10, current_user=current_user)

    service.record_repo.get_by_id.assert_called_with(1, hospital_id=2)


@pytest.mark.asyncio
async def test_patient_document_upload_persists_hospital_id(mock_db):
    service = PatientService(mock_db)

    now = datetime.now(timezone.utc)
    patient = Patient(
        id=101, hospital_id=1, patient_code="PAT-101", first_name="Amit", last_name="Sharma",
        status="active", created_at=now, updated_at=now
    )
    service.repo.get_by_id = AsyncMock(return_value=patient)
    service.repo.get_patient_lab_history = AsyncMock(return_value=[])
    service.audit_repo.create = AsyncMock()

    now = datetime.now(timezone.utc)
    created_doc = PatientDocument(
        id=50, hospital_id=1, patient_id=101, document_name="test.pdf",
        document_type="Lab Report", file_path="uploads/test.pdf",
        created_at=now
    )
    service.repo.add_document = AsyncMock(return_value=created_doc)

    current_user = MagicMock(spec=User)
    current_user.id = 5
    current_user.hospital_id = 1
    current_user.role = MagicMock()
    current_user.role.name = "Doctor"

    fake_file = UploadFile(filename="test.pdf", file=io.BytesIO(b"%PDF-1.4 dummy content"))

    with patch("app.services.patient_service.save_upload_file", AsyncMock(return_value="uploads/test.pdf")):
        resp = await service.upload_document(
            patient_id=101, file=fake_file, document_type="Lab Report",
            user_id=5, current_user=current_user
        )

    assert resp.id == 50
    assert resp.hospital_id == 1
    assert resp.patient_id == 101

    # Verify doc created with hospital_id=1
    call_doc = service.repo.add_document.call_args[0][0]
    assert call_doc.hospital_id == 1


@pytest.mark.asyncio
async def test_patient_document_download_tenant_isolation(mock_db):
    service = PatientService(mock_db)

    # Patient in Hospital 1, queried by user from Hospital 2 -> get_by_id raises NotFound
    service.repo.get_by_id = AsyncMock(return_value=None)

    current_user = MagicMock(spec=User)
    current_user.id = 20
    current_user.hospital_id = 2
    current_user.role = MagicMock()
    current_user.role.name = "Doctor"

    with pytest.raises(NotFoundException):
        await service.get_document(patient_id=101, document_id=50, current_user=current_user)
