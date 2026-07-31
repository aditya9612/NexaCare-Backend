from typing import List
from datetime import date

from fastapi import APIRouter, Depends, File, UploadFile, Query, Form, Request
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.models.user_model import User
from app.schemas.common_schema import APIResponse, MessageResponse
from app.schemas.patient_schema import (
    FamilyMemberCreate,
    FamilyMemberResponse,
    PatientCreate,
    PatientDocumentResponse,
    PatientResponse,
    PatientUpdate,
    PatientFilterQuery,
    PatientDocumentCreate,
    PatientListResponse,
)
from app.schemas.clinical_record_schema import ClinicalRecordResponse
from app.services.patient_service import PatientService
from app.utils.pagination import PaginatedResult

router = APIRouter()


@router.post("", response_model=APIResponse[PatientResponse], status_code=201)
async def create_patient(
    data: PatientCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("patients", "create")),
):
    patient = await PatientService(db).create(data, current_user.id)
    return APIResponse(message="Patient created", data=patient)


@router.get("", response_model=APIResponse[PatientListResponse])
async def list_patients(
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    start_date: date | None = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: date | None = Query(None, description="End date (YYYY-MM-DD)"),
    _: User = Depends(require_permission("patients", "read")),
):
    result = await PatientService(db).list_patients(
        page=page,
        size=size,
        sort_by=sort_by,
        sort_order=sort_order,
        start_date=start_date,
        end_date=end_date,
    )
    return APIResponse(message="Patients retrieved", data=result)


@router.get("/search", response_model=APIResponse[PaginatedResult[PatientResponse]])
async def search_patients(
    q: str,
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    _: User = Depends(require_permission("patients", "read")),
):
    result = await PatientService(db).search(q, page=page, size=size)
    return APIResponse(message="Search results", data=result)


def get_patient_filter_query(
    gender: str | None = None,
    blood_group: str | None = None,
    city: str | None = None,
    state: str | None = None,
    status: str | None = None,
    page: int = 1,
    size: int = 20,
) -> PatientFilterQuery:
    try:
        return PatientFilterQuery(
            gender=gender,
            blood_group=blood_group,
            city=city,
            state=state,
            status=status,
            page=page,
            size=size,
        )
    except ValidationError as e:
        raise RequestValidationError(e.errors())


@router.get("/filter", response_model=APIResponse[PaginatedResult[PatientResponse]])
async def filter_patients(
    db: DbSession,
    current_user: CurrentUser,
    params: PatientFilterQuery = Depends(get_patient_filter_query),
    _: User = Depends(require_permission("patients", "read")),
):
    result = await PatientService(db).filter_patients(
        gender=params.gender,
        blood_group=params.blood_group,
        city=params.city,
        state=params.state,
        status=params.status,
        page=params.page,
        size=params.size,
    )
    return APIResponse(message="Filtered patients", data=result)


@router.get("/{patient_id}", response_model=APIResponse[PatientResponse])
async def get_patient(
    patient_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("patients", "read")),
):
    patient = await PatientService(db).get_by_id(patient_id)
    return APIResponse(message="Patient retrieved", data=patient)


@router.put("/{patient_id}", response_model=APIResponse[PatientResponse])
async def update_patient(
    patient_id: int,
    data: PatientUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("patients", "update")),
):
    patient = await PatientService(db).update(patient_id, data, current_user.id)
    return APIResponse(message="Patient updated", data=patient)


@router.delete("/{patient_id}", response_model=APIResponse[MessageResponse])
async def delete_patient(
    patient_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("patients", "delete")),
):
    await PatientService(db).delete(patient_id, current_user.id)
    return APIResponse(message="Patient deleted", data=MessageResponse(message="Soft deleted"))


@router.get("/{patient_id}/appointments", response_model=APIResponse[List])
async def patient_appointments(
    patient_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("patients", "read")),
):
    from app.schemas.appointment_schema import AppointmentResponse

    appointments = await PatientService(db).get_appointments(patient_id)
    return APIResponse(message="Appointments retrieved", data=appointments)


