import asyncio

from app.celery_app import celery_app
from app.core.celery_async import run_celery_async
from app.core.database import AsyncSessionLocal
from app.core.logger import logger


@celery_app.task(name="app.tasks.voice_tasks.execute_voice_call", bind=True, max_retries=3)
def execute_voice_call(self, call_id: int):
    try:
        run_celery_async(_execute_voice_call(call_id))
    except Exception as exc:
        logger.error("execute_voice_call failed call_id=%s: %s", call_id, exc, exc_info=True)
        raise self.retry(exc=exc, countdown=60)


@celery_app.task(name="app.tasks.voice_tasks.process_pending_calls")
def process_pending_calls():
    run_celery_async(_process_pending_calls())


@celery_app.task(name="app.tasks.voice_tasks.process_reception_callback_tickets")
def process_reception_callback_tickets():
    run_celery_async(_process_reception_callback_tickets())


async def _execute_voice_call(call_id: int) -> None:
    from app.services.voice_service import VoiceService

    async with AsyncSessionLocal() as db:
        try:
            service = VoiceService(db)
            await service.start_call_internal(call_id)
            await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.error("Voice call task failed for %s: %s", call_id, exc, exc_info=True)
            raise


async def _process_pending_calls() -> None:
    from app.services.voice_service import VoiceService

    async with AsyncSessionLocal() as db:
        try:
            service = VoiceService(db)
            pending = await service.repo.list_pending_calls(limit=20)
            for call in pending:
                await service.start_call_internal(call.id)
            await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.error("Pending voice calls task failed: %s", exc, exc_info=True)


async def _process_reception_callback_tickets() -> None:
    """Process queued reception callback tickets: notify staff + dial patient back."""
    from app.services.reception_transfer_service import ReceptionTransferService

    async with AsyncSessionLocal() as db:
        try:
            service = ReceptionTransferService(db)
            count = await service.process_queued_tickets(limit=20)
            await db.commit()
            logger.info("Processed %s reception callback tickets", count)
        except Exception as exc:
            await db.rollback()
            logger.error("Callback ticket processing failed: %s", exc, exc_info=True)
