import json
import logging
from sqlalchemy import select
from pywebpush import webpush, WebPushException

from app.celery_app import celery_app
from app.core.celery_async import run_celery_async
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.notification_model import PushSubscription

logger = logging.getLogger(__name__)

async def _send_browser_push(user_id: int, title: str, message: str) -> None:
    if not settings.VAPID_PRIVATE_KEY or not settings.VAPID_PUBLIC_KEY:
        logger.info("VAPID keys not configured; skipping browser push.")
        return

    async with AsyncSessionLocal() as db:
        # Get active subscriptions for the user
        stmt = select(PushSubscription).where(
            PushSubscription.user_id == user_id,
            PushSubscription.is_active.is_(True)
        )
        res = await db.execute(stmt)
        subscriptions = res.scalars().all()

        if not subscriptions:
            return

        payload = json.dumps({
            "title": title,
            "body": message
        })

        for sub in subscriptions:
            try:
                subscription_info = {
                    "endpoint": sub.endpoint,
                    "keys": {
                        "p256dh": sub.p256dh,
                        "auth": sub.auth
                    }
                }

                # webpush is synchronous, so we just call it directly
                # Normally it does I/O synchronously, but it's okay inside Celery worker
                webpush(
                    subscription_info=subscription_info,
                    data=payload,
                    vapid_private_key=settings.VAPID_PRIVATE_KEY,
                    vapid_claims={"sub": settings.VAPID_CLAIM_EMAIL}
                )
            except WebPushException as ex:
                logger.warning(f"WebPush failed for endpoint {sub.endpoint}: {ex}")
                # 410 Gone or 404 Not Found means the subscription is no longer valid
                if ex.response is not None and ex.response.status_code in (404, 410):
                    logger.info(f"Deactivating invalid PushSubscription {sub.id}")
                    sub.is_active = False
                    await db.commit()
            except Exception as e:
                logger.error(f"Unexpected error sending push to {sub.endpoint}: {e}")

@celery_app.task(name="app.tasks.notification_tasks.send_browser_push_async", bind=True, max_retries=3)
def send_browser_push_async(self, user_id: int, title: str, message: str) -> None:
    try:
        run_celery_async(_send_browser_push(user_id, title, message))
    except Exception as exc:
        logger.error(f"Failed to send browser push: {exc}")
        self.retry(exc=exc, countdown=10)
