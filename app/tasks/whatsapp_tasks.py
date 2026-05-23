import asyncio

from app.celery_app import celery_app
from app.core.database import AsyncSessionLocal
from app.core.logger import logger


@celery_app.task(name="app.tasks.whatsapp_tasks.send_message_async", bind=True, max_retries=3)
def send_message_async(self, message_id: int):
    asyncio.run(_send_message(message_id))


@celery_app.task(name="app.tasks.whatsapp_tasks.broadcast_campaign", bind=True, max_retries=2)
def broadcast_campaign(self, campaign_id: int, phone_numbers: list[str]):
    asyncio.run(_broadcast(campaign_id, phone_numbers))


async def _send_message(message_id: int) -> None:
    from app.services.whatsapp_service import WhatsAppService

    async with AsyncSessionLocal() as db:
        try:
            await WhatsAppService(db).dispatch_message(message_id)
            await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.error("WhatsApp send task failed for %s: %s", message_id, exc)
            raise


async def _broadcast(campaign_id: int, phone_numbers: list[str]) -> None:
    from app.services.whatsapp_service import WhatsAppService

    async with AsyncSessionLocal() as db:
        try:
            await WhatsAppService(db).process_broadcast(campaign_id, phone_numbers)
            await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.error("WhatsApp broadcast failed for campaign %s: %s", campaign_id, exc)
            raise
