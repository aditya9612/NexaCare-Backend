from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from app.models.security_model import LoginHistory
from app.models.audit_log_model import AuditLog
from app.models.user_model import User

class SecurityRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_login_history(self, log: LoginHistory) -> LoginHistory:
        self.db.add(log)
        await self.db.flush()
        await self.db.refresh(log)
        return log

    async def list_login_histories(self, skip: int = 0, limit: int = 100) -> list[LoginHistory]:
        result = await self.db.execute(
            select(LoginHistory)
            .options(joinedload(LoginHistory.user))
            .order_by(desc(LoginHistory.login_time))
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_audit_logs(self, skip: int = 0, limit: int = 100) -> list[AuditLog]:
        result = await self.db.execute(
            select(AuditLog)
            .order_by(desc(AuditLog.created_at))
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_user_by_id(self, user_id: int) -> User | None:
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def update_user(self, user: User) -> User:
        await self.db.flush()
        await self.db.refresh(user)
        return user
