from fastapi import APIRouter, Depends
from app.core.dependencies import CurrentUser, DbSession
from app.core.exceptions import ForbiddenException
from app.core.constants import UserRole
from app.schemas.common_schema import APIResponse, MessageResponse
from app.schemas.security_schema import LoginHistoryResponse, AuditLogResponse, BlockUserRequest
from app.services.security_service import SecurityService
from app.models.user_model import User

router = APIRouter()

async def require_super_admin(user: CurrentUser) -> User:
    if not user.role or user.role.name != UserRole.SUPER_ADMIN:
        raise ForbiddenException("Requires Super Admin role")
    return user

@router.get("/login-history", response_model=APIResponse[list[LoginHistoryResponse]])
async def get_login_history(
    db: DbSession,
    current_user: User = Depends(require_super_admin)
):
    history = await SecurityService(db).list_login_history()
    return APIResponse(message="Login history retrieved successfully", data=history)

@router.get("/audit-logs", response_model=APIResponse[list[AuditLogResponse]])
async def get_audit_logs(
    db: DbSession,
    current_user: User = Depends(require_super_admin)
):
    logs = await SecurityService(db).list_audit_logs()
    return APIResponse(message="Security audit logs retrieved successfully", data=logs)

@router.post("/block-user", response_model=APIResponse[MessageResponse])
async def block_user(
    data: BlockUserRequest,
    db: DbSession,
    current_user: User = Depends(require_super_admin)
):
    await SecurityService(db).block_user(data, current_user.id)
    action_msg = "blocked" if data.block else "unblocked"
    return APIResponse(
        message=f"User {action_msg} successfully",
        data=MessageResponse(message=f"User {action_msg}")
    )