@router.get("/{patient_id}/history", response_model=APIResponse[List])
async def patient_history(
    patient_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("patients", "read")),
):
    history = await PatientService(db).get_history(patient_id)
    return APIResponse(message="Visit history retrieved", data=history)


@router.post("/{patient_id}/documents", response_model=APIResponse[PatientDocumentResponse], status_code=201)
async def upload_document(
    patient_id: int,
    db: DbSession,
    current_user: CurrentUser,
    request: Request,
    file: UploadFile = File(...),
    document_type: str = Form("general"),
    _: User = Depends(require_permission("patients", "update")),
):
    # Extract raw value from form to distinguish between omitted and explicitly empty/whitespace values
    form_data = await request.form()
    raw_document_type = form_data.get("document_type")
    
    val_to_check = raw_document_type if raw_document_type is not None else "General"
    
    try:
        validated = PatientDocumentCreate(document_type=val_to_check)
        document_type = validated.document_type
    except ValidationError as e:
        raise RequestValidationError(e.errors())

    doc = await PatientService(db).upload_document(patient_id, file, document_type, current_user.id)
    return APIResponse(message="Document uploaded", data=doc)


@router.get("/{patient_id}/documents", response_model=APIResponse[List[PatientDocumentResponse]])
async def list_documents(
    patient_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("patients", "read")),
):
    docs = await PatientService(db).list_documents(patient_id)
    return APIResponse(message="Documents retrieved", data=docs)


@router.get("/{patient_id}/documents/{document_id}/download")
async def download_document(
    patient_id: int,
    document_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("patients", "read")),
):
    import os
    from fastapi.responses import FileResponse
    from app.core.exceptions import NotFoundException
    
    doc = await PatientService(db).get_document(patient_id, document_id)
    if not os.path.exists(doc.file_path):
        raise NotFoundException("Document file not found on disk")
        
    return FileResponse(
        path=doc.file_path,
        filename=doc.document_name,
        media_type="application/octet-stream"
    )


@router.get("/{patient_id}/documents/{document_id}/view")
async def view_document(
    patient_id: int,
    document_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("patients", "read")),
):
    import os
    import mimetypes
    from fastapi.responses import FileResponse
    from app.core.exceptions import NotFoundException
    
    doc = await PatientService(db).get_document(patient_id, document_id)
    if not os.path.exists(doc.file_path):
        raise NotFoundException("Document file not found on disk")
        
    mime_type, _ = mimetypes.guess_type(doc.file_path)
    if not mime_type:
        mime_type = "application/octet-stream"
        
    return FileResponse(
        path=doc.file_path,
        media_type=mime_type,
        content_disposition_type="inline"
    )



@router.delete("/{patient_id}/documents/{document_id}", response_model=APIResponse[MessageResponse])
async def delete_document(
    patient_id: int,
    document_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("patients", "update")),
):
    await PatientService(db).delete_document(patient_id, document_id, current_user.id)
    return APIResponse(message="Document deleted successfully", data=MessageResponse(message="Deleted"))


@router.post("/{patient_id}/family-members", response_model=APIResponse[FamilyMemberResponse], status_code=201)
async def add_family_member(
    patient_id: int,
    data: FamilyMemberCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("patients", "update")),
):
    member = await PatientService(db).add_family_member(patient_id, data, current_user.id)
    return APIResponse(message="Family member added", data=member)


@router.get("/{patient_id}/family-members", response_model=APIResponse[List[FamilyMemberResponse]])
async def list_family_members(
    patient_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("patients", "read")),
):
    members = await PatientService(db).list_family_members(patient_id)
    return APIResponse(message="Family members retrieved", data=members)


@router.get("/{patient_id}/clinical-records", response_model=APIResponse[PaginatedResult[ClinicalRecordResponse]])
async def list_patient_clinical_records(
    patient_id: int,
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: User = Depends(require_permission("patients", "read")),
):
    from app.services.clinical_record_service import ClinicalRecordService
    result = await ClinicalRecordService(db).list_records(
        page=page, size=size, patient_id=patient_id
    )
    return APIResponse(message="Records fetched successfully", data=result)
