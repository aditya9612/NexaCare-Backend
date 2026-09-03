"""
faq_ai_tasks.py — Celery tasks for async FAQ / Policy / Document embedding.

Phase 2: Move embedding generation out of the synchronous API request path.

Isolation guarantee:
  - This is a NEW file. No existing production files are modified by this module.
  - Voice Assistant code is NOT touched.
  - RAG / KnowledgeRetriever / RagFaqService are NOT modified.
  - EmbeddingStore / KnowledgeEmbedding schema are NOT changed.
  - The existing sync_faq_embedding / sync_policy_embedding / sync_document_embedding
    functions in knowledge_embedding_sync.py are REUSED as-is (not replaced).

Stale-task protection:
  HospitalFaq.updated_at (from TimestampMixin) is recorded in the task payload
  at dispatch time. When the task runs it re-fetches the FAQ from the DB and
  compares updated_at. If the DB row is newer, the task is a stale remnant of
  an earlier FAQ version and must be discarded WITHOUT touching KnowledgeEmbedding
  or Redis. This prevents race conditions where Task-A (old version) would
  overwrite the embedding written by Task-B (new version).

Retry policy:
  max_retries=3, countdown=30s — consistent with voice_tasks.py pattern.
  Transient OpenAI errors are retried; the task does NOT silently swallow them.

Idempotency:
  EmbeddingStore.upsert_kb_entry already performs a content_hash check.
  Running the same task twice on the same FAQ content is safe.

Redis invalidation:
  Cache is invalidated ONLY after EmbeddingStore.upsert_kb_entry succeeds.
  If embedding generation fails, no cache invalidation occurs, so the old
  cached vectors remain valid rather than causing a cold-rebuild from a
  potentially stale DB row.
"""

from __future__ import annotations

from datetime import datetime

from app.celery_app import celery_app
from app.core.celery_async import run_celery_async
from app.core.database import AsyncSessionLocal
from app.core.logger import logger
from app.repositories.hospital_voice_repository import (
    HospitalFaqRepository,
    HospitalPolicyRepository,
    HospitalVoiceDocumentRepository,
)
from app.services.faq_retrieval_service import FaqRetrievalService
from app.services.knowledge_embedding_sync import (
    sync_document_embedding,
    sync_faq_embedding,
    sync_policy_embedding,
)



# ---------------------------------------------------------------------------
# FAQ embedding task
# ---------------------------------------------------------------------------

@celery_app.task(
    name="app.tasks.faq_ai_tasks.generate_faq_embedding",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    ignore_result=True,
)
def generate_faq_embedding(self, faq_id: int, dispatched_updated_at: str) -> None:
    """
    Async-safe Celery task to generate/update the embedding for a single FAQ.

    Args:
        faq_id: Primary key of the HospitalFaq row.
        dispatched_updated_at: ISO-format UTC timestamp of faq.updated_at at
                               dispatch time — used for stale-task detection.
    """
    try:
        run_celery_async(_generate_faq_embedding(faq_id, dispatched_updated_at))
    except Exception as exc:
        logger.error(
            "generate_faq_embedding failed faq_id=%s: %s", faq_id, exc, exc_info=True
        )
        raise self.retry(exc=exc, countdown=30)


