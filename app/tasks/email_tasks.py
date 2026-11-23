from typing import Any
from app.celery_app import celery_app
from app.core.celery_async import run_celery_async
from app.core.constants import EmailMessageType
from app.core.database import AsyncSessionLocal
from app.core.logger import logger
from app.schemas.email_schema import (
    SendEmailReminderRequest,
    SendMediaEmailRequest,
    SendTemplateEmailRequest,
)
from app.utils.helpers import utc_now


@celery_app.task(name="app.tasks.email_tasks.send_batch_email_reminders_task", bind=True, max_retries=2)
def send_batch_email_reminders_task(
    self,
    batch_id: str,
    hospital_id: int | None,
    patient_ids: list[int],
    custom_notes: str | None = None,
):
    run_celery_async(_send_batch_reminders(batch_id, hospital_id, patient_ids, custom_notes))


async def _send_batch_reminders(
    batch_id: str,
    hospital_id: int | None,
    patient_ids: list[int],
    custom_notes: str | None,
) -> None:
    from app.services.email_service import EmailService

    async with AsyncSessionLocal() as db:
        try:
            service = EmailService(db)
            # Update batch to PROCESSING
            batch = await service.repo.get_batch(batch_id)
            if batch:
                batch.status = "PROCESSING"
                await db.flush()

            results = []
            sent_count = 0
            failed_count = 0
            skipped_count = 0

            for pid in patient_ids:
                res = await service._process_single_patient_reminder(
                    batch_id=batch_id,
                    hospital_id=hospital_id,
                    patient_id=pid,
                    custom_notes=custom_notes,
                )
                results.append(res)
                if res.status == "SENT":
                    sent_count += 1
                elif res.status == "SKIPPED":
                    skipped_count += 1
                else:
                    failed_count += 1

            await service.repo.update_batch_summary(
                batch_id=batch_id,
                sent_count=sent_count,
                failed_count=failed_count,
                skipped_count=skipped_count,
                results_summary={"results": [r.model_dump(mode="json") for r in results]},
                status="COMPLETED",
            )
            await db.commit()
            logger.info("Batch reminders %s finished: %s sent, %s skipped, %s failed", batch_id, sent_count, skipped_count, failed_count)
        except Exception as exc:
            await db.rollback()
            logger.error("Async batch reminders task failed for batch %s: %s", batch_id, exc, exc_info=True)
            raise


@celery_app.task(name="app.tasks.email_tasks.send_batch_template_task", bind=True, max_retries=2)
def send_batch_template_task(
    self,
    batch_id: str,
    hospital_id: int | None,
    patient_ids: list[int],
    template_name: str,
    language: str,
    variables: dict[str, Any],
):
    run_celery_async(_send_batch_template(batch_id, hospital_id, patient_ids, template_name, language, variables))


async def _send_batch_template(
    batch_id: str,
    hospital_id: int | None,
    patient_ids: list[int],
    template_name: str,
    language: str,
    variables: dict[str, Any],
) -> None:
    from app.services.email_service import EmailService

    async with AsyncSessionLocal() as db:
        try:
            service = EmailService(db)
            batch = await service.repo.get_batch(batch_id)
            if batch:
                batch.status = "PROCESSING"
                await db.flush()

            template = await service.repo.get_template_by_name(template_name, hospital_id, language)

            results = []
            sent_count = 0
            failed_count = 0
            skipped_count = 0

            for pid in patient_ids:
                res = await service._process_single_patient_template(
                    batch_id=batch_id,
                    hospital_id=hospital_id,
                    patient_id=pid,
                    template=template,
                    template_name=template_name,
                    raw_variables=variables,
                )
                results.append(res)
                if res.status == "SENT":
                    sent_count += 1
                elif res.status == "SKIPPED":
                    skipped_count += 1
                else:
                    failed_count += 1

            await service.repo.update_batch_summary(
                batch_id=batch_id,
                sent_count=sent_count,
                failed_count=failed_count,
                skipped_count=skipped_count,
                results_summary={"results": [r.model_dump(mode="json") for r in results]},
                status="COMPLETED",
            )
            await db.commit()
            logger.info("Batch template %s finished: %s sent, %s skipped, %s failed", batch_id, sent_count, skipped_count, failed_count)
        except Exception as exc:
            await db.rollback()
            logger.error("Async batch template task failed for batch %s: %s", batch_id, exc, exc_info=True)
            raise


