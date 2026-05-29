from datetime import datetime
from pydantic import Field
from app.schemas.common_schema import BaseSchema

class LoginHistoryResponse(BaseSchema):
    id: int
    user_id: int | None
    login_time: datetime
    ip_address: str | None
    user_agent: str | None
    status: str
    details: str | None
    
    user_email: str | None = None

class AuditLogResponse(BaseSchema):
    id: int
    user_id: int | None
    action: str
    resource: str
    resource_id: str | None
    details: str | None
    ip_address: str | None
    created_at: datetime

    user_email: str | None = None

class BlockUserRequest(BaseSchema):
    user_id: int
    block: bool = True
