from datetime import date
from typing import List

from fastapi import APIRouter, Depends

from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.models.user_model import User
from app.schemas.appointment_schema import (
    AppointmentCreate,
    AppointmentResponse,
    AppointmentUpdate,
    CancelRequest,
    ConfirmRequest,
    RescheduleRequest,
    TokenResponse,
)
from app.schemas.common_schema import APIResponse, MessageResponse
from app.services.appointment_service import AppointmentService
from app.utils.pagination import PaginatedResult

router = APIRouter()


@router.post("", response_model=APIResponse[AppointmentResponse], status_code=201)
async def create_appointment(
    data: AppointmentCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("appointments", "create")),
):
    appointment = await AppointmentService(db).create(data, current_user.id)
    return APIResponse(message="Appointment booked", data=appointment)


@router.get("", response_model=APIResponse[PaginatedResult[AppointmentResponse]])
async def list_appointments(
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    patient_id: int | None = None,
    doctor_id: int | None = None,
    department_id: int | None = None,
    status: str | None = None,
    appointment_date: date | None = None,
    _: User = Depends(require_permission("appointments", "read")),
):
    result = await AppointmentService(db).list_appointments(
        page=page, size=size, patient_id=patient_id, doctor_id=doctor_id,
        department_id=department_id, status=status, appointment_date=appointment_date,
    )
    return APIResponse(message="Appointments retrieved", data=result)


@router.get("/calendar", response_model=APIResponse[List[AppointmentResponse]])
async def calendar_view(
    start_date: date,
    end_date: date,
    db: DbSession,
    current_user: CurrentUser,
    doctor_id: int | None = None,
    _: User = Depends(require_permission("appointments", "read")),
):
    appointments = await AppointmentService(db).get_calendar(start_date, end_date, doctor_id)
    return APIResponse(message="Calendar data", data=appointments)


@router.get("/today", response_model=APIResponse[List[AppointmentResponse]])
async def today_appointments(
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("appointments", "read")),
):
    appointments = await AppointmentService(db).get_today()
    return APIResponse(message="Today's appointments", data=appointments)


@router.get("/upcoming", response_model=APIResponse[List[AppointmentResponse]])
async def upcoming_appointments(
    db: DbSession,
    current_user: CurrentUser,
    limit: int = 20,
    _: User = Depends(require_permission("appointments", "read")),
):
    appointments = await AppointmentService(db).get_upcoming(limit)
    return APIResponse(message="Upcoming appointments", data=appointments)


@router.post("/reschedule", response_model=APIResponse[AppointmentResponse])
async def reschedule_appointment(
    data: RescheduleRequest,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("appointments", "update")),
):
    appointment = await AppointmentService(db).reschedule(data, current_user.id)
    return APIResponse(message="Appointment rescheduled", data=appointment)


@router.post("/cancel", response_model=APIResponse[AppointmentResponse])
async def cancel_appointment(
    data: CancelRequest,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("appointments", "update")),
):
    appointment = await AppointmentService(db).cancel(data, current_user.id)
    return APIResponse(message="Appointment cancelled", data=appointment)


@router.post("/confirm", response_model=APIResponse[AppointmentResponse])
async def confirm_appointment(
    data: ConfirmRequest,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("appointments", "approve")),
):
    appointment = await AppointmentService(db).confirm(data, current_user.id)
    return APIResponse(message="Appointment confirmed", data=appointment)

@router.get("/{appointment_id}/token", response_model=APIResponse[TokenResponse])
async def get_appointment_token(
    appointment_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("appointments", "read")),
):
    token = await AppointmentService(db).get_token(appointment_id)
    return APIResponse(message="Token retrieved", data=token)


@router.get("/{appointment_id}", response_model=APIResponse[AppointmentResponse])
async def get_appointment(
    appointment_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("appointments", "read")),
):
    appointment = await AppointmentService(db).get_by_id(appointment_id)
    return APIResponse(message="Appointment retrieved", data=appointment)


@router.put("/{appointment_id}", response_model=APIResponse[AppointmentResponse])
async def update_appointment(
    appointment_id: int,
    data: AppointmentUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("appointments", "update")),
):
    appointment = await AppointmentService(db).update(appointment_id, data, current_user.id)
    return APIResponse(message="Appointment updated", data=appointment)


@router.delete("/{appointment_id}", response_model=APIResponse[MessageResponse])
async def delete_appointment(
    appointment_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("appointments", "delete")),
):
    await AppointmentService(db).delete(appointment_id, current_user.id)
    return APIResponse(message="Appointment deleted", data=MessageResponse(message="Deleted"))
