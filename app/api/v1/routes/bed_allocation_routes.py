from typing import List, Optional
from fastapi import APIRouter, Depends, Query

from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.models.user_model import User
from app.schemas.common_schema import APIResponse, MessageResponse
from app.schemas.bed_allocation_schema import (
    FloorCreate,
    FloorUpdate,
    FloorResponse,
    RoomCreate,
    RoomUpdate,
    RoomResponse,
    BedCreate,
    BedUpdate,
    BedResponse,
    BedAllocationRequest,
    BedReleaseRequest,
    BedTransferRequest,
    BedActivityLogResponse,
    BedAnalyticsSummaryResponse,
    ICUAnalyticsResponse,
)
from app.services.bed_allocation_service import BedAllocationService

router = APIRouter()


# 1. Floor Routes
@router.get("/floors", response_model=APIResponse[List[FloorResponse]])
async def list_floors(
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("bed_allocation", "read")),
    status: Optional[str] = Query(None, description="Filter beds by status (e.g. Available, Occupied, Cleaning, Maintenance, Reserved)"),
    floor_id: Optional[int] = Query(None, description="Filter by Floor ID"),
    floor_number: Optional[int] = Query(None, description="Filter by Floor Number"),
    floor_type: Optional[str] = Query(None, description="Filter by Floor Type (e.g. ICU, General, Emergency)"),
    room_id: Optional[int] = Query(None, description="Filter by Room ID"),
    room_number: Optional[int] = Query(None, description="Filter by Room Number"),
    room_type: Optional[str] = Query(None, description="Filter by Room Type (e.g. ICU, General, Deluxe)"),
):
    floors = await BedAllocationService(db).list_floors(
        status=status,
        floor_id=floor_id,
        floor_number=floor_number,
        floor_type=floor_type,
        room_id=room_id,
        room_number=room_number,
        room_type=room_type,
    )
    return APIResponse(message="Floors retrieved successfully", data=floors)


@router.post("/floors", response_model=APIResponse[FloorResponse], status_code=201)
async def create_floor(
    data: FloorCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("bed_allocation", "create")),
):
    floor = await BedAllocationService(db).create_floor(data)
    return APIResponse(message="Floor created successfully", data=floor)


@router.put("/floors/{floorId}", response_model=APIResponse[FloorResponse])
async def update_floor(
    floorId: int,
    data: FloorUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("bed_allocation", "update")),
):
    floor = await BedAllocationService(db).update_floor(floorId, data)
    return APIResponse(message="Floor updated successfully", data=floor)


@router.delete("/floors/{floorId}", response_model=APIResponse[MessageResponse])
async def delete_floor(
    floorId: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("bed_allocation", "delete")),
):
    await BedAllocationService(db).delete_floor(floorId)
    return APIResponse(message="Floor deleted successfully", data=MessageResponse(message="Deleted successfully"))


# 2. Room Routes
@router.post("/floors/{floorId}/rooms", response_model=APIResponse[RoomResponse], status_code=201)
async def create_room(
    floorId: int,
    data: RoomCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("bed_allocation", "create")),
):
    room = await BedAllocationService(db).create_room(floorId, data)
    return APIResponse(message="Room created successfully", data=room)


@router.put("/rooms/{roomId}", response_model=APIResponse[RoomResponse])
async def update_room(
    roomId: int,
    data: RoomUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("bed_allocation", "update")),
):
    room = await BedAllocationService(db).update_room(roomId, data)
    return APIResponse(message="Room updated successfully", data=room)


@router.delete("/rooms/{roomId}", response_model=APIResponse[MessageResponse])
async def delete_room(
    roomId: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("bed_allocation", "delete")),
):
    await BedAllocationService(db).delete_room(roomId)
    return APIResponse(message="Room deleted successfully", data=MessageResponse(message="Deleted successfully"))


# 3. Bed Routes
@router.post("/rooms/{roomId}/beds", response_model=APIResponse[BedResponse], status_code=201)
async def create_bed(
    roomId: int,
    data: BedCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("bed_allocation", "create")),
):
    bed = await BedAllocationService(db).create_bed(roomId, data)
    return APIResponse(message="Bed created successfully", data=bed)


