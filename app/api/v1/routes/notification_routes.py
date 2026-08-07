from typing import Any

from fastapi import APIRouter, Query, status

from app.core.dependencies import CurrentUser, DbSession
from app.schemas.common_schema import APIResponse
from app.schemas.notification_schema import NotificationResponse, UnreadCountResponse, CategoryCountsResponse
from app.services.notification_service import NotificationService
from app.utils.pagination import PaginatedResult

router = APIRouter()


@router.get("", response_model=APIResponse[PaginatedResult[NotificationResponse]])
async def list_notifications(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    is_read: bool | None = Query(None, description="Filter by read status"),
    notification_type: str | None = Query(None, description="Filter by type: CRITICAL_VALUE, PENDING_TEST, DOCTOR_APPOINTMENT_REMINDER"),
    category: str | None = Query(None, description="Filter by category (e.g. critical, medication, doctors, vitals, updates, tasks, system, unread, completed)"),
) -> APIResponse[PaginatedResult[NotificationResponse]]:
    """Get logged-in user's notifications (newest first)."""
    result = await NotificationService(db).list_user_notifications(
        user_id=current_user.id,
        page=page,
        limit=limit,
        is_read=is_read,
        notification_type=notification_type,
        category=category,
    )
    return APIResponse(message="Notifications retrieved successfully", data=result)


@router.get("/category-counts", response_model=APIResponse[CategoryCountsResponse])
async def get_category_counts(
    db: DbSession,
    current_user: CurrentUser,
) -> APIResponse[CategoryCountsResponse]:
    """Get notification count for each category for the logged-in user."""
    counts = await NotificationService(db).get_category_counts(current_user.id)
    return APIResponse(message="Category counts retrieved successfully", data=CategoryCountsResponse(**counts))


@router.get("/unread-count", response_model=APIResponse[UnreadCountResponse])
async def get_unread_notification_count(
    db: DbSession,
    current_user: CurrentUser,
) -> APIResponse[UnreadCountResponse]:
    """Get unread notification count for the logged-in user."""
    unread_data = await NotificationService(db).get_unread_count(current_user.id)
    return APIResponse(message="Unread notification count retrieved", data=unread_data)


@router.patch("/{notification_id}/read", response_model=APIResponse[NotificationResponse])
async def mark_notification_as_read(
    notification_id: int,
    db: DbSession,
    current_user: CurrentUser,
) -> APIResponse[NotificationResponse]:
    """Mark a specific notification as read."""
    updated = await NotificationService(db).mark_as_read(notification_id, current_user.id)
    return APIResponse(message="Notification marked as read", data=updated)


@router.patch("/read-all", response_model=APIResponse[dict[str, Any]])
async def mark_all_notifications_as_read(
    db: DbSession,
    current_user: CurrentUser,
) -> APIResponse[dict[str, Any]]:
    """Mark all unread notifications as read for the logged-in user."""
    result = await NotificationService(db).mark_all_as_read(current_user.id)
    return APIResponse(message="All notifications marked as read", data=result)
