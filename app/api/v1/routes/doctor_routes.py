from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, Body, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from pydantic import ValidationError

from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.models.user_model import User
from app.schemas.appointment_schema import AppointmentResponse, DoctorAppointmentListResponse
from app.schemas.common_schema import APIResponse, MessageResponse
from app.schemas.doctor_schema import (
    DoctorCreate,
    DoctorOnboardCreate,
    DoctorOnboardResponse,
    DoctorResponse,
    DoctorScheduleCreate,
    DoctorScheduleResponse,
    DoctorScheduleUpdate,
    DoctorUpdate,
    DoctorPaginatedResult,
)
from app.schemas.doctor_medical_record_schema import (
    DiagnosisResponse,
    DiagnosisUpdate,
    MedicalRecordResponse,
    TreatmentNoteCreate,
    TreatmentNoteResponse,
    MedicalRecordUploadValidator,
    MedicalRecordUpdate,
)
from app.services.doctor_service import DoctorService
from app.services.doctor_medical_record_service import DoctorMedicalRecordService
from app.utils.pagination import PaginatedResult
from app.schemas.clinical_record_schema import ClinicalRecordResponse
from fastapi import Query

router = APIRouter()


@router.post(
    "",
    response_model=APIResponse[DoctorResponse],
    status_code=201,
    openapi_extra={
        "requestBody": {
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "required": ["first_name", "last_name", "specialization", "license_number", "experience"]
                    }
                }
            }
        }
    }
)
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
            raise RequestValidationError(e.errors())
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
        if experience is None:
            missing_fields.append({"type": "missing", "loc": ["body", "experience"], "msg": "Field required", "input": None})
        
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
            raise RequestValidationError(e.errors())
        image_file = profile_image

    doctor_obj = await DoctorService(db).create(doctor_data, current_user.id, image_file=image_file)
    return APIResponse(message="Doctor created", data=doctor_obj)


@router.post(
    "/onboard",
    response_model=APIResponse[DoctorOnboardResponse],
    status_code=201,
    openapi_extra={
        "requestBody": {
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "required": [
                            "first_name",
                            "last_name",
                            "specialization",
                            "license_number",
                            "experience",
                            "phone",
                            "email",
                            "password",
                        ]
                    }
                }
            }
        }
    },
)
async def onboard_doctor(
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
    password: Optional[str] = Form(None),
    department_id: Optional[int] = Form(None),
    consultation_fee: Optional[float] = Form(None),
    availability_status: Optional[str] = Form(None),
    bio: Optional[str] = Form(None),
    gender: Optional[str] = Form(None),
    date_of_birth: Optional[str] = Form(None),
    profile_image: Optional[UploadFile] = File(None),
    _: User = Depends(require_permission("doctors", "create")),
):
    """
    Create a doctor login account (`users`) and clinical profile (`doctors`) in one step.
    Accepts multipart/form-data only (optional profile image file).
    The new doctor can log in immediately with the provided email and password.
    """
    missing_fields = []
    required = {
        "first_name": first_name,
        "last_name": last_name,
        "specialization": specialization,
        "license_number": license_number,
        "experience": experience,
        "phone": phone,
        "email": email,
        "password": password,
    }
    for field_name, value in required.items():
        if value is None or (isinstance(value, str) and not value.strip()):
            missing_fields.append({
                "type": "missing",
                "loc": ["body", field_name],
                "msg": "Field required",
                "input": None,
            })
    if missing_fields:
        raise HTTPException(status_code=422, detail=missing_fields)

    try:
        onboard_data = DoctorOnboardCreate(
            first_name=first_name,
            last_name=last_name,
            specialization=specialization,
            qualification=qualification,
            experience=experience,
            phone=phone,
            email=email,
            password=password,
            department_id=department_id,
            consultation_fee=consultation_fee,
            license_number=license_number,
            availability_status=availability_status or "available",
            bio=bio,
            gender=gender,
            date_of_birth=date_of_birth or None,
            profile_image=None,
        )
    except ValidationError as e:
        raise RequestValidationError(e.errors())

    result = await DoctorService(db).onboard(onboard_data, current_user, image_file=profile_image)
    return APIResponse(message="Doctor onboarded successfully", data=result)


