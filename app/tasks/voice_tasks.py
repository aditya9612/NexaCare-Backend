import asyncio

from app.celery_app import celery_app
from app.core.database import AsyncSessionLocal
from app.core.logger import logger


@celery_app.task(name="app.tasks.voice_tasks.execute_voice_call", bind=True, max_retries=3)
def execute_voice_call(self, call_id: int):
    asyncio.run(_execute_voice_call(call_id))


@celery_app.task(name="app.tasks.voice_tasks.process_pending_calls")
def process_pending_calls():
    asyncio.run(_process_pending_calls())


async def _execute_voice_call(call_id: int) -> None:
    from app.services.voice_service import VoiceService

    async with AsyncSessionLocal() as db:
        try:
            service = VoiceService(db)
            await service.start_call_internal(call_id)
            await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.error("Voice call task failed for %s: %s", call_id, exc)
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
            logger.error("Pending voice calls task failed: %s", exc)
