from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, Body, Request
from fastapi.responses import FileResponse
from pydantic import ValidationError

from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.models.user_model import User
from app.schemas.appointment_schema import AppointmentResponse
from app.schemas.common_schema import APIResponse, MessageResponse
from app.schemas.doctor_schema import (
    DoctorCreate,
    DoctorOnboardCreate,
    DoctorOnboardResponse,
    DoctorResponse,
    DoctorScheduleCreate,
    DoctorScheduleResponse,
    DoctorUpdate,
)
from app.schemas.doctor_medical_record_schema import (
    DiagnosisResponse,
    DiagnosisUpdate,
    MedicalRecordResponse,
    TreatmentNoteCreate,
    TreatmentNoteResponse,
)
from app.services.doctor_service import DoctorService
from app.services.doctor_medical_record_service import DoctorMedicalRecordService
from app.utils.pagination import PaginatedResult
from app.schemas.clinical_record_schema import ClinicalRecordResponse
from fastapi import Query

router = APIRouter()


@router.post("", response_model=APIResponse[DoctorResponse], status_code=201)
async def create_doctor(
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
    first_name: Optional[str] = Form(None),
    last_name: Optional[str] = Form(None),
    specialization: Optional[str] = Form(None),
    license_number: Optional[str] = Form(None),
    qualification: Optional[str] = Form(None),
    experience: Optional[int] = Form(None),
    phone: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    department_id: Optional[int] = Form(None),
    consultation_fee: Optional[float] = Form(None),
    availability_status: Optional[str] = Form(None),
    bio: Optional[str] = Form(None),
    user_id: Optional[int] = Form(None),
    profile_image: Optional[UploadFile] = File(None),
    _: User = Depends(require_permission("doctors", "create")),
):
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            body = await request.json()
            doctor_data = DoctorCreate(**body)
        except ValidationError as e:
            raise HTTPException(status_code=422, detail=e.errors())
        except Exception as e:
            raise HTTPException(status_code=422, detail=[{"loc": ["body"], "msg": f"Invalid JSON payload: {str(e)}", "type": "json_invalid"}])
        image_file = None
    else:
        # Check required fields for Form/Multipart manually since we made them optional in function signature
        missing_fields = []
        if not first_name:
            missing_fields.append({"type": "missing", "loc": ["body", "first_name"], "msg": "Field required", "input": None})
        if not last_name:
            missing_fields.append({"type": "missing", "loc": ["body", "last_name"], "msg": "Field required", "input": None})
        if not specialization:
            missing_fields.append({"type": "missing", "loc": ["body", "specialization"], "msg": "Field required", "input": None})
        if not license_number:
            missing_fields.append({"type": "missing", "loc": ["body", "license_number"], "msg": "Field required", "input": None})
        
        if missing_fields:
            raise HTTPException(status_code=422, detail=missing_fields)
            
        try:
            doctor_data = DoctorCreate(
                first_name=first_name,
                last_name=last_name,
                specialization=specialization,
                qualification=qualification,
                experience=experience,
                phone=phone,
                email=email,
                department_id=department_id,
                consultation_fee=consultation_fee,
                license_number=license_number,
                availability_status=availability_status or "available",
                bio=bio,
                user_id=user_id,
                profile_image=None
            )
        except ValidationError as e:
            raise HTTPException(status_code=422, detail=e.errors())
        image_file = profile_image

    doctor_obj = await DoctorService(db).create(doctor_data, current_user.id, image_file=image_file)
    return APIResponse(message="Doctor created", data=doctor_obj)


@router.post("/onboard", response_model=APIResponse[DoctorOnboardResponse], status_code=201)
async def onboard_doctor(
    db: DbSession,
    current_user: CurrentUser,
    data: DoctorOnboardCreate,
    _: User = Depends(require_permission("doctors", "create")),
):
    """
    Create a doctor login account (`users`) and clinical profile (`doctors`) in one step.
    The new doctor can log in immediately with the provided email and password.
    """
    result = await DoctorService(db).onboard(data, current_user)
    return APIResponse(message="Doctor onboarded successfully", data=result)