@celery_app.task(name="app.tasks.email_tasks.send_batch_media_task", bind=True, max_retries=2)
def send_batch_media_task(
    self,
    batch_id: str,
    hospital_id: int | None,
    patient_ids: list[int],
    message_type: str,
    media_url: str,
    caption: str | None,
):
    run_celery_async(_send_batch_media(batch_id, hospital_id, patient_ids, message_type, media_url, caption))


async def _send_batch_media(
    batch_id: str,
    hospital_id: int | None,
    patient_ids: list[int],
    message_type: str,
    media_url: str,
    caption: str | None,
) -> None:
    from app.services.email_service import EmailService

    async with AsyncSessionLocal() as db:
        try:
            service = EmailService(db)
            batch = await service.repo.get_batch(batch_id)
            if batch:
                batch.status = "PROCESSING"
                await db.flush()

            msg_type_enum = EmailMessageType(message_type) if message_type in EmailMessageType.__members__.values() else EmailMessageType.PDF

            results = []
            sent_count = 0
            failed_count = 0
            skipped_count = 0

            for pid in patient_ids:
                res = await service._process_single_patient_media(
                    batch_id=batch_id,
                    hospital_id=hospital_id,
                    patient_id=pid,
                    message_type=msg_type_enum,
                    media_url=media_url,
                    caption=caption,
                )
                results.append(res)
                if res.status == "SENT":
                    sent_count += 1
                elif res.status == "SKIPPED":
                    skipped_count += 1
                else:
                    failed_count += 1

            await service.repo.update_batch_summary(
                batch_id=batch_id,
                sent_count=sent_count,
                failed_count=failed_count,
                skipped_count=skipped_count,
                results_summary={"results": [r.model_dump(mode="json") for r in results]},
                status="COMPLETED",
            )
            await db.commit()
            logger.info("Batch media %s finished: %s sent, %s skipped, %s failed", batch_id, sent_count, skipped_count, failed_count)
        except Exception as exc:
            await db.rollback()
            logger.error("Async batch media task failed for batch %s: %s", batch_id, exc, exc_info=True)
            raise


@celery_app.task(name="app.tasks.email_tasks.broadcast_email_campaign_task", bind=True, max_retries=2)
def broadcast_email_campaign_task(self, campaign_id: int, emails: list[str], hospital_id: int | None):
    run_celery_async(_broadcast(campaign_id, emails, hospital_id))


async def _broadcast(campaign_id: int, emails: list[str], hospital_id: int | None) -> None:
    from app.services.email_service import EmailService

    async with AsyncSessionLocal() as db:
        try:
            service = EmailService(db)
            await service.execute_broadcast_campaign(campaign_id, emails, hospital_id)
        except Exception as exc:
            await db.rollback()
            logger.error("Async broadcast failed for campaign %s: %s", campaign_id, exc, exc_info=True)
            raise


@celery_app.task(name="app.tasks.email_tasks.check_due_scheduled_campaigns")
def check_due_scheduled_campaigns():
    """Periodic Celery Beat task: sweep scheduled campaigns that have reached scheduled_at."""
    run_celery_async(_check_due_campaigns())


async def _check_due_campaigns() -> None:
    from app.services.email_service import EmailService

    now = utc_now()
    async with AsyncSessionLocal() as db:
        try:
            service = EmailService(db)
            due_campaigns = await service.repo.get_due_scheduled_campaigns(now)
            for campaign in due_campaigns:
                logger.info("Triggering due scheduled email campaign %s (%s)", campaign.id, campaign.campaign_name)
                # Mark queued and trigger broadcast
                campaign.status = "QUEUED"
                await db.flush()
                # For broadcast campaign, we trigger execution
                broadcast_email_campaign_task.delay(
                    campaign_id=campaign.id,
                    emails=[],  # will fetch from campaign or recipients
                    hospital_id=campaign.hospital_id,
                )
            await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.error("Failed checking due email campaigns: %s", exc, exc_info=True)

