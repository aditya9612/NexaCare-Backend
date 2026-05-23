import asyncio

from app.celery_app import celery_app
from app.core.logger import logger


@celery_app.task(name="app.tasks.chat_tasks.persist_session_snapshot")
def persist_session_snapshot(session_id: str):
    asyncio.run(_persist_snapshot(session_id))


async def _persist_snapshot(session_id: str) -> None:
    from app.core.database import AsyncSessionLocal
    from app.services.chat_service import ChatService
    from app.utils.redis_service import cache_get

    snapshot = await cache_get(f"chat:session:{session_id}")
    if not snapshot:
        return
    async with AsyncSessionLocal() as db:
        try:
            service = ChatService(db)
            await service.sync_redis_snapshot(session_id, snapshot)
            await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.error("Chat snapshot persist failed for %s: %s", session_id, exc)
