from datetime import date, timedelta

from app.celery_app import celery_app
from app.core.celery_async import run_celery_async
from app.core.database import AsyncSessionLocal
from app.core.logger import logger
from app.services.reminder_orchestrator import ReminderOrchestrator


@celery_app.task(name="app.tasks.reminder_tasks.schedule_appointment_voice_reminders")
def schedule_appointment_voice_reminders():
    run_celery_async(_schedule_voice_reminders())


async def _schedule_voice_reminders() -> None:
    target = date.today() + timedelta(days=1)
    async with AsyncSessionLocal() as db:
        try:
            count = await ReminderOrchestrator(db).schedule_voice_reminders_for_date(target)
            await db.commit()
            logger.info("Scheduled %s voice reminders for %s", count, target)
        except Exception as exc:
            await db.rollback()
            logger.error("Voice reminder scheduling failed: %s", exc)
            raise


@celery_app.task(name="app.tasks.reminder_tasks.process_doctor_appointment_reminders")
def process_doctor_appointment_reminders():
    run_celery_async(_process_doctor_appointment_reminders())


async def _process_doctor_appointment_reminders() -> None:
    from app.services.notification_service import NotificationService
    async with AsyncSessionLocal() as db:
        try:
            count = await NotificationService(db).process_doctor_appointment_reminders()
            await db.commit()
            logger.info("Processed %s doctor appointment reminders", count)
        except Exception as exc:
            await db.rollback()
            logger.error("Doctor appointment reminder processing failed: %s", exc)
            raise


@celery_app.task(name="app.tasks.reminder_tasks.process_medication_reminders")
def process_medication_reminders():
    run_celery_async(_process_medication_reminders())


async def _process_medication_reminders() -> None:
    from app.services.notification_service import NotificationService
    async with AsyncSessionLocal() as db:
        try:
            count = await NotificationService(db).process_medication_reminders()
            await db.commit()
            logger.info("Processed %s medication reminders", count)
        except Exception as exc:
            await db.rollback()
            logger.error("Medication reminder processing failed: %s", exc)
            raise
