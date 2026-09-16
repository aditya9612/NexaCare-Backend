from typing import Sequence
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hospital_voice_document_chunk import HospitalVoiceDocumentChunk
from app.models.hospital_voice_model import HospitalVoiceDocument

class HospitalVoiceDocumentChunkRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_for_hospital(self, hospital_id: int) -> Sequence[HospitalVoiceDocumentChunk]:
        stmt = (
            select(HospitalVoiceDocumentChunk)
            .join(HospitalVoiceDocument)
            .where(
                HospitalVoiceDocument.hospital_id == hospital_id,
                HospitalVoiceDocument.is_active == True,
            )
            .options(selectinload(HospitalVoiceDocumentChunk.document))
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def list_by_document(self, document_id: int) -> Sequence[HospitalVoiceDocumentChunk]:
        stmt = (
            select(HospitalVoiceDocumentChunk)
            .where(HospitalVoiceDocumentChunk.document_id == document_id)
            .order_by(HospitalVoiceDocumentChunk.chunk_index)
            .options(selectinload(HospitalVoiceDocumentChunk.document))
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    def add(self, chunk: HospitalVoiceDocumentChunk) -> None:
        self.db.add(chunk)

    async def delete_by_document(self, document_id: int) -> None:
        from sqlalchemy import delete
        stmt = delete(HospitalVoiceDocumentChunk).where(HospitalVoiceDocumentChunk.document_id == document_id)
        await self.db.execute(stmt)

