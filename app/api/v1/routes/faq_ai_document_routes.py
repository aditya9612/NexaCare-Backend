from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.dependencies import get_db, get_current_user
from app.core.chat_auth import verify_chat_hospital_scope
from app.services.faq_ai_document_service import FaqAiDocumentService
from app.models.user_model import User
from app.utils.faq_ai_rate_limiter import faq_ai_document_rate_limiter
from app.repositories.audit_repository import AuditRepository

router = APIRouter(prefix="/faq-ai/documents", tags=["FAQ AI Documents"])

@router.post("/upload")
async def upload_document(
    hospital_id: int = Form(...),
    title: str = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    verify_chat_hospital_scope(current_user, hospital_id)
    await faq_ai_document_rate_limiter.check(hospital_id, current_user.id)
    
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
        
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Invalid MIME type")
        
    pdf_bytes = await file.read()
    
    # Arbitrary 20MB limit for example
    if len(pdf_bytes) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large")
        
    service = FaqAiDocumentService(db)
    
    try:
        doc = await service.process_pdf(
            hospital_id=hospital_id,
            title=title,
            pdf_bytes=pdf_bytes,
            source=file.filename
        )
        
        await AuditRepository(db).create(
            action="create",
            resource="documents",
            user_id=current_user.id,
            resource_id=str(doc.id)
        )
        
        return {"status": "success", "document_id": doc.id, "message": "Document uploaded and chunking started"}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Document processing failed")

@router.delete("/{document_id}")
async def delete_document(
    document_id: int,
    hospital_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    verify_chat_hospital_scope(current_user, hospital_id)
    await faq_ai_document_rate_limiter.check(hospital_id, current_user.id)
    
    service = FaqAiDocumentService(db)
    try:
        await service.deactivate_document(hospital_id, document_id)
        
        await AuditRepository(db).create(
            action="deactivate",
            resource="documents",
            user_id=current_user.id,
            resource_id=str(document_id)
        )
        
        return {"status": "success", "message": "Document deactivated"}
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