@router.get("", response_model=APIResponse[DoctorPaginatedResult])
async def list_doctors(
    db: DbSession,
    current_user: CurrentUser,
    page: int | None = None,
    size: int | None = None,
    department_id: int | None = None,
    availability_status: str | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    _: User = Depends(require_permission("doctors", "read")),
):
    from app.models.staff_model import Staff
    from app.core.exceptions import BadRequestException
    from sqlalchemy import select

    # Resolve department_id for Lab Technician
    role_name = current_user.role.name.lower() if current_user and current_user.role else ""
    if role_name in ["lab technician", "lab_technician"]:
        staff_result = await db.execute(
            select(Staff).where(Staff.email == current_user.email)
        )
        staff = staff_result.scalar_one_or_none()
        if not staff or not staff.department_id:
            raise BadRequestException("Lab technician department is not assigned")
        department_id = staff.department_id

    result = await DoctorService(db).list_doctors(
        current_user=current_user,
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
    summary="Create Medical Record",
)
async def upload_report(
    db: DbSession,
    current_user: CurrentUser,
    patient_id: int = Form(...),
    appointment_id: int = Form(...),
    doctor_id: int = Form(...),
    diagnosis: str = Form(...),
    report_title: Optional[str] = Form(None),
    report_type: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    symptoms: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    _: User = Depends(require_permission("doctors", "create")),
):
    try:
        validated = MedicalRecordUploadValidator(
            patient_id=patient_id,
            appointment_id=appointment_id,
            doctor_id=doctor_id,
            diagnosis=diagnosis,
            report_title=report_title,
            report_type=report_type,
            notes=notes,
            symptoms=symptoms,
        )
        report_title = validated.report_title
        report_type = validated.report_type
        diagnosis = validated.diagnosis
        notes = validated.notes
        symptoms = validated.symptoms
    except ValidationError as e:
        raise RequestValidationError(e.errors())

    record = await DoctorMedicalRecordService(db).upload_report(
        patient_id=patient_id,
        appointment_id=appointment_id,
        doctor_id=doctor_id,
        diagnosis=diagnosis,
        report_title=report_title,
        report_type=report_type,
        notes=notes,
        symptoms=symptoms,
        file=file,
        user_id=current_user.id,
    )
    return APIResponse(message="Report uploaded", data=record)


@router.get(
    "/medical-records",
    response_model=APIResponse[PaginatedResult[MedicalRecordResponse]],
    summary="List of Medical Records",
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
        user_id=current_user.id,
    )
    return APIResponse(message="Medical records retrieved", data=result)


@router.get("/medical-records/{record_id}/download")
async def download_report(
    record_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("doctors", "read")),
):
    record = await DoctorMedicalRecordService(db).get_report_file(record_id, user_id=current_user.id)
    return FileResponse(
        path=record.file_path,
        filename=record.file_name,
        media_type=record.file_type or "application/octet-stream",
    )


@router.get(
    "/medical-records/view",
    summary="View Report",
)
async def view_report(
    db: DbSession,
    current_user: CurrentUser,
    record_id: Optional[int] = None,
    _: User = Depends(require_permission("doctors", "read")),
):
    if record_id is None:
        return APIResponse(message="No report record_id provided", data=None)
    record = await DoctorMedicalRecordService(db).get_report_file(record_id, user_id=current_user.id)
    return FileResponse(
        path=record.file_path,
        filename=record.file_name,
        media_type=record.file_type or "application/octet-stream",
        content_disposition_type="inline",
    )


@router.get(
    "/medical-records/{record_id}",
    response_model=APIResponse[MedicalRecordResponse],
)
async def get_medical_record(
    record_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("doctors", "read")),
):
    record = await DoctorMedicalRecordService(db).get_report_by_id(record_id, user_id=current_user.id)
    return APIResponse(message="Medical record retrieved", data=record)