@router.put("/beds/{bedId}", response_model=APIResponse[BedResponse])
async def update_bed(
    bedId: int,
    data: BedUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("bed_allocation", "update")),
):
    bed = await BedAllocationService(db).update_bed(bedId, data)
    return APIResponse(message="Bed updated successfully", data=bed)


@router.delete("/beds/{bedId}", response_model=APIResponse[MessageResponse])
async def delete_bed(
    bedId: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("bed_allocation", "delete")),
):
    await BedAllocationService(db).delete_bed(bedId)
    return APIResponse(message="Bed deleted successfully", data=MessageResponse(message="Deleted successfully"))


# 4. Bed Allocation Actions
@router.post("/beds/{bedId}/allocate", response_model=APIResponse[BedResponse])
async def allocate_bed(
    bedId: int,
    data: BedAllocationRequest,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("bed_allocation", "assign")),
):
    bed = await BedAllocationService(db).allocate_bed(bedId, data)
    return APIResponse(message="Bed allocated successfully", data=bed)


@router.post("/beds/{bedId}/release", response_model=APIResponse[BedResponse])
async def release_bed(
    bedId: int,
    data: BedReleaseRequest,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("bed_allocation", "assign")),
):
    bed = await BedAllocationService(db).release_bed(bedId, data)
    return APIResponse(message="Bed released successfully", data=bed)


@router.post("/beds/transfer", response_model=APIResponse[BedResponse])
async def transfer_bed(
    data: BedTransferRequest,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("bed_allocation", "assign")),
):
    bed = await BedAllocationService(db).transfer_bed(data)
    return APIResponse(message="Patient transferred successfully", data=bed)


# 5. Activity Log Routes
@router.get("/activity-logs", response_model=APIResponse[List[BedActivityLogResponse]])
async def list_activity_logs(
    db: DbSession,
    current_user: CurrentUser,
    limit: int = 50,
    _: User = Depends(require_permission("bed_allocation", "read")),
):
    logs = await BedAllocationService(db).list_activity_logs(limit)
    return APIResponse(message="Activity logs retrieved successfully", data=logs)


# 6. Analytics Routes
@router.get("/bed-analytics/summary", response_model=APIResponse[BedAnalyticsSummaryResponse])
async def get_analytics_summary(
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("bed_allocation", "read")),
):
    summary = await BedAllocationService(db).get_analytics_summary()
    return APIResponse(message="Bed analytics summary retrieved successfully", data=summary)


@router.get("/bed-analytics/icu", response_model=APIResponse[ICUAnalyticsResponse])
async def get_icu_analytics(
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("bed_allocation", "read")),
):
    analytics = await BedAllocationService(db).get_icu_analytics()
    return APIResponse(message="ICU bed analytics retrieved successfully", data=analytics)


# 7. Housekeeping & Bed Cleaning Routes
@router.get("/cleaning-queue", response_model=APIResponse[List[BedResponse]])
async def get_cleaning_queue(
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("bed_allocation", "read")),
):
    """
    List all beds currently in 'Cleaning' status awaiting housekeeping sanitization.
    """
    beds = await BedAllocationService(db).get_cleaning_queue()
    return APIResponse(message="Beds awaiting cleaning retrieved successfully", data=beds)


@router.patch("/beds/{bedId}/cleaning-complete", response_model=APIResponse[BedResponse])
async def mark_cleaning_complete(
    bedId: int,
    db: DbSession,
    current_user: CurrentUser,
    notes: str | None = Query(None, description="Housekeeping sanitization notes"),
    _: User = Depends(require_permission("bed_allocation", "assign")),
):
    """
    Housekeeping marks bed sanitization complete. Bed status transitions to 'Available'.
    """
    bed = await BedAllocationService(db).mark_cleaning_complete(bedId, current_user.id, notes)
    return APIResponse(message="Bed cleaning completed and bed is now Available", data=bed)

