import logging
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.faq_ai_chunking_service import FaqAiChunkingService
from app.repositories.hospital_voice_repository import HospitalVoiceDocumentRepository
from app.repositories.hospital_voice_document_chunk_repository import HospitalVoiceDocumentChunkRepository
from app.models.hospital_voice_model import HospitalVoiceDocument
from app.models.hospital_voice_document_chunk import HospitalVoiceDocumentChunk
from app.utils.ocr import extract_text_from_pdf_bytes
from app.services.faq_ai_dispatcher import FaqAiDispatcher

logger = logging.getLogger(__name__)

class FaqAiDocumentService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.doc_repo = HospitalVoiceDocumentRepository(db)
        self.chunk_repo = HospitalVoiceDocumentChunkRepository(db)
        self.chunking_svc = FaqAiChunkingService()
        self.dispatcher = FaqAiDispatcher(db)
        
    async def process_pdf(self, hospital_id: int, title: str, pdf_bytes: bytes, source: str | None = None) -> HospitalVoiceDocument:
        logger.info(f"Processing PDF '{title}' for hospital {hospital_id}")
        
        # 1. Extract text
        text = extract_text_from_pdf_bytes(pdf_bytes)
        if not text.strip():
            raise ValueError("No extractable text found in PDF")
            
        # 2. Create chunks
        text_chunks = self.chunking_svc.chunk_text(text)
        if not text_chunks:
            raise ValueError("Extracted text could not be chunked (too short or empty)")
            
        # 3. Create document record
        doc = HospitalVoiceDocument(
            hospital_id=hospital_id,
            title=title,
            source=source,
            content=text,
            is_active=True,
            language="en"
        )
        self.db.add(doc)
        await self.db.flush()
        
        # 4. Create chunk records
        for i, chunk_text in enumerate(text_chunks):
            chunk = HospitalVoiceDocumentChunk(
                document_id=doc.id,
                chunk_index=i,
                text=chunk_text
            )
            self.chunk_repo.add(chunk)
            
        await self.db.flush()
        
        # 5. Commit and dispatch safely
        await self.dispatcher.dispatch_document_embedding(hospital_id, doc.id)
        
        return doc
        
    async def deactivate_document(self, hospital_id: int, document_id: int) -> None:
        doc = await self.doc_repo.get_by_id(document_id)
        if not doc or doc.hospital_id != hospital_id:
            raise ValueError("Document not found or access denied")
            
        doc.is_active = False
        await self.doc_repo.update(doc)
        # Note: Chunks are dynamically excluded because KnowledgeRetriever
        # queries chunks joined with HospitalVoiceDocument where is_active == True.
        # We don't need to physically delete the chunks.
        
        await self.db.flush()
        
        # Dispatch a task to remove the vectors from Redis/KnowledgeEmbedding
        await self.dispatcher.dispatch_document_deactivation(hospital_id, document_id)