@router.put(
    "/medical-records/{record_id}",
    response_model=APIResponse[MedicalRecordResponse],
)
async def update_medical_record(
    record_id: int,
    db: DbSession,
    current_user: CurrentUser,
    report_title: Optional[str] = Form(None),
    report_type: Optional[str] = Form(None),
    diagnosis: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    _: User = Depends(require_permission("doctors", "update")),
):
    try:
        validated = MedicalRecordUpdate(
            report_title=report_title,
            report_type=report_type,
            diagnosis=diagnosis,
            notes=notes,
        )
        report_title = validated.report_title
        report_type = validated.report_type
        diagnosis = validated.diagnosis
        notes = validated.notes
    except ValidationError as e:
        raise RequestValidationError(e.errors())

    record = await DoctorMedicalRecordService(db).update_report(
        record_id=record_id,
        report_title=report_title,
        report_type=report_type,
        diagnosis=diagnosis,
        notes=notes,
        file=file,
        user_id=current_user.id,
    )
    return APIResponse(message="Medical record updated", data=record)


@router.delete(
    "/medical-records/{record_id}",
    response_model=APIResponse[MessageResponse],
)
async def delete_medical_record(
    record_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("doctors", "delete")),
):
    await DoctorMedicalRecordService(db).delete_report(record_id, current_user.id)
    return APIResponse(
        message="Medical record deleted",
        data=MessageResponse(message="Record deleted"),
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


@router.get("/bulk-template")
async def get_bulk_template(
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("doctors", "read")),
):
    from fastapi.responses import StreamingResponse
    stream = await DoctorService(db).generate_doctor_bulk_template()
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=doctors_bulk_template.xlsx"}
    )


@router.post("/bulk-upload", response_model=APIResponse[dict])
async def upload_bulk(
    db: DbSession,
    current_user: CurrentUser,
    file: UploadFile = File(...),
    _: User = Depends(require_permission("doctors", "create")),
):
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Only Excel (.xlsx) files are allowed.")
        
    content = await file.read()
    result = await DoctorService(db).import_doctors_from_excel(content, current_user)
    return APIResponse(message="Bulk upload processed", data=result)


@router.get("/export")
async def export_doctors_data(
    db: DbSession,
    current_user: CurrentUser,
    format: str = Query(..., description="Export format: excel or pdf"),
    department_id: Optional[int] = Query(None),
    availability_status: Optional[str] = Query(None),
    _: User = Depends(require_permission("doctors", "read")),
):
    if format not in ("excel", "pdf"):
        raise HTTPException(status_code=400, detail="Format must be 'excel' or 'pdf'")
        
    content, media_type = await DoctorService(db).export_doctors(
        format_type=format,
        department_id=department_id,
        availability_status=availability_status
    )
    
    filename = f"doctors_export.{'xlsx' if format == 'excel' else 'pdf'}"
    
    from fastapi import Response
    return Response(
        content=content if format == "pdf" else content.getvalue(),
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.get("/{doctor_id}", response_model=APIResponse[DoctorResponse])
async def get_doctor(
    doctor_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("doctors", "read")),
):
    doctor = await DoctorService(db).get_by_id(doctor_id)
    return APIResponse(message="Doctor retrieved", data=doctor)


