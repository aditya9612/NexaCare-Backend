import logging
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pywebpush import webpush, WebPushException

from app.core.config import settings
from app.models.notification_model import PushSubscription
from app.schemas.notification_schema import PushSubscriptionCreate
from app.core.exceptions import NotFoundException

logger = logging.getLogger(__name__)

class PushNotificationService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def subscribe(self, user_id: int, payload: PushSubscriptionCreate) -> dict[str, str]:
        # Check if subscription already exists for this endpoint and user
        stmt = select(PushSubscription).where(
            PushSubscription.user_id == user_id,
            PushSubscription.endpoint == payload.endpoint
        )
        res = await self.db.execute(stmt)
        subscription = res.scalar_one_or_none()

        if subscription:
            # Update existing subscription keys and reactivate
            subscription.p256dh = payload.p256dh
            subscription.auth = payload.auth
            subscription.is_active = True
        else:
            # Create new subscription
            subscription = PushSubscription(
                user_id=user_id,
                endpoint=payload.endpoint,
                p256dh=payload.p256dh,
                auth=payload.auth,
                is_active=True
            )
            self.db.add(subscription)

        await self.db.commit()
        return {"message": "Successfully subscribed to push notifications"}

    async def unsubscribe(self, user_id: int, endpoint: str) -> dict[str, str]:
        stmt = select(PushSubscription).where(
            PushSubscription.user_id == user_id,
            PushSubscription.endpoint == endpoint
        )
        res = await self.db.execute(stmt)
        subscription = res.scalar_one_or_none()

        if not subscription:
            raise NotFoundException("Subscription not found")

        subscription.is_active = False
        await self.db.commit()
        return {"message": "Successfully unsubscribed from push notifications"}
