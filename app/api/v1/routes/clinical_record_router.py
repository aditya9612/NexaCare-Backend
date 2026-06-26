from fastapi import APIRouter, Depends, Query

from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.models.user_model import User
from app.schemas.common_schema import APIResponse, MessageResponse
from app.schemas.clinical_record_schema import (
    ClinicalRecordCreate,
    ClinicalRecordUpdate,
    ClinicalRecordResponse,
)
from app.services.clinical_record_service import ClinicalRecordService
from app.utils.pagination import PaginatedResult

router = APIRouter()


@router.post("", response_model=APIResponse[ClinicalRecordResponse], status_code=201)
async def create_clinical_record(
    data: ClinicalRecordCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("patients", "create")),
):
    record = await ClinicalRecordService(db).create_record(data, current_user.id)
    return APIResponse(message="Record created successfully", data=record)


@router.get("", response_model=APIResponse[PaginatedResult[ClinicalRecordResponse]])
async def list_clinical_records(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    patient_id: int | None = Query(None),
    doctor_id: int | None = Query(None),
    appointment_id: int | None = Query(None),
    _: User = Depends(require_permission("patients", "read")),
):
    result = await ClinicalRecordService(db).list_records(
        page=page, size=size, patient_id=patient_id, doctor_id=doctor_id, appointment_id=appointment_id
    )
    return APIResponse(message="Records fetched successfully", data=result)


@router.get("/{record_id}", response_model=APIResponse[ClinicalRecordResponse])
async def get_clinical_record(
    record_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("patients", "read")),
):
    record = await ClinicalRecordService(db).get_record(record_id)
    return APIResponse(message="Record fetched successfully", data=record)


@router.put("/{record_id}", response_model=APIResponse[ClinicalRecordResponse])
async def update_clinical_record(
    record_id: int,
    data: ClinicalRecordUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("patients", "update")),
):
    record = await ClinicalRecordService(db).update_record(record_id, data, current_user.id)
    return APIResponse(message="Record updated successfully", data=record)


@router.delete("/{record_id}", response_model=APIResponse[MessageResponse])
async def delete_clinical_record(
    record_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("patients", "delete")),
):
    await ClinicalRecordService(db).delete_record(record_id, current_user.id)
    return APIResponse(message="Record deleted successfully", data=MessageResponse(message="Soft deleted"))
