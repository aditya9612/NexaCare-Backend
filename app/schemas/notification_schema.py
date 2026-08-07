from datetime import datetime
from pydantic import BaseModel, Field

from app.schemas.common_schema import BaseSchema


class NotificationResponse(BaseSchema):
    id: int
    user_id: int
    title: str
    message: str
    notification_type: str = Field(..., description="Type of notification: CRITICAL_VALUE, PENDING_TEST")
    reference_type: str | None = Field(None, description="Reference entity: TEST_RESULT, TEST_ORDER")
    reference_id: int | None = Field(None, description="ID of reference entity")
    priority: str = Field("NORMAL", description="Priority level: HIGH, NORMAL")
    is_read: bool = False
    created_at: datetime
    updated_at: datetime


class UnreadCountResponse(BaseModel):
    unread_count: int = Field(..., description="Total unread notifications count for the user")


class CategoryCountsResponse(BaseModel):
    all: int
    critical: int
    medication: int
    doctors: int
    vitals: int
    updates: int
    tasks: int
    system: int
    unread: int
    completed: int

