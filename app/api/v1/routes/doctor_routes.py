from typing import List

from fastapi import APIRouter, Depends

from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.models.user_model import User
from app.schemas.appointment_schema import AppointmentResponse
from app.schemas.common_schema import APIResponse, MessageResponse
from app.schemas.doctor_schema import (
    DoctorCreate,
    DoctorResponse,
    DoctorScheduleCreate,
    DoctorScheduleResponse,
    DoctorUpdate,
)
from app.services.doctor_service import DoctorService
from app.utils.pagination import PaginatedResult

router = APIRouter()


@router.post("", response_model=APIResponse[DoctorResponse], status_code=201)
async def create_doctor(
    data: DoctorCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("doctors", "create")),
):
    doctor = await DoctorService(db).create(data, current_user.id)
    return APIResponse(message="Doctor created", data=doctor)


@router.get("", response_model=APIResponse[PaginatedResult[DoctorResponse]])
async def list_doctors(
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    department: str | None = None,
    availability_status: str | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    _: User = Depends(require_permission("doctors", "read")),
):
    result = await DoctorService(db).list_doctors(
        page=page, size=size, department=department,
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
    data: DoctorUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("doctors", "update")),
):
    doctor = await DoctorService(db).update(doctor_id, data, current_user.id)
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
