from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log_model import AuditLog


class AuditRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        action: str,
        resource: str,
        user_id: int | None = None,
        resource_id: str | None = None,
        details: str | None = None,
        ip_address: str | None = None,
    ) -> AuditLog:
        log = AuditLog(
            user_id=user_id,
            action=action,
            resource=resource,
            resource_id=resource_id,
            details=details,
            ip_address=ip_address,
        )
        self.db.add(log)
        await self.db.flush()
        return log