@router.put("/{doctor_id}", response_model=APIResponse[DoctorOnboardResponse])
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
    password: Optional[str] = Form(None),
    department_id: Optional[int] = Form(None),
    consultation_fee: Optional[float] = Form(None),
    license_number: Optional[str] = Form(None),
    availability_status: Optional[str] = Form(None),
    bio: Optional[str] = Form(None),
    gender: Optional[str] = Form(None),
    date_of_birth: Optional[str] = Form(None),
    profile_image: Optional[UploadFile] = File(None),
    _: User = Depends(require_permission("doctors", "update")),
):
    update_args = {}
    if first_name is not None and first_name.strip() != "":
        update_args["first_name"] = first_name.strip()
    if last_name is not None and last_name.strip() != "":
        update_args["last_name"] = last_name.strip()
    if specialization is not None and specialization.strip() != "":
        update_args["specialization"] = specialization.strip()
    if qualification is not None and qualification.strip() != "":
        update_args["qualification"] = qualification.strip()
    if experience is not None:
        update_args["experience"] = experience
    if phone is not None and phone.strip() != "":
        update_args["phone"] = phone.strip()
    if email is not None and email.strip() != "":
        update_args["email"] = email.strip()
    if password is not None and password.strip() != "":
        update_args["password"] = password
    if department_id is not None:
        update_args["department_id"] = department_id
    if consultation_fee is not None:
        update_args["consultation_fee"] = consultation_fee
    if license_number is not None and license_number.strip() != "":
        update_args["license_number"] = license_number.strip()
    if availability_status is not None and availability_status.strip() != "":
        update_args["availability_status"] = availability_status.strip()
    if bio is not None and bio.strip() != "":
        update_args["bio"] = bio.strip()
    if gender is not None and gender.strip() != "":
        update_args["gender"] = gender.strip()
    if date_of_birth is not None and date_of_birth.strip() != "":
        update_args["date_of_birth"] = date_of_birth.strip()

    try:
        data = DoctorUpdate(**update_args)
    except ValidationError as e:
        raise RequestValidationError(e.errors())
    result = await DoctorService(db).update(doctor_id, data, current_user.id, image_file=profile_image)
    return APIResponse(message="Doctor updated", data=result)


@router.delete("/{doctor_id}", response_model=APIResponse[MessageResponse])
async def delete_doctor(
    doctor_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("doctors", "delete")),
):
    await DoctorService(db).delete(doctor_id, current_user.id)
    return APIResponse(message="Doctor deleted", data=MessageResponse(message="Soft deleted"))


@router.get("/{doctor_id}/appointments", response_model=APIResponse[DoctorAppointmentListResponse])
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


@router.put("/{doctor_id}/schedule", response_model=APIResponse[List[DoctorScheduleResponse]])
async def update_doctor_schedule(
    doctor_id: int,
    data: List[DoctorScheduleCreate],
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("doctors", "update")),
):
    schedule = await DoctorService(db).update_doctor_schedule(doctor_id, data, current_user.id)
    return APIResponse(message="Doctor schedule updated successfully", data=schedule)


@router.put("/{doctor_id}/schedule/{slot_id}", response_model=APIResponse[DoctorScheduleResponse])
@router.patch("/{doctor_id}/schedule/{slot_id}", response_model=APIResponse[DoctorScheduleResponse])
async def update_doctor_schedule_slot(
    doctor_id: int,
    slot_id: int,
    data: DoctorScheduleUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("doctors", "update")),
):
    schedule = await DoctorService(db).update_schedule_slot(doctor_id, slot_id, data, current_user.id)
    return APIResponse(message="Schedule slot updated successfully", data=schedule)


@router.delete("/{doctor_id}/schedule", response_model=APIResponse[MessageResponse])

async def delete_all_doctor_schedules(
    doctor_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("doctors", "delete")),
):
    await DoctorService(db).delete_all_schedules(doctor_id, current_user.id)
    return APIResponse(
        message="All schedule slots removed successfully",
        data=MessageResponse(message="All schedule slots removed"),
    )


@router.delete("/{doctor_id}/schedule/{slot_id}", response_model=APIResponse[MessageResponse])
async def delete_doctor_schedule_slot(
    doctor_id: int,
    slot_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("doctors", "delete")),
):
    await DoctorService(db).delete_schedule_slot(doctor_id, slot_id, current_user.id)
    return APIResponse(
        message="Schedule slot removed successfully",
        data=MessageResponse(message="Schedule slot removed"),
    )

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
