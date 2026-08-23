"""
Repository for knowledge_embeddings table.

Integration: used only by EmbeddingStore / KnowledgeRetriever sync paths.
"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_embedding_model import KnowledgeEmbedding


class KnowledgeEmbeddingRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_source(
        self, source_type: str, source_id: int
    ) -> KnowledgeEmbedding | None:
        result = await self.db.execute(
            select(KnowledgeEmbedding).where(
                KnowledgeEmbedding.source_type == source_type,
                KnowledgeEmbedding.source_id == source_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_active_for_hospital(
        self, hospital_id: int, language: str | None = None
    ) -> list[KnowledgeEmbedding]:
        query = select(KnowledgeEmbedding).where(
            KnowledgeEmbedding.hospital_id == hospital_id,
            KnowledgeEmbedding.is_active.is_(True),
        )
        if language:
            query = query.where(KnowledgeEmbedding.language == language)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def upsert(
        self,
        *,
        hospital_id: int,
        source_type: str,
        source_id: int,
        language: str,
        content_hash: str,
        embedding_model: str,
        embedding: list[float],
        is_active: bool = True,
    ) -> KnowledgeEmbedding:
        row = await self.get_by_source(source_type, source_id)
        payload = json.dumps(embedding)
        if row:
            row.hospital_id = hospital_id
            row.language = language
            row.content_hash = content_hash
            row.embedding_model = embedding_model
            row.embedding = payload
            row.is_active = is_active
            await self.db.flush()
            await self.db.refresh(row)
            return row

        row = KnowledgeEmbedding(
            hospital_id=hospital_id,
            source_type=source_type,
            source_id=source_id,
            language=language,
            content_hash=content_hash,
            embedding_model=embedding_model,
            embedding=payload,
            is_active=is_active,
        )
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def deactivate(self, source_type: str, source_id: int) -> None:
        row = await self.get_by_source(source_type, source_id)
        if not row:
            return
        row.is_active = False
        await self.db.flush()
