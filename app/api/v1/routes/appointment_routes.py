from datetime import date
from typing import List

from fastapi import APIRouter, Depends

from app.core.dependencies import CurrentUser, DbSession, require_permission, require_roles
from app.models.user_model import User
from app.core.constants import UserRole
from app.schemas.appointment_schema import (
    AppointmentCreate,
    AppointmentResponse,
    AppointmentUpdate,
    CancelRequest,
    ConfirmRequest,
    RescheduleRequest,
    TokenResponse,
    AppointmentCheckInResponse,
    AppointmentCheckOutResponse,
    QueueTokenResponse,
    QueueStatusResponse,
    ConfirmedVisitListResponse,
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
    date_filter: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    _: User = Depends(require_permission("appointments", "read")),
):
    result = await AppointmentService(db).list_appointments(
        page=page, size=size, patient_id=patient_id, doctor_id=doctor_id,
        department_id=department_id, status=status, appointment_date=appointment_date,
        date_filter=date_filter, start_date=start_date, end_date=end_date,
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


@router.get("/confirmed-visits", response_model=APIResponse[ConfirmedVisitListResponse])
async def confirmed_visits(
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    limit: int = 20,
    search: str | None = None,
    doctor_id: int | None = None,
    department_id: int | None = None,
    appointment_date: date | None = None,
    _: User = Depends(require_roles(UserRole.RECEPTIONIST, UserRole.SUPER_ADMIN, UserRole.HOSPITAL_ADMIN)),
):
    if page < 1:
        page = 1
    if limit < 1:
        limit = 20
    elif limit > 100:
        limit = 100
        
    result = await AppointmentService(db).get_confirmed_visit_list(
        page=page,
        limit=limit,
        search=search,
        doctor_id=doctor_id,
        department_id=department_id,
        appointment_date=appointment_date,
    )
    return APIResponse(message="Confirmed visits retrieved", data=result)


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

@router.patch("/{appointment_id}/check-in", response_model=APIResponse[AppointmentCheckInResponse])
async def check_in_appointment(
    appointment_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_roles(UserRole.RECEPTIONIST)),
):
    appointment = await AppointmentService(db).check_in(appointment_id, current_user.id)
    return APIResponse(
        message="Patient checked in successfully",
        data=AppointmentCheckInResponse(
            id=appointment.id,
            appointment_number=appointment.appointment_number,
            check_in_time=appointment.check_in_time,
            appointment_status=appointment.appointment_status
        )
    )


@router.patch("/{appointment_id}/check-out", response_model=APIResponse[AppointmentCheckOutResponse])
async def check_out_appointment(
    appointment_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_roles(UserRole.RECEPTIONIST)),
):
    appointment = await AppointmentService(db).check_out(appointment_id, current_user.id)
    return APIResponse(
        message="Patient checked out successfully",
        data=AppointmentCheckOutResponse(
            id=appointment.id,
            appointment_number=appointment.appointment_number,
            check_out_time=appointment.check_out_time,
            appointment_status=appointment.appointment_status
        )
    )


@router.post("/{appointment_id}/generate-token", response_model=APIResponse[QueueTokenResponse])
async def generate_queue_token(
    appointment_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_roles(UserRole.RECEPTIONIST)),
):
    appointment = await AppointmentService(db).generate_queue_token(appointment_id, current_user.id)
    return APIResponse(
        message="Queue token generated successfully",
        data=QueueTokenResponse(
            appointment_id=appointment.id,
            queue_token=appointment.queue_token,
            queue_status=appointment.queue_status
        )
    )


@router.get("/queue", response_model=APIResponse[List[AppointmentResponse]])
async def get_today_queue(
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_roles(UserRole.RECEPTIONIST)),
):
    appointments = await AppointmentService(db).get_today_queue()
    return APIResponse(
        message="Today's queue retrieved successfully",
        data=[AppointmentResponse.model_validate(a) for a in appointments]
    )


@router.get("/queue/current", response_model=APIResponse[AppointmentResponse | None])
async def get_current_queue(
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_roles(UserRole.RECEPTIONIST)),
):
    appointment = await AppointmentService(db).get_current_queue()
    return APIResponse(
        message="Current queue item retrieved successfully",
        data=AppointmentResponse.model_validate(appointment) if appointment else None
    )


@router.patch("/queue/{appointment_id}/call", response_model=APIResponse[QueueStatusResponse])
async def call_next_token(
    appointment_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_roles(UserRole.RECEPTIONIST)),
):
    appointment = await AppointmentService(db).call_next_token(appointment_id, current_user.id)
    return APIResponse(
        message="Next token called successfully",
        data=QueueStatusResponse(
            appointment_id=appointment.id,
            queue_token=appointment.queue_token,
            queue_status=appointment.queue_status
        )
    )


@router.patch("/queue/{appointment_id}/complete", response_model=APIResponse[QueueStatusResponse])
async def complete_token(
    appointment_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_roles(UserRole.RECEPTIONIST)),
):
    appointment = await AppointmentService(db).complete_token(appointment_id, current_user.id)
    return APIResponse(
        message="Token completed successfully",
        data=QueueStatusResponse(
            appointment_id=appointment.id,
            queue_token=appointment.queue_token,
            queue_status=appointment.queue_status
        )
    )


@router.patch("/queue/{appointment_id}/skip", response_model=APIResponse[QueueStatusResponse])
async def skip_token(
    appointment_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_roles(UserRole.RECEPTIONIST)),
):
    appointment = await AppointmentService(db).skip_token(appointment_id, current_user.id)
    return APIResponse(
        message="Token skipped successfully",
        data=QueueStatusResponse(
            appointment_id=appointment.id,
            queue_token=appointment.queue_token,
            queue_status=appointment.queue_status
        )
    )


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
