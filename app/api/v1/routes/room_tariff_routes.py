from fastapi import APIRouter, Depends, Query, status

from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.models.user_model import User
from app.schemas.common_schema import APIResponse, MessageResponse
from app.schemas.room_tariff_schema import (
    RoomTariffCreate,
    RoomTariffResponse,
    RoomTariffUpdate,
)
from app.services.room_tariff_service import RoomTariffService

router = APIRouter(prefix="/tariffs/rooms", tags=["Room Tariff Master"])


@router.get("", response_model=APIResponse[list[RoomTariffResponse]])
async def list_room_tariffs(
    db: DbSession,
    current_user: CurrentUser,
    active_only: bool = Query(False, description="Filter active tariffs only"),
    _: User = Depends(require_permission("billing", "read")),
):
    """
    List all room tariffs (ICU, Deluxe, Special, General Ward per day rates).
    """
    tariffs = await RoomTariffService(db).list_tariffs(active_only=active_only)
    return APIResponse(
        success=True,
        message="Room tariffs retrieved successfully",
        data=tariffs,
    )


@router.get("/{tariff_id}", response_model=APIResponse[RoomTariffResponse])
async def get_room_tariff(
    tariff_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("billing", "read")),
):
    """
    Get a specific room tariff by ID.
    """
    tariff = await RoomTariffService(db).get_by_id(tariff_id)
    return APIResponse(
        success=True,
        message="Room tariff retrieved successfully",
        data=tariff,
    )


@router.post("", response_model=APIResponse[RoomTariffResponse], status_code=status.HTTP_201_CREATED)
async def create_room_tariff(
    data: RoomTariffCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("billing", "create")),
):
    """
    Create a new room tariff configuration.
    """
    tariff = await RoomTariffService(db).create(data)
    return APIResponse(
        success=True,
        message="Room tariff created successfully",
        data=tariff,
    )


@router.put("/{tariff_id}", response_model=APIResponse[RoomTariffResponse])
async def update_room_tariff(
    tariff_id: int,
    data: RoomTariffUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("billing", "update")),
):
    """
    Update an existing room tariff (adjust daily rates, nursing, or doctor visit charges).
    """
    tariff = await RoomTariffService(db).update(tariff_id, data)
    return APIResponse(
        success=True,
        message="Room tariff updated successfully",
        data=tariff,
    )


@router.delete("/{tariff_id}", response_model=APIResponse[MessageResponse])
async def delete_room_tariff(
    tariff_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("billing", "delete")),
):
    """
    Delete a room tariff.
    """
    await RoomTariffService(db).delete(tariff_id)
    return APIResponse(
        success=True,
        message="Room tariff deleted successfully",
        data=MessageResponse(message=f"Room tariff {tariff_id} deleted"),
    )