async def _generate_faq_embedding(faq_id: int, dispatched_updated_at: str) -> None:
    """Inner async implementation for generate_faq_embedding Celery task."""
    async with AsyncSessionLocal() as db:
        try:
            faq_repo = HospitalFaqRepository(db)
            faq = await faq_repo.get_by_id(faq_id)

            # Safety check 1: FAQ deleted or deactivated since dispatch.
            if not faq or not faq.is_active:
                logger.info(
                    "generate_faq_embedding: faq_id=%s not found or inactive — skipping",
                    faq_id,
                )
                return

            # Safety check 2: Stale-task detection via updated_at.
            # If the DB row has been updated AFTER this task was dispatched,
            # a newer task is responsible for the embedding. Discard this one.
            try:
                dispatch_dt = datetime.fromisoformat(dispatched_updated_at)
            except (ValueError, TypeError):
                dispatch_dt = None

            if dispatch_dt is not None and faq.updated_at > dispatch_dt:
                logger.info(
                    "generate_faq_embedding: faq_id=%s is stale "
                    "(task updated_at=%s < db updated_at=%s) — skipping",
                    faq_id,
                    dispatched_updated_at,
                    faq.updated_at.isoformat(),
                )
                return

            # Delegate to the existing embedding sync function (reuse, don't replace).
            await sync_faq_embedding(db, faq)

            # Invalidate Redis ONLY after a successful embedding upsert.
            await FaqRetrievalService(db).invalidate_cache(faq.hospital_id)

            await db.commit()
            logger.info("generate_faq_embedding: faq_id=%s embedding updated", faq_id)

        except Exception as exc:
            await db.rollback()
            logger.error(
                "generate_faq_embedding inner task failed faq_id=%s: %s",
                faq_id, exc, exc_info=True,
            )
            raise



# ---------------------------------------------------------------------------
# Policy embedding task
# ---------------------------------------------------------------------------

@celery_app.task(
    name="app.tasks.faq_ai_tasks.generate_policy_embedding",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    ignore_result=True,
)
def generate_policy_embedding(self, policy_id: int, dispatched_updated_at: str) -> None:
    """
    Async-safe Celery task to generate/update the embedding for a single Policy.

    Args:
        policy_id: Primary key of the HospitalPolicy row.
        dispatched_updated_at: ISO-format UTC timestamp at dispatch time.
    """
    try:
        run_celery_async(_generate_policy_embedding(policy_id, dispatched_updated_at))
    except Exception as exc:
        logger.error(
            "generate_policy_embedding failed policy_id=%s: %s",
            policy_id, exc, exc_info=True,
        )
        raise self.retry(exc=exc, countdown=30)


async def _generate_policy_embedding(policy_id: int, dispatched_updated_at: str) -> None:
    """Inner async implementation for generate_policy_embedding Celery task."""
    async with AsyncSessionLocal() as db:
        try:
            repo = HospitalPolicyRepository(db)
            policy = await repo.get_by_id(policy_id)

            if not policy or not policy.is_active:
                logger.info(
                    "generate_policy_embedding: policy_id=%s not found or inactive — skipping",
                    policy_id,
                )
                return

            try:
                dispatch_dt = datetime.fromisoformat(dispatched_updated_at)
            except (ValueError, TypeError):
                dispatch_dt = None

            if dispatch_dt is not None and policy.updated_at > dispatch_dt:
                logger.info(
                    "generate_policy_embedding: policy_id=%s stale task — skipping",
                    policy_id,
                )
                return

            await sync_policy_embedding(db, policy)
            await FaqRetrievalService(db).invalidate_cache(policy.hospital_id)
            await db.commit()
            logger.info(
                "generate_policy_embedding: policy_id=%s embedding updated", policy_id
            )

        except Exception as exc:
            await db.rollback()
            logger.error(
                "generate_policy_embedding inner failed policy_id=%s: %s",
                policy_id, exc, exc_info=True,
            )
            raise



# ---------------------------------------------------------------------------
# Document embedding task
# ---------------------------------------------------------------------------

@celery_app.task(
    name="app.tasks.faq_ai_tasks.generate_document_embedding",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    ignore_result=True,
)
def generate_document_embedding(self, doc_id: int, dispatched_updated_at: str) -> None:
    """
    Async-safe Celery task to generate/update the embedding for a single Document.

    Args:
        doc_id: Primary key of the HospitalVoiceDocument row.
        dispatched_updated_at: ISO-format UTC timestamp at dispatch time.
    """
    try:
        run_celery_async(_generate_document_embedding(doc_id, dispatched_updated_at))
    except Exception as exc:
        logger.error(
            "generate_document_embedding failed doc_id=%s: %s",
            doc_id, exc, exc_info=True,
        )
        raise self.retry(exc=exc, countdown=30)


