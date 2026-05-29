from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import NotFoundException, BadRequestException
from app.models.security_model import LoginHistory
from app.repositories.security_repository import SecurityRepository
from app.repositories.audit_repository import AuditRepository
from app.schemas.security_schema import (
    LoginHistoryResponse,
    AuditLogResponse,
    BlockUserRequest,
)

class SecurityService:
    def __init__(self, db: AsyncSession):
        self.repo = SecurityRepository(db)
        self.audit_repo = AuditRepository(db)

    async def record_login(
        self,
        user_id: int | None,
        ip_address: str | None,
        user_agent: str | None,
        status: str,
        details: str | None = None
    ) -> None:
        log = LoginHistory(
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            status=status,
            details=details
        )
        await self.repo.create_login_history(log)

    async def list_login_history(self, skip: int = 0, limit: int = 100) -> list[LoginHistoryResponse]:
        histories = await self.repo.list_login_histories(skip, limit)
        return [
            LoginHistoryResponse(
                id=h.id,
                user_id=h.user_id,
                login_time=h.login_time,
                ip_address=h.ip_address,
                user_agent=h.user_agent,
                status=h.status,
                details=h.details,
                user_email=h.user.email if h.user else None
            )
            for h in histories
        ]

    async def list_audit_logs(self, skip: int = 0, limit: int = 100) -> list[AuditLogResponse]:
        logs = await self.repo.list_audit_logs(skip, limit)
        res: list[AuditLogResponse] = []
        for l in logs:
            email = None
            if l.user_id:
                user = await self.repo.get_user_by_id(l.user_id)
                email = user.email if user else None
            res.append(
                AuditLogResponse(
                    id=l.id,
                    user_id=l.user_id,
                    action=l.action,
                    resource=l.resource,
                    resource_id=l.resource_id,
                    details=l.details,
                    ip_address=l.ip_address,
                    created_at=l.created_at,
                    user_email=email
                )
            )
        return res

    async def block_user(self, data: BlockUserRequest, executor_id: int) -> None:
        user = await self.repo.get_user_by_id(data.user_id)
        if not user:
            raise NotFoundException("User not found")
        if user.id == executor_id:
            raise BadRequestException("You cannot block/unblock yourself")

        # is_active = False represents a blocked user
        user.is_active = not data.block
        await self.repo.update_user(user)

        action = "block_user" if data.block else "unblock_user"
        await self.audit_repo.create(action, "users", user_id=executor_id, resource_id=str(user.id))