@router.get("", response_model=APIResponse[PaginatedResult[DoctorResponse]])
async def list_doctors(
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    department_id: int | None = None,
    availability_status: str | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    _: User = Depends(require_permission("doctors", "read")),
):
    result = await DoctorService(db).list_doctors(
        page=page, size=size, department_id=department_id,
        availability_status=availability_status, sort_by=sort_by, sort_order=sort_order,
    )
    return APIResponse(message="Doctors retrieved", data=result)


@router.get("/search", response_model=APIResponse[PaginatedResult[DoctorResponse]])
async def search_doctors(
    q: str,
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    _: User = Depends(require_permission("doctors", "read")),
):
    result = await DoctorService(db).search(q, page=page, size=size)
    return APIResponse(message="Search results", data=result)


@router.get("/availability", response_model=APIResponse[List[DoctorResponse]])
async def list_available_doctors(
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("doctors", "read")),
):
    doctors = await DoctorService(db).list_available()
    return APIResponse(message="Available doctors", data=doctors)



# =========================
# Doctor Dashboard - Medical Records APIs
# =========================


@router.post(
    "/medical-records",
    response_model=APIResponse[MedicalRecordResponse],
    status_code=201,
)
async def upload_report(
    db: DbSession,
    current_user: CurrentUser,
    patient_id: int = Form(...),
    patient_name: str = Form(...),
    report_title: str = Form(...),
    report_type: str = Form(...),
    diagnosis: str | None = Form(None),
    notes: str | None = Form(None),
    file: UploadFile = File(...),
    _: User = Depends(require_permission("doctors", "create")),
):
    record = await DoctorMedicalRecordService(db).upload_report(
        patient_id=patient_id,
        patient_name=patient_name,
        report_title=report_title,
        report_type=report_type,
        diagnosis=diagnosis,
        notes=notes,
        file=file,
        user_id=current_user.id,
    )
    return APIResponse(message="Report uploaded", data=record)


@router.get(
    "/medical-records",
    response_model=APIResponse[PaginatedResult[MedicalRecordResponse]],
)
async def view_reports(
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    _: User = Depends(require_permission("doctors", "read")),
):
    result = await DoctorMedicalRecordService(db).list_reports(
        page=page,
        size=size,
    )
    return APIResponse(message="Medical records retrieved", data=result)


@router.get("/medical-records/{record_id}/download")
async def download_report(
    record_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("doctors", "read")),
):
    record = await DoctorMedicalRecordService(db).get_report_file(record_id)
    return FileResponse(
        path=record.file_path,
        filename=record.file_name,
        media_type=record.file_type or "application/octet-stream",
    )


@router.get(
    "/patients/{patient_id}/diagnosis",
    response_model=APIResponse[DiagnosisResponse],
)
async def get_diagnosis(
    patient_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("doctors", "read")),
):
    diagnosis = await DoctorMedicalRecordService(db).get_diagnosis(patient_id)
    return APIResponse(message="Diagnosis retrieved", data=diagnosis)


@router.put(
    "/patients/{patient_id}/diagnosis",
    response_model=APIResponse[DiagnosisResponse],
)
async def update_diagnosis(
    patient_id: int,
    data: DiagnosisUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("doctors", "update")),
):
    diagnosis = await DoctorMedicalRecordService(db).update_diagnosis(
        patient_id=patient_id,
        data=data,
        user_id=current_user.id,
    )
    return APIResponse(message="Diagnosis updated", data=diagnosis)


@router.get(
    "/patients/{patient_id}/treatment-notes",
    response_model=APIResponse[PaginatedResult[TreatmentNoteResponse]],
)
async def view_treatment_notes(
    patient_id: int,
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    _: User = Depends(require_permission("doctors", "read")),
):
    result = await DoctorMedicalRecordService(db).list_treatment_notes(
        patient_id=patient_id,
        page=page,
        size=size,
    )
    return APIResponse(message="Treatment notes retrieved", data=result)


