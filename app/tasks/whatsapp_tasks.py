from app.celery_app import celery_app
from app.core.celery_async import run_celery_async
from app.core.database import AsyncSessionLocal
from app.core.logger import logger


import httpx

@celery_app.task(name="app.tasks.whatsapp_tasks.send_message_async", bind=True, max_retries=3, autoretry_for=(httpx.HTTPError, ConnectionError, TimeoutError), retry_backoff=True)
def send_message_async(self, message_id: int):
    run_celery_async(_send_message(message_id))


@celery_app.task(name="app.tasks.whatsapp_tasks.broadcast_campaign", bind=True, max_retries=2, autoretry_for=(httpx.HTTPError, ConnectionError, TimeoutError), retry_backoff=True)
def broadcast_campaign(self, campaign_id: int, phone_numbers: list[str]):
    run_celery_async(_broadcast(campaign_id, phone_numbers))


async def _send_message(message_id: int) -> None:
    from app.models.patient_model import Patient
    from app.models.whatsapp_model import WhatsAppMessage
    from app.services.module_service import ModuleService
    from app.services.whatsapp_service import WhatsAppService

    async with AsyncSessionLocal() as db:
        try:
            msg = await db.get(WhatsAppMessage, message_id)
            if msg and msg.patient_id:
                patient = await db.get(Patient, msg.patient_id)
                if patient and patient.hospital_id:
                    module_service = ModuleService(db)
                    if not await module_service.is_module_active(patient.hospital_id, "WHATSAPP"):
                        logger.warning(
                            "WhatsApp send aborted: Hospital %s does not have active WHATSAPP module.",
                            patient.hospital_id,
                        )
                        msg.delivery_status = "CANCELLED_NOT_ENTITLED"
                        await db.commit()
                        return

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
