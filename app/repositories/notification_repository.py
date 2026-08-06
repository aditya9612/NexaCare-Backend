from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification_model import Notification
from app.utils.helpers import utc_now


class NotificationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, notification: Notification) -> Notification:
        self.db.add(notification)
        await self.db.commit()
        await self.db.refresh(notification)
        return notification

    async def get_by_id(self, notification_id: int) -> Notification | None:
        result = await self.db.execute(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.is_deleted.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def list_user_notifications(
        self,
        user_id: int,
        skip: int = 0,
        limit: int = 20,
        is_read: bool | None = None,
        notification_type: str | None = None,
    ) -> list[Notification]:
        query = select(Notification).where(
            Notification.user_id == user_id,
            Notification.is_deleted.is_(False),
        )

        if is_read is not None:
            query = query.where(Notification.is_read.is_(is_read))
        if notification_type is not None:
            query = query.where(Notification.notification_type == notification_type)

        query = query.order_by(Notification.created_at.desc()).offset(skip).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count_user_notifications(
        self,
        user_id: int,
        is_read: bool | None = None,
        notification_type: str | None = None,
    ) -> int:
        query = select(func.count(Notification.id)).where(
            Notification.user_id == user_id,
            Notification.is_deleted.is_(False),
        )

        if is_read is not None:
            query = query.where(Notification.is_read.is_(is_read))
        if notification_type is not None:
            query = query.where(Notification.notification_type == notification_type)

        result = await self.db.execute(query)
        return result.scalar() or 0

    async def get_unread_count(self, user_id: int) -> int:
        result = await self.db.execute(
            select(func.count(Notification.id)).where(
                Notification.user_id == user_id,
                Notification.is_read.is_(False),
                Notification.is_deleted.is_(False),
            )
        )
        return result.scalar() or 0

    async def mark_as_read(self, notification_id: int, user_id: int) -> Notification | None:
        notification = await self.get_by_id(notification_id)
        if not notification or notification.user_id != user_id:
            return None

        notification.is_read = True
        notification.updated_at = utc_now()
        await self.db.commit()
        await self.db.refresh(notification)
        return notification

    async def mark_all_as_read(self, user_id: int) -> int:
        stmt = (
            update(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.is_read.is_(False),
                Notification.is_deleted.is_(False),
            )
            .values(is_read=True, updated_at=utc_now())
        )
        result = await self.db.execute(stmt)
        await self.db.commit()
        return result.rowcount

    async def exists_duplicate(
        self,
        user_id: int,
        notification_type: str,
        reference_type: str | None,
        reference_id: int | None,
    ) -> bool:
        if reference_type is None or reference_id is None:
            return False

        query = select(func.count(Notification.id)).where(
            Notification.user_id == user_id,
            Notification.notification_type == notification_type,
            Notification.reference_type == reference_type,
            Notification.reference_id == reference_id,
            Notification.is_deleted.is_(False),
        )
        result = await self.db.execute(query)
        count = result.scalar() or 0
        return count > 0
