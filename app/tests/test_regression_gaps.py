import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime

from app.ai.rag.retriever import KnowledgeRetriever
from app.models.hospital_voice_model import HospitalFaq
from app.models.hospital_voice_document_chunk import HospitalVoiceDocumentChunk
from app.schemas.hospital_voice_schema import HospitalFaqCreate
from app.services.hospital_knowledge_service import HospitalKnowledgeService
from app.services.voice_assistant_service import VoiceAssistantService
from app.ai.voice_appointment_assistant.schemas import VoiceState
from app.services.faq_retrieval_service import FaqAnswer


@pytest.mark.asyncio
async def test_p0_1_existing_voice_faq_integrity():
    """
    P0-1. EXISTING VOICE FAQ INTEGRITY
    Verify that adding document_chunk knowledge does NOT degrade existing FAQ retrieval.
    """
    mock_db = AsyncMock()
    retriever = KnowledgeRetriever(mock_db)
    
    # Setup Fake Embeddings
    fake_faq_vector = [0.0] * 1536
    fake_faq_vector[0] = 0.99
    
    fake_chunk_vector = [0.0] * 1536
    fake_chunk_vector[1] = 0.99
    
    # Existing FAQ in the Redis/Embedding Store
    faq_entry = {
        "source": "faq", "id": 1, "hospital_id": 1, "language": "en",
        "embedding": fake_faq_vector, "text": "9 AM to 5 PM",
        "label": "[faq:1] Q: What are the OPD hours?\nA: 9 AM to 5 PM",
        "content_hash": "hash1"
    }
    
    # A random unrelated chunk
    chunk_entry = HospitalVoiceDocumentChunk(
        id=99, document_id=1, text="Unrelated chunks about billing."
    )
    chunk_entry_dict = {
        "source": "document_chunk", "id": 99, "hospital_id": 1, "language": "en",
        "embedding": fake_chunk_vector, "text": "Unrelated chunks about billing.",
        "label": "[document_chunk:99] Title: Billing\nContent: Unrelated chunks about billing.",
        "content_hash": "hash2"
    }
    
    retriever.store = AsyncMock()
    retriever.store.list_active_vectors.return_value = [faq_entry, chunk_entry_dict]
    
    faq_db_entry = HospitalFaq(
        id=1, hospital_id=1, question="What are the OPD hours?", answer="9 AM to 5 PM", language="en", is_active=True
    )
    retriever.faq_repo = AsyncMock()
    retriever.faq_repo.list_for_hospital.return_value = [faq_db_entry]
    
    retriever.policy_repo = AsyncMock()
    retriever.policy_repo.list_for_hospital.return_value = []
    retriever.doc_repo = AsyncMock()
    retriever.doc_repo.list_for_hospital.return_value = []
    
    retriever.chunk_repo = AsyncMock()
    retriever.chunk_repo.list_for_hospital.return_value = [chunk_entry]
    
    retriever.embedder = AsyncMock()
    retriever.embedder.embed_text.return_value = fake_faq_vector
    
    chunks = await retriever.retrieve(
        hospital_id=1, 
        query="What are the OPD hours?", 
        language="en", 
        top_k=5
    )
    
    assert len(chunks) > 0, "No chunks retrieved!"
    # Ensure the FAQ is correctly ranked/selected
    assert chunks[0].source == "faq", "FAQ should be ranked first"
    assert chunks[0].id == 1
    assert "9 AM to 5 PM" in chunks[0].text


@pytest.mark.asyncio
async def test_p0_2_hospital_knowledge_crud_celery_dispatch():
    """
    P0-2. HOSPITAL KNOWLEDGE CRUD -> CELERY DISPATCH
    Verify existing FAQ CRUD behavior after the new async embedding architecture.
    """
    mock_db = AsyncMock()
    svc = HospitalKnowledgeService(mock_db)
    
    payload = HospitalFaqCreate(
        hospital_id=1, 
        question="Q", 
        answer="A", 
        language="en"
    )
    
    svc.faq_repo = AsyncMock()
    new_faq = HospitalFaq(
        id=123, 
        hospital_id=1, 
        question="Q", 
        answer="A",
        language="en",
        is_active=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    svc.faq_repo.create.return_value = new_faq
    
    with patch("app.services.faq_ai_dispatcher.generate_faq_embedding") as mock_task:
        result = await svc.create_faq(payload)
        
        # Verify CRUD returns successfully
        assert result.id == 123
        
        # Verify embedding work is dispatched asynchronously
        mock_task.delay.assert_called_once()
        # Verify that it didn't wait synchronously on celery
        assert not hasattr(mock_task.delay.return_value, '__await__'), "delay() should be synchronous"


@pytest.mark.asyncio
async def test_p0_3_voice_assistant_openai_error_fallback():
    """
    P0-3. VOICE ASSISTANT OPENAI ERROR FALLBACK
    Verify that FAQ-AI/OpenAI sanitized errors do not crash the Voice Assistant flow.
    """
    mock_db = AsyncMock()
    svc = VoiceAssistantService(mock_db)
    
    # We need to setup a VoiceState in cache so handle_turn can load it
    state = VoiceState(call_sid="TEST_SID", hospital_id=1, language="en", step="faq_question")
    
    with patch("app.services.voice_assistant_service.cache_get", new=AsyncMock(return_value=state.to_dict())):
        with patch("app.services.voice_assistant_service.cache_set", new=AsyncMock()):
            svc.faq_service = AsyncMock()
            svc.faq_service.answer.return_value = FaqAnswer(
                found=False,
                answer="AI service temporarily unavailable",
                source="none",
                faq_hit=False,
                ai_fallback=True,
                should_transfer=False
            )
            
            # Mock the assistant generating a response
            svc.assistant = MagicMock()
            
            # The assistant returns a VoiceAssistantTurn
            class FakeTurn:
                def __init__(self):
                    self.state = state
                    self.output_text = "Let me check that."
                    self.transfer_required = False
                    self.action_required = False
                    self.booking_json = None
            
            svc.assistant.process_turn.return_value = FakeTurn()
            
            # Mock twilio gather generation
            svc._build_gather_twiml = MagicMock(return_value="<Response></Response>")
            
            try:
                response = await svc.handle_turn(
                    call_sid="TEST_SID",
                    speech_result="What are the OPD hours?",
                    confidence=0.9
                )
                assert response is not None
            except Exception as e:
                pytest.fail(f"Voice Assistant crashed with error: {e}")
