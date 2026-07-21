from app.celery_app import celery_app
from app.core.celery_async import run_celery_async
from app.core.database import AsyncSessionLocal
from app.core.logger import logger


@celery_app.task(name="app.tasks.analytics_tasks.generate_export", bind=True, max_retries=2)
def generate_export(self, export_id: int):
    run_celery_async(_generate_export(export_id))


@celery_app.task(name="app.tasks.analytics_tasks.refresh_dashboard_cache")
def refresh_dashboard_cache():
    run_celery_async(_refresh_cache())


async def _generate_export(export_id: int) -> None:
    from app.services.analytics_service import AnalyticsService

    async with AsyncSessionLocal() as db:
        try:
            await AnalyticsService(db).process_export(export_id)
            await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.error("Export task failed for %s: %s", export_id, exc)
            raise


async def _refresh_cache() -> None:
    from app.services.analytics_service import AnalyticsService

    async with AsyncSessionLocal() as db:
        try:
            await AnalyticsService(db).cache_dashboard_summary()
            await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.error("Dashboard cache refresh failed: %s", exc)
