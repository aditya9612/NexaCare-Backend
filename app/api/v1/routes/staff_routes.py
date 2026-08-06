from typing import List

from fastapi import APIRouter, Depends, status

from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.models.user_model import User
from app.schemas.common_schema import APIResponse, MessageResponse
from app.schemas.staff_schema import (
    StaffCreate,
    StaffResponse,
    StaffStatusUpdate,
    StaffUpdate,
    StaffScheduleCreate,
    StaffScheduleResponse,
    StaffListWithCountsResponse,
)
from app.services.staff_service import StaffService
from app.utils.pagination import PaginatedResult

router = APIRouter()


@router.post("", response_model=APIResponse[StaffResponse], status_code=status.HTTP_201_CREATED)
async def create_staff(
    data: StaffCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("staff", "create")),
):
    staff = await StaffService(db).create_staff(data, current_user.id)
    return APIResponse(message="Staff created successfully", data=staff)


@router.get("", response_model=APIResponse[StaffListWithCountsResponse])
async def list_staff(
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    q: str | None = None,
    department_id: int | None = None,
    status: int | None = None,
    _: User = Depends(require_permission("staff", "read")),
):
    result = await StaffService(db).list_staff(
        page=page, size=size, q=q, department_id=department_id, status=status
    )
    return APIResponse(message="Staff retrieved", data=result)


@router.get("/dashboard/stats", response_model=APIResponse[dict])
async def get_dashboard_stats(
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("staff", "read")),
):
    stats = await StaffService(db).get_dashboard_stats()
    return APIResponse(message="Dashboard statistics retrieved", data=stats)


@router.get("/department/{department_id}", response_model=APIResponse[List[StaffResponse]])
async def get_staff_by_department(
    department_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("staff", "read")),
):
    staff_list = await StaffService(db).get_staff_by_department(department_id)
    return APIResponse(message="Staff in department retrieved", data=staff_list)


@router.get("/{staff_id}", response_model=APIResponse[StaffResponse])
async def get_staff_by_id(
    staff_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("staff", "read")),
):
    staff = await StaffService(db).get_staff_by_id(staff_id)
    return APIResponse(message="Staff retrieved successfully", data=staff)


@router.patch("/{staff_id}", response_model=APIResponse[StaffResponse])
async def update_staff(
    staff_id: int,
    data: StaffUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("staff", "update")),
):
    staff = await StaffService(db).update_staff(staff_id, data, current_user.id)
    return APIResponse(message="Staff updated successfully", data=staff)


@router.patch("/{staff_id}/status", response_model=APIResponse[StaffResponse])
async def update_staff_status(
    staff_id: int,
    data: StaffStatusUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("staff", "update")),
):
    staff = await StaffService(db).update_staff_status(staff_id, data.status.value, current_user.id)
    return APIResponse(message="Staff status updated successfully", data=staff)


@router.delete("/{staff_id}", response_model=APIResponse[MessageResponse])
async def delete_staff(
    staff_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("staff", "delete")),
):
    await StaffService(db).delete_staff(staff_id, current_user.id)
    return APIResponse(message="Staff soft deleted successfully", data=MessageResponse(message="Soft deleted"))


@router.get("/{staff_id}/schedule", response_model=APIResponse[List[StaffScheduleResponse]])
async def get_staff_schedule(
    staff_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("staff", "read")),
):
    schedule = await StaffService(db).get_schedule(staff_id)
    return APIResponse(message="Schedule retrieved", data=schedule)


@router.post("/{staff_id}/schedule", response_model=APIResponse[StaffScheduleResponse], status_code=status.HTTP_201_CREATED)
async def add_staff_schedule(
    staff_id: int,
    data: StaffScheduleCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("staff", "update")),
):
    schedule = await StaffService(db).add_schedule(staff_id, data, current_user.id)
    return APIResponse(message="Schedule added", data=schedule)


@router.delete("/{staff_id}/schedule", response_model=APIResponse[MessageResponse])
async def delete_all_staff_schedules(
    staff_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("staff", "delete")),
):
    await StaffService(db).delete_all_schedules(staff_id, current_user.id)
    return APIResponse(
        message="All schedule slots removed successfully",
        data=MessageResponse(message="All schedule slots removed"),
    )


@router.delete("/{staff_id}/schedule/{slot_id}", response_model=APIResponse[MessageResponse])
async def delete_staff_schedule_slot(
    staff_id: int,
    slot_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("staff", "delete")),
):
    await StaffService(db).delete_schedule_slot(staff_id, slot_id, current_user.id)
    return APIResponse(
        message="Schedule slot removed successfully",
        data=MessageResponse(message="Schedule slot removed"),
    )