async def _generate_document_embedding(doc_id: int, dispatched_updated_at: str) -> None:
    """Inner async implementation for generate_document_embedding Celery task."""
    async with AsyncSessionLocal() as db:
        try:
            repo = HospitalVoiceDocumentRepository(db)
            doc = await repo.get_by_id(doc_id)

            if not doc or not doc.is_active:
                logger.info(
                    "generate_document_embedding: doc_id=%s not found or inactive — skipping",
                    doc_id,
                )
                return

            try:
                dispatch_dt = datetime.fromisoformat(dispatched_updated_at)
            except (ValueError, TypeError):
                dispatch_dt = None

            if dispatch_dt is not None and doc.updated_at > dispatch_dt:
                logger.info(
                    "generate_document_embedding: doc_id=%s stale task — skipping",
                    doc_id,
                )
                return

            await sync_document_embedding(db, doc)
            await FaqRetrievalService(db).invalidate_cache(doc.hospital_id)
            await db.commit()
            logger.info(
                "generate_document_embedding: doc_id=%s embedding updated", doc_id
            )

        except Exception as exc:
            await db.rollback()
            logger.error(
                "generate_document_embedding inner failed doc_id=%s: %s",
                doc_id, exc, exc_info=True,
            )
            raise

# ---------------------------------------------------------------------------
# Document Deactivation Task
# ---------------------------------------------------------------------------
@celery_app.task(
    name="app.tasks.faq_ai_tasks.deactivate_document_task",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    ignore_result=True,
)
def deactivate_document_task(self, hospital_id: int, document_id: int) -> None:
    try:
        run_celery_async(_deactivate_document_task(hospital_id, document_id))
    except Exception as exc:
        logger.error(f"deactivate_document_task failed doc_id={document_id}: {exc}")
        raise self.retry(exc=exc, countdown=30)

async def _deactivate_document_task(hospital_id: int, document_id: int) -> None:
    async with AsyncSessionLocal() as db:
        try:
            from app.ai.embeddings.store import EmbeddingStore
            from app.repositories.hospital_voice_document_chunk_repository import HospitalVoiceDocumentChunkRepository
            store = EmbeddingStore(db)
            
            chunk_repo = HospitalVoiceDocumentChunkRepository(db)
            chunks = await chunk_repo.list_by_document(document_id)
            
            for chunk in chunks:
                await store.deactivate_entry("document_chunk", chunk.id, hospital_id)
                
            await store.deactivate_entry("document", document_id, hospital_id)
            await db.commit()
            logger.info(f"deactivate_document_task complete doc_id={document_id}")
        except Exception as exc:
            await db.rollback()
            logger.error(f"deactivate_document_task failed: {exc}")
            raise


# ---------------------------------------------------------------------------
# Document Chunk embedding tasks (Phase 3C)
# ---------------------------------------------------------------------------

@celery_app.task(
    name="app.tasks.faq_ai_tasks.embed_document_task",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    ignore_result=True,
)
def embed_document_task(self, hospital_id: int, document_id: int) -> None:
    try:
        run_celery_async(_embed_document_task(hospital_id, document_id))
    except Exception as exc:
        logger.error(f"embed_document_task failed doc_id={document_id}: {exc}")
        raise self.retry(exc=exc, countdown=30)

async def _embed_document_task(hospital_id: int, document_id: int) -> None:
    async with AsyncSessionLocal() as db:
        try:
            from app.repositories.hospital_voice_document_chunk_repository import HospitalVoiceDocumentChunkRepository
            from app.repositories.hospital_voice_repository import HospitalVoiceDocumentRepository
            
            doc_repo = HospitalVoiceDocumentRepository(db)
            doc = await doc_repo.get_by_id(document_id)
            if not doc or not doc.is_active or doc.hospital_id != hospital_id:
                logger.info(f"embed_document_task: doc_id={document_id} inactive or deleted. Skipping.")
                return

            chunk_repo = HospitalVoiceDocumentChunkRepository(db)
            chunks = await chunk_repo.list_by_document(document_id)
            
            for chunk in chunks:
                embed_document_chunk_task.delay(hospital_id, chunk.id)
                
            logger.info(f"embed_document_task: Dispatched {len(chunks)} chunks for doc_id={document_id}")
        except Exception as exc:
            logger.error(f"embed_document_task inner failed: {exc}")
            raise