@router.post(
    "/patients/{patient_id}/treatment-notes",
    response_model=APIResponse[TreatmentNoteResponse],
    status_code=201,
)
async def add_treatment_note(
    patient_id: int,
    data: TreatmentNoteCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("doctors", "create")),
):
    note = await DoctorMedicalRecordService(db).add_treatment_note(
        patient_id=patient_id,
        data=data,
        user_id=current_user.id,
    )
    return APIResponse(message="Treatment note added", data=note)

@router.get("/{doctor_id}", response_model=APIResponse[DoctorResponse])
async def get_doctor(
    doctor_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("doctors", "read")),
):
    doctor = await DoctorService(db).get_by_id(doctor_id)
    return APIResponse(message="Doctor retrieved", data=doctor)


@router.put("/{doctor_id}", response_model=APIResponse[DoctorResponse])
async def update_doctor(
    doctor_id: int,
    db: DbSession,
    current_user: CurrentUser,
    first_name: Optional[str] = Form(None),
    last_name: Optional[str] = Form(None),
    specialization: Optional[str] = Form(None),
    qualification: Optional[str] = Form(None),
    experience: Optional[int] = Form(None),
    phone: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    department: Optional[str] = Form(None),
    consultation_fee: Optional[float] = Form(None),
    license_number: Optional[str] = Form(None),
    availability_status: Optional[str] = Form(None),
    bio: Optional[str] = Form(None),
    profile_image: Optional[UploadFile] = File(None),
    _: User = Depends(require_permission("doctors", "update")),
):
    try:
        data = DoctorUpdate(
            first_name=first_name,
            last_name=last_name,
            specialization=specialization,
            qualification=qualification,
            experience=experience,
            phone=phone,
            email=email,
            department=department,
            consultation_fee=consultation_fee,
            license_number=license_number,
            availability_status=availability_status,
            bio=bio,
            profile_image=None,  # will be handled by service
        )
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())
    doctor = await DoctorService(db).update(doctor_id, data, current_user.id, image_file=profile_image)
    return APIResponse(message="Doctor updated", data=doctor)


@router.delete("/{doctor_id}", response_model=APIResponse[MessageResponse])
async def delete_doctor(
    doctor_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("doctors", "delete")),
):
    await DoctorService(db).delete(doctor_id, current_user.id)
    return APIResponse(message="Doctor deleted", data=MessageResponse(message="Soft deleted"))


@router.get("/{doctor_id}/appointments", response_model=APIResponse[List[AppointmentResponse]])
async def doctor_appointments(
    doctor_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("doctors", "read")),
):
    appointments = await DoctorService(db).get_appointments(doctor_id)
    return APIResponse(message="Appointments retrieved", data=appointments)


@router.get("/{doctor_id}/schedule", response_model=APIResponse[List[DoctorScheduleResponse]])
async def doctor_schedule(
    doctor_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("doctors", "read")),
):
    schedule = await DoctorService(db).get_schedule(doctor_id)
    return APIResponse(message="Schedule retrieved", data=schedule)


@router.post("/{doctor_id}/schedule", response_model=APIResponse[DoctorScheduleResponse], status_code=201)
async def add_doctor_schedule(
    doctor_id: int,
    data: DoctorScheduleCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("doctors", "update")),
):
    schedule = await DoctorService(db).add_schedule(doctor_id, data, current_user.id)
    return APIResponse(message="Schedule added", data=schedule)

@router.get("/{doctor_id}/clinical-records", response_model=APIResponse[PaginatedResult[ClinicalRecordResponse]])
async def list_doctor_clinical_records(
    doctor_id: int,
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: User = Depends(require_permission("doctors", "read")),
):
    from app.services.clinical_record_service import ClinicalRecordService
    result = await ClinicalRecordService(db).list_records(
        page=page, size=size, doctor_id=doctor_id
    )
    return APIResponse(message="Records fetched successfully", data=result)
