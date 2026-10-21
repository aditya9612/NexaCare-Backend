from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification_model import Notification
from app.models.user_model import User
from app.utils.helpers import utc_now


class NotificationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _build_base_query(
        self,
        user_id: int,
        hospital_id: int | None = None,
        is_super_admin: bool = False,
        is_hospital_admin: bool = False,
    ):
        query = select(Notification).where(Notification.is_deleted.is_(False))

        if is_super_admin:
            if hospital_id is not None:
                # Scoped to a specific tenant via X-Hospital-Id
                query = query.where(
                    or_(
                        Notification.hospital_id == hospital_id,
                        and_(
                            Notification.hospital_id.is_(None),
                            Notification.user.has(User.hospital_id == hospital_id),
                        ),
                    )
                )
            else:
                # Global Super Admin view without header -> user's own notifications
                query = query.where(Notification.user_id == user_id)

        elif is_hospital_admin and hospital_id is not None:
            # Hospital Admin: see hospital notifications and own notifications
            query = query.where(
                or_(
                    Notification.hospital_id == hospital_id,
                    Notification.user_id == user_id,
                    and_(
                        Notification.hospital_id.is_(None),
                        Notification.user.has(User.hospital_id == hospital_id),
                    ),
                )
            )

        else:
            # Regular users: only own notifications within tenant
            query = query.where(Notification.user_id == user_id)
            if hospital_id is not None:
                query = query.where(
                    or_(
                        Notification.hospital_id == hospital_id,
                        Notification.hospital_id.is_(None),
                    )
                )

        return query

    def _apply_category_filter(self, query, category: str):
        cat = category.lower()
        if cat == "critical":
            query = query.where(
                (Notification.priority.in_(["CRITICAL", "HIGH"])) |
                (Notification.notification_type.in_([
                    "CRITICAL_VALUE", 
                    "CRITICAL_PATIENT_ALERT", 
                    "PATIENT_EMERGENCY_ALERT", 
                    "CRITICAL_ALERT"
                ]))
            )
        elif cat == "medication":
            query = query.where(Notification.notification_type == "MEDICATION_REMINDER")
        elif cat == "doctors":
            query = query.where(
                Notification.notification_type.in_(["DOCTOR_APPOINTMENT_REMINDER", "DOCTOR_INSTRUCTION"])
            )
        elif cat == "vitals":
            query = query.where(Notification.notification_type.in_(["CRITICAL_VALUE"]))
        elif cat == "updates":
            query = query.where(
                Notification.notification_type.in_(["PATIENT_UPDATE", "SHIFT_UPDATE", "PENDING_TEST"])
            )
        elif cat == "tasks":
            query = query.where(
                Notification.notification_type.in_(["TASK", "NURSE_TASK", "DOCTOR_INSTRUCTION"])
            )
        elif cat == "system":
            query = query.where(
                Notification.notification_type.in_(["SYSTEM", "QUEUE_ALERT"])
            )
        elif cat == "unread":
            query = query.where(Notification.is_read.is_(False))
        elif cat == "completed":
            query = query.where(Notification.is_read.is_(True))
        return query

    async def get_category_counts(
        self,
        user_id: int,
        hospital_id: int | None = None,
        is_super_admin: bool = False,
        is_hospital_admin: bool = False,
    ) -> dict[str, int]:
        categories = ["all", "critical", "medication", "doctors", "vitals", "updates", "tasks", "system", "unread", "completed"]
        counts = {}
        for cat in categories:
            query = (
                self._build_base_query(
                    user_id=user_id,
                    hospital_id=hospital_id,
                    is_super_admin=is_super_admin,
                    is_hospital_admin=is_hospital_admin,
                )
                .with_only_columns(func.count(Notification.id))
                .order_by(None)
            )
            if cat != "all":
                query = self._apply_category_filter(query, cat)
            result = await self.db.execute(query)
            counts[cat] = result.scalar() or 0
        return counts

    async def create(self, notification: Notification) -> Notification:
        self.db.add(notification)
        await self.db.flush()
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
        category: str | None = None,
        hospital_id: int | None = None,
        is_super_admin: bool = False,
        is_hospital_admin: bool = False,
    ) -> list[Notification]:
        query = self._build_base_query(
            user_id=user_id,
            hospital_id=hospital_id,
            is_super_admin=is_super_admin,
            is_hospital_admin=is_hospital_admin,
        )

        if is_read is not None:
            query = query.where(Notification.is_read.is_(is_read))
        if notification_type is not None:
            types = [t.strip() for t in notification_type.split(",") if t.strip()]
            if types:
                if len(types) == 1:
                    query = query.where(Notification.notification_type == types[0])
                else:
                    query = query.where(Notification.notification_type.in_(types))
        if category is not None:
            query = self._apply_category_filter(query, category)

        query = query.order_by(Notification.created_at.desc()).offset(skip).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count_user_notifications(
        self,
        user_id: int,
        is_read: bool | None = None,
        notification_type: str | None = None,
        category: str | None = None,
        hospital_id: int | None = None,
        is_super_admin: bool = False,
        is_hospital_admin: bool = False,
    ) -> int:
        query = (
            self._build_base_query(
                user_id=user_id,
                hospital_id=hospital_id,
                is_super_admin=is_super_admin,
                is_hospital_admin=is_hospital_admin,
            )
            .with_only_columns(func.count(Notification.id))
            .order_by(None)
        )

        if is_read is not None:
            query = query.where(Notification.is_read.is_(is_read))
        if notification_type is not None:
            types = [t.strip() for t in notification_type.split(",") if t.strip()]
            if types:
                if len(types) == 1:
                    query = query.where(Notification.notification_type == types[0])
                else:
                    query = query.where(Notification.notification_type.in_(types))
        if category is not None:
            query = self._apply_category_filter(query, category)

        result = await self.db.execute(query)
        return result.scalar() or 0

    async def get_unread_count(
        self,
        user_id: int,
        hospital_id: int | None = None,
        is_super_admin: bool = False,
        is_hospital_admin: bool = False,
    ) -> int:
        query = (
            self._build_base_query(
                user_id=user_id,
                hospital_id=hospital_id,
                is_super_admin=is_super_admin,
                is_hospital_admin=is_hospital_admin,
            )
            .where(Notification.is_read.is_(False))
            .with_only_columns(func.count(Notification.id))
            .order_by(None)
        )
        result = await self.db.execute(query)
        return result.scalar() or 0

    async def mark_as_read(self, notification_id: int, user_id: int) -> Notification | None:
        notification = await self.get_by_id(notification_id)
        if not notification or notification.user_id != user_id:
            return None

        notification.is_read = True
        notification.updated_at = utc_now()
        await self.db.flush()
        await self.db.refresh(notification)
        return notification

    async def mark_all_as_read(
        self,
        user_id: int,
        hospital_id: int | None = None,
        is_super_admin: bool = False,
        is_hospital_admin: bool = False,
    ) -> int:
        if is_super_admin and hospital_id is not None:
            stmt = (
                update(Notification)
                .where(
                    Notification.hospital_id == hospital_id,
                    Notification.is_read.is_(False),
                    Notification.is_deleted.is_(False),
                )
                .values(is_read=True, updated_at=utc_now())
            )
        elif is_hospital_admin and hospital_id is not None:
            stmt = (
                update(Notification)
                .where(
                    or_(
                        Notification.hospital_id == hospital_id,
                        Notification.user_id == user_id,
                    ),
                    Notification.is_read.is_(False),
                    Notification.is_deleted.is_(False),
                )
                .values(is_read=True, updated_at=utc_now())
            )
        else:
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
        count = await self.db.scalar(query)
        if isinstance(count, (int, float)):
            return count > 0
        return False
