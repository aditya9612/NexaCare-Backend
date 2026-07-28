import asyncio

from app.celery_app import celery_app
from app.core.database import AsyncSessionLocal
from app.core.logger import logger
from app.services.notification_service import NotificationService


@celery_app.task(name="app.tasks.lab_tasks.check_pending_lab_tests")
def check_pending_lab_tests():
    asyncio.run(_check_pending_lab_tests())


async def _check_pending_lab_tests() -> None:
    async with AsyncSessionLocal() as db:
        try:
            count = await NotificationService(db).process_pending_test_reminders()
            await db.commit()
            logger.info("Processed %s pending lab test reminders", count)
        except Exception as exc:
            await db.rollback()
            logger.error("Pending lab test reminders task failed: %s", exc)
            raise
