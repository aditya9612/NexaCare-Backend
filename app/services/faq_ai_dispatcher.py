from sqlalchemy.ext.asyncio import AsyncSession
from app.core.logger import logger
from app.models.hospital_voice_model import HospitalFaq, HospitalPolicy, HospitalVoiceDocument
from app.tasks.faq_ai_tasks import (
    generate_faq_embedding,
    generate_policy_embedding,
    generate_document_embedding,
)

class FaqAiDispatcher:
    """
    Isolated dispatcher for FAQ AI background tasks.
    Ensures that database changes are committed BEFORE dispatching
    tasks to Celery, avoiding transaction-bound race conditions.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def dispatch_faq_update(self, faq: HospitalFaq) -> None:
        """Commits the current transaction and dispatches the FAQ embedding task."""
        await self.db.commit()
        try:
            generate_faq_embedding.delay(faq.id, faq.updated_at.isoformat())
        except Exception as exc:
            logger.error("Failed to dispatch Celery task for FAQ %s: %s", faq.id, exc, exc_info=True)

    async def dispatch_policy_update(self, policy: HospitalPolicy) -> None:
        await self.db.commit()
        try:
            generate_policy_embedding.delay(policy.id, policy.updated_at.isoformat())
        except Exception as exc:
            logger.error("Failed to dispatch Celery task for Policy %s: %s", policy.id, exc, exc_info=True)

    async def dispatch_document_update(self, doc: HospitalVoiceDocument) -> None:
        await self.db.commit()
        try:
            generate_document_embedding.delay(doc.id, doc.updated_at.isoformat())
        except Exception as exc:
            logger.error("Failed to dispatch Celery task for Document %s: %s", doc.id, exc, exc_info=True)

    async def dispatch_document_embedding(self, hospital_id: int, document_id: int) -> None:
        await self.db.commit()
        from app.tasks.faq_ai_tasks import embed_document_task
        embed_document_task.delay(hospital_id, document_id)

    async def dispatch_document_deactivation(self, hospital_id: int, document_id: int) -> None:
        await self.db.commit()
        from app.tasks.faq_ai_tasks import deactivate_document_task
        deactivate_document_task.delay(hospital_id, document_id)