@celery_app.task(
    name="app.tasks.faq_ai_tasks.embed_document_chunk_task",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    ignore_result=True,
)
def embed_document_chunk_task(self, hospital_id: int, chunk_id: int) -> None:
    is_retry = self.request.retries > 0
    try:
        run_celery_async(_embed_document_chunk_task(hospital_id, chunk_id, is_retry=is_retry))
    except Exception as exc:
        is_final = self.request.retries >= self.max_retries
        if is_final:
            try:
                run_celery_async(_set_chunk_failed(chunk_id, str(exc)))
            except Exception as inner_exc:
                logger.error(f"Failed to set chunk status to failed for chunk_id={chunk_id}: {inner_exc}")
        logger.error(f"embed_document_chunk_task failed chunk_id={chunk_id}: {exc}")
        raise self.retry(exc=exc, countdown=30)

async def _set_chunk_failed(chunk_id: int, error_msg: str) -> None:
    async with AsyncSessionLocal() as db:
        from sqlalchemy import select
        from app.models.hospital_voice_document_chunk import HospitalVoiceDocumentChunk
        stmt = select(HospitalVoiceDocumentChunk).where(HospitalVoiceDocumentChunk.id == chunk_id)
        result = await db.execute(stmt)
        chunk = result.scalar_one_or_none()
        if chunk:
            chunk.embedding_status = "failed"
            chunk.embedding_error = error_msg[:2000] if error_msg else None
            await db.commit()

async def _embed_document_chunk_task(hospital_id: int, chunk_id: int, is_retry: bool = False) -> None:
    async with AsyncSessionLocal() as db:
        try:
            from sqlalchemy import select
            from app.models.hospital_voice_document_chunk import HospitalVoiceDocumentChunk
            from app.models.hospital_voice_model import HospitalVoiceDocument
            from app.ai.embeddings.store import EmbeddingStore
            from app.services.faq_retrieval_service import FaqRetrievalService
            from sqlalchemy.orm import selectinload
            
            stmt = (
                select(HospitalVoiceDocumentChunk)
                .options(selectinload(HospitalVoiceDocumentChunk.document))
                .where(HospitalVoiceDocumentChunk.id == chunk_id)
            )
            result = await db.execute(stmt)
            chunk = result.scalar_one_or_none()
            
            if not chunk or not chunk.document or not chunk.document.is_active:
                logger.info(f"embed_document_chunk_task: chunk_id={chunk_id} not found or inactive. Skipping.")
                return
                
            chunk.embedding_status = "processing"
            chunk.embedding_error = None
            await db.commit()
                
            store = EmbeddingStore(db)
            
            title = chunk.document.title or ""
            label = f"[document_chunk:{chunk.id}] Title: {title}\nContent: {chunk.text}"
            embed_text = f"{title}\n{chunk.text}".strip()
            
            await store.upsert_kb_entry(
                hospital_id=hospital_id,
                source_type="document_chunk",
                source_id=chunk.id,
                language=chunk.document.language or "en",
                embed_text=embed_text,
                answer_text=chunk.text,
                label=label,
            )
            
            await FaqRetrievalService(db).invalidate_cache(hospital_id)
            
            chunk.embedding_status = "completed"
            await db.commit()
            
            logger.info(f"embed_document_chunk_task: chunk_id={chunk_id} embedding complete")
        except Exception as exc:
            await db.rollback()
            logger.error(f"embed_document_chunk_task inner failed: {exc}")
            raise


