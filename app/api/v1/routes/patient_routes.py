from typing import List, Optional
from datetime import date

from fastapi import APIRouter, Depends, File, UploadFile, Query, Form, Request, HTTPException
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
    PatientCreateResponse,
    PatientUpdate,
    PatientFilterQuery,
    PatientDocumentCreate,
    PatientListResponse,
)
from app.schemas.clinical_record_schema import ClinicalRecordResponse
from app.services.patient_service import PatientService
from app.utils.pagination import PaginatedResult

router = APIRouter()


@router.post(
    "",
    response_model=APIResponse[PatientCreateResponse],
    status_code=201,
    openapi_extra={
        "requestBody": {
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "required": ["first_name", "last_name", "diagnosis"]
                    }
                }
            }
        }
    }
)
async def create_patient(
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
    first_name: Optional[str] = Form(None),
    last_name: Optional[str] = Form(None),
    gender: Optional[str] = Form(None),
    dob: Optional[date] = Form(None),
    blood_group: Optional[str] = Form(None),
    marital_status: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    address: Optional[str] = Form(None),
    city: Optional[str] = Form(None),
    state: Optional[str] = Form(None),
    pincode: Optional[str] = Form(None),
    emergency_contact_name: Optional[str] = Form(None),
    emergency_contact_number: Optional[str] = Form(None),
    allergies: Optional[str] = Form(None),
    medical_history: Optional[str] = Form(None),
    chronic_disease: Optional[str] = Form(None),
    diagnosis: Optional[str] = Form(None),
    insurance_provider: Optional[str] = Form(None),
    insurance_number: Optional[str] = Form(None),
    status: Optional[str] = Form(None),
    preferred_language: Optional[str] = Form(None),
    consent_form: Optional[UploadFile] = File(None),
    _: User = Depends(require_permission("patients", "create")),
):
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            body = await request.json()
            patient_data = PatientCreate(**body)
        except ValidationError as e:
            raise RequestValidationError(e.errors())
        except Exception as e:
            raise HTTPException(
                status_code=422,
                detail=[{"loc": ["body"], "msg": f"Invalid JSON payload: {str(e)}", "type": "json_invalid"}]
            )
        consent_file = None
    else:
        # Check required fields manually for Form/Multipart request
        missing_fields = []
        if not first_name:
            missing_fields.append({"type": "missing", "loc": ["body", "first_name"], "msg": "Field required", "input": None})
        if not last_name:
            missing_fields.append({"type": "missing", "loc": ["body", "last_name"], "msg": "Field required", "input": None})
        if not diagnosis:
            missing_fields.append({"type": "missing", "loc": ["body", "diagnosis"], "msg": "Field required", "input": None})
            
        if missing_fields:
            raise HTTPException(status_code=422, detail=missing_fields)

        try:
            patient_data = PatientCreate(
                first_name=first_name,
                last_name=last_name,
                gender=gender,
                dob=dob,
                blood_group=blood_group,
                marital_status=marital_status,
                phone=phone,
                email=email,
                address=address,
                city=city,
                state=state,
                pincode=pincode,
                emergency_contact_name=emergency_contact_name,
                emergency_contact_number=emergency_contact_number,
                allergies=allergies,
                medical_history=medical_history,
                chronic_disease=chronic_disease,
                diagnosis=diagnosis,
                insurance_provider=insurance_provider,
                insurance_number=insurance_number,
                status=status or "active",
                preferred_language=preferred_language,
            )
        except ValidationError as e:
            raise RequestValidationError(e.errors())
        consent_file = consent_form

    patient = await PatientService(db).create(patient_data, current_user.id, consent_file=consent_file)
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
        current_user=current_user,
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
    result = await PatientService(db).search(q, page=page, size=size, current_user=current_user)
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
        current_user=current_user,
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


@router.get("/documents/download")
async def download_document(
    db: DbSession,
    current_user: CurrentUser,
    patient_id: Optional[int] = None,
    document_id: Optional[int] = None,
    _: User = Depends(require_permission("patients", "read")),
):
    import os
    from fastapi.responses import FileResponse
    from app.core.exceptions import NotFoundException
    
    if patient_id is None or document_id is None:
        return APIResponse(
            success=True,
            message="No document identifiers provided",
            data=None
        )
        
    doc = await PatientService(db).get_document(patient_id, document_id)
    if not os.path.exists(doc.file_path):
        raise NotFoundException("Document file not found on disk")
        
    return FileResponse(
        path=doc.file_path,
        filename=doc.document_name,
        media_type="application/octet-stream"
    )


@router.get("/documents/view")
async def view_document(
    db: DbSession,
    current_user: CurrentUser,
    patient_id: Optional[int] = None,
    document_id: Optional[int] = None,
    _: User = Depends(require_permission("patients", "read")),
):
    import os
    import mimetypes
    from fastapi.responses import FileResponse
    from app.core.exceptions import NotFoundException
    
    if patient_id is None or document_id is None:
        return APIResponse(
            success=True,
            message="No document identifiers provided",
            data=None
        )
        
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


@router.delete("/{patient_id}/family-members/{member_id}", response_model=APIResponse[MessageResponse])
async def delete_family_member(
    patient_id: int,
    member_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("patients", "update")),
):
    await PatientService(db).delete_family_member(patient_id, member_id, current_user.id)
    return APIResponse(message="Family member deleted successfully", data=MessageResponse(message="Deleted"))


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
