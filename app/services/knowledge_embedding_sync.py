"""
Sync helpers: push FAQ/policy/document rows into knowledge_embeddings.

Called from HospitalKnowledgeService after CRUD. Failures are logged and do
not block admin CRUD (embeddings lazy-backfill on next retrieve).
"""

from __future__ import annotations

from app.ai.embeddings.store import (
    EmbeddingStore,
    build_embed_text,
    label_for_entry,
)
from app.core.logger import logger
from app.models.hospital_voice_model import HospitalFaq, HospitalPolicy, HospitalVoiceDocument
from sqlalchemy.ext.asyncio import AsyncSession


async def sync_faq_embedding(db: AsyncSession, faq: HospitalFaq) -> None:
    try:
        store = EmbeddingStore(db)
        await store.upsert_kb_entry(
            hospital_id=faq.hospital_id,
            source_type="faq",
            source_id=faq.id,
            language=faq.language or "en",
            embed_text=build_embed_text(
                "faq",
                question=faq.question,
                tags=faq.tags or "",
                answer=faq.answer,
            ),
            answer_text=faq.answer,
            label=label_for_entry(
                "faq", faq.id, question=faq.question, answer=faq.answer
            ),
        )
    except Exception as exc:
        logger.warning("sync_faq_embedding failed id=%s: %s", getattr(faq, "id", None), exc)


async def sync_policy_embedding(db: AsyncSession, policy: HospitalPolicy) -> None:
    try:
        store = EmbeddingStore(db)
        await store.upsert_kb_entry(
            hospital_id=policy.hospital_id,
            source_type="policy",
            source_id=policy.id,
            language=policy.language or "en",
            embed_text=build_embed_text(
                "policy",
                title=policy.title,
                category=policy.category or "",
                body=policy.body,
            ),
            answer_text=policy.body,
            label=label_for_entry(
                "policy",
                policy.id,
                title=policy.title,
                body=policy.body,
                category=policy.category or "",
            ),
        )
    except Exception as exc:
        logger.warning(
            "sync_policy_embedding failed id=%s: %s", getattr(policy, "id", None), exc
        )


async def sync_document_embedding(db: AsyncSession, doc: HospitalVoiceDocument) -> None:
    try:
        store = EmbeddingStore(db)
        await store.upsert_kb_entry(
            hospital_id=doc.hospital_id,
            source_type="document",
            source_id=doc.id,
            language=doc.language or "en",
            embed_text=build_embed_text(
                "document", title=doc.title, content=doc.content
            ),
            answer_text=doc.content,
            label=label_for_entry(
                "document", doc.id, title=doc.title, content=doc.content
            ),
        )
    except Exception as exc:
        logger.warning(
            "sync_document_embedding failed id=%s: %s", getattr(doc, "id", None), exc
        )


async def deactivate_kb_embedding(
    db: AsyncSession, source_type: str, source_id: int, hospital_id: int
) -> None:
    try:
        await EmbeddingStore(db).deactivate_entry(source_type, source_id, hospital_id)
    except Exception as exc:
        logger.warning(
            "deactivate_kb_embedding failed %s:%s: %s", source_type, source_id, exc
        )
